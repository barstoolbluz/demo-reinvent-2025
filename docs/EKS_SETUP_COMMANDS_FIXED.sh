#!/usr/bin/env bash
# EKS Setup Script - Step-by-step commands for re:Invent 2025 Demo
# Run these commands from the xplatform-cli-tools Flox environment
# Usage: From within flox environment: bash /path/to/this/script.sh

set -euo pipefail

# Source flox wrapper functions if available (for 1password-wrapped aws/gh/git)
if [[ -n "${FLOX_ENV_CACHE:-}" ]] && [[ -f "${FLOX_ENV_CACHE}/shell/wrapper.bash" ]]; then
  source "${FLOX_ENV_CACHE}/shell/wrapper.bash"

  # If using 1password wrapper, export AWS credentials for tools like eksctl
  if [[ -n "${OP_SESSION_TOKEN:-}" ]]; then
    export AWS_ACCESS_KEY_ID=$(op read "op://${OP_AWS_VAULT}/${OP_AWS_CREDENTIALS_ITEM}/${OP_AWS_USERNAME_FIELD}" --session "$OP_SESSION_TOKEN" 2>/dev/null)
    export AWS_SECRET_ACCESS_KEY=$(op read "op://${OP_AWS_VAULT}/${OP_AWS_CREDENTIALS_ITEM}/${OP_AWS_CREDENTIALS_FIELD}" --session "$OP_SESSION_TOKEN" 2>/dev/null)
  fi
fi

# Check required dependencies
for cmd in aws kubectl eksctl jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ ERROR: Required command '$cmd' not found in PATH"
    echo "Please install $cmd or run from xplatform-cli-tools Flox environment"
    exit 1
  fi
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# ============================================================================
# STEP 1: Set Environment Variables
# ============================================================================
echo "===================================================================="
echo "STEP 1: Setting up environment variables"
echo "===================================================================="

# Cluster configuration
export CLUSTER_NAME="${CLUSTER_NAME:-reinvent-demo-test}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export EKS_VERSION="${EKS_VERSION:-1.28}"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Validate AWS credentials
if [[ -z "$AWS_ACCOUNT_ID" ]] || [[ "$AWS_ACCOUNT_ID" == "None" ]] || [[ "$AWS_ACCOUNT_ID" =~ "error" ]] || [[ "$AWS_ACCOUNT_ID" =~ "Unable" ]] || ! [[ "$AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]; then
  log_error "Failed to get AWS account ID. Got: '$AWS_ACCOUNT_ID'"
  log_error "Please check your AWS credentials."
  log_error "If using flox with 1password, ensure you're running this script with:"
  log_error "  flox activate -- bash /path/to/script.sh"
  exit 1
fi

# GitHub repository (CHANGE THIS to your actual repo)
export GITHUB_ORG="${GITHUB_ORG:-barstoolbluz}"  # Change to your GitHub username/org
export GITHUB_REPO="${GITHUB_REPO:-amazon-reinvent-2025-demo-runtime-test}"  # Your repo name

# FloxHub configuration
export FLOX_HUB_ORG="${FLOX_HUB_ORG:-flox}"  # Change if using different org
export FLOXHUB_CLIENT_ID="${FLOXHUB_CLIENT_ID:-}"  # Set for private environments
export FLOXHUB_CLIENT_SECRET="${FLOXHUB_CLIENT_SECRET:-}"  # Set for private environments

log_info "Configuration:"
echo "   Cluster: $CLUSTER_NAME"
echo "   Region: $AWS_REGION"
echo "   EKS Version: $EKS_VERSION"
echo "   Account: $AWS_ACCOUNT_ID"
echo "   GitHub: $GITHUB_ORG/$GITHUB_REPO"
echo ""

# Save config for later use
cat > /tmp/eks-setup-config.env <<EOF
export CLUSTER_NAME="$CLUSTER_NAME"
export AWS_REGION="$AWS_REGION"
export EKS_VERSION="$EKS_VERSION"
export AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"
export GITHUB_ORG="$GITHUB_ORG"
export GITHUB_REPO="$GITHUB_REPO"
export FLOX_HUB_ORG="$FLOX_HUB_ORG"
EOF

log_info "Config saved to /tmp/eks-setup-config.env"
echo "   You can reload with: source /tmp/eks-setup-config.env"
echo ""

# ============================================================================
# STEP 2: Create EKS Cluster
# ============================================================================
echo "===================================================================="
echo "STEP 2: Creating EKS cluster (this takes ~15-20 minutes)"
echo "===================================================================="

# Check if cluster already exists
if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  log_warn "Cluster '$CLUSTER_NAME' already exists, skipping creation"
else
  read -p "Create EKS cluster now? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    eksctl create cluster \
      --name "$CLUSTER_NAME" \
      --region "$AWS_REGION" \
      --version "$EKS_VERSION" \
      --nodegroup-name standard-workers \
      --node-type t3.medium \
      --nodes 2 \
      --nodes-min 1 \
      --nodes-max 3 \
      --managed \
      --with-oidc

    log_info "Cluster created!"
  else
    log_warn "Skipping cluster creation"
  fi
fi
echo ""

# ============================================================================
# STEP 3: Update kubeconfig
# ============================================================================
echo "===================================================================="
echo "STEP 3: Configuring kubectl"
echo "===================================================================="

# Verify cluster exists before configuring kubectl
if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  log_error "Cluster '$CLUSTER_NAME' does not exist. Cannot configure kubectl."
  log_error "Please create the cluster first or check the cluster name."
  exit 1
fi

aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

log_info "kubectl configured"
kubectl get nodes
echo ""

# ============================================================================
# STEP 4: Install Flox on EKS Nodes
# ============================================================================
echo "===================================================================="
echo "STEP 4: Installing Flox and containerd shim on all nodes"
echo "===================================================================="

# Get instance IDs
INSTANCE_IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:eks:cluster-name,Values=$CLUSTER_NAME" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" \
  --region "$AWS_REGION" \
  --output text)

if [[ -z "$INSTANCE_IDS" ]]; then
  log_error "No instances found for cluster $CLUSTER_NAME"
  exit 1
fi

echo "Found instances: $INSTANCE_IDS"
echo ""

read -p "Install Flox on nodes via SSM? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Create installation script
  cat > /tmp/install-flox.sh <<'FLOXEOF'
#!/bin/bash
set -euo pipefail

echo "Installing Flox..."
# Check if Flox is already installed
if rpm -q flox >/dev/null 2>&1; then
  echo "Flox is already installed, skipping installation"
else
  # Download and install Flox RPM package
  curl -fsSL https://downloads.flox.dev/by-env/stable/rpm/flox-1.7.7.x86_64-linux.rpm -o /tmp/flox.rpm
  sudo rpm --import https://downloads.flox.dev/by-env/stable/rpm/flox-archive-keyring.asc || true
  sudo rpm -ivh /tmp/flox.rpm
fi

echo "Activating Flox shim installer..."
# Flox shim installer is idempotent, always run it
if [[ -x /root/.flox/bin/flox ]]; then
  FLOX_BIN="/root/.flox/bin/flox"
elif [[ -x /home/ec2-user/.flox/bin/flox ]]; then
  FLOX_BIN="/home/ec2-user/.flox/bin/flox"
elif command -v flox >/dev/null 2>&1; then
  FLOX_BIN="flox"
else
  echo "ERROR: Flox binary not found after installation"
  exit 1
fi

echo "Using Flox at: $FLOX_BIN"

# Debug: Check before activation
echo "DEBUG: Files before activation:"
ls -la /usr/local/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /usr/local/bin"
ls -la /opt/flox/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /opt/flox/bin"

"$FLOX_BIN" activate -r flox/containerd-shim-flox-installer --trust

# Debug: Check immediately after activation
echo "DEBUG: Files immediately after activation:"
ls -la /usr/local/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /usr/local/bin"
ls -la /opt/flox/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /opt/flox/bin"

# Wait a moment for shim to be fully written
sleep 2

# Debug: Check after sleep
echo "DEBUG: Files after 2 second sleep:"
ls -la /usr/local/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /usr/local/bin"
ls -la /opt/flox/bin/containerd-shim* 2>/dev/null || echo "  No shim files in /opt/flox/bin"

echo "Verifying shim installation..."
# Shim can be v1 or v2, and in /usr/local/bin or /opt/flox/bin
if [[ -f /usr/local/bin/containerd-shim-flox-v2 ]]; then
  echo "SUCCESS: Shim found at /usr/local/bin/containerd-shim-flox-v2"
elif [[ -f /usr/local/bin/containerd-shim-flox-v1 ]]; then
  echo "SUCCESS: Shim found at /usr/local/bin/containerd-shim-flox-v1"
elif [[ -f /opt/flox/bin/containerd-shim-flox-v2 ]]; then
  echo "SUCCESS: Shim found at /opt/flox/bin/containerd-shim-flox-v2"
elif [[ -f /opt/flox/bin/containerd-shim-flox-v1 ]]; then
  echo "SUCCESS: Shim found at /opt/flox/bin/containerd-shim-flox-v1"
else
  echo "ERROR: Shim not found in /usr/local/bin or /opt/flox/bin"
  echo "Full directory listings:"
  ls -la /usr/local/bin/ 2>/dev/null | grep -E "(containerd|flox)" || echo "  No containerd/flox files in /usr/local/bin"
  ls -la /opt/flox/bin/ 2>/dev/null || echo "  /opt/flox/bin does not exist"
  exit 1
fi

echo "Restarting containerd..."
systemctl restart containerd

echo "Verifying containerd config..."
if ! grep -q "flox" /etc/containerd/config.toml; then
  echo "WARNING: Flox runtime not found in containerd config"
  exit 1
fi

echo "SUCCESS: Flox installed and configured"
FLOXEOF

  # Verify SSM prerequisites before attempting installation
  log_info "Verifying SSM agent availability on instances..."
  echo ""

  INSTANCES_NOT_READY=""
  for INSTANCE_ID in $INSTANCE_IDS; do
    # Check if instance is managed by SSM
    SSM_STATUS=$(aws ssm describe-instance-information \
      --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query "InstanceInformationList[0].PingStatus" \
      --output text 2>/dev/null || echo "")

    if [[ -z "$SSM_STATUS" ]] || [[ "$SSM_STATUS" == "None" ]]; then
      log_error "Instance $INSTANCE_ID not managed by SSM"
      log_error "  Possible causes:"
      log_error "    - SSM agent not installed"
      log_error "    - SSM agent not running"
      log_error "    - Instance profile missing AmazonSSMManagedInstanceCore policy"
      INSTANCES_NOT_READY="$INSTANCES_NOT_READY $INSTANCE_ID"
    elif [[ "$SSM_STATUS" != "Online" ]]; then
      log_warn "Instance $INSTANCE_ID SSM status: $SSM_STATUS (not Online)"
      log_warn "  SSM commands may fail or be delayed"
      INSTANCES_NOT_READY="$INSTANCES_NOT_READY $INSTANCE_ID"
    else
      log_info "Instance $INSTANCE_ID is SSM-ready (Status: $SSM_STATUS)"
    fi
  done

  # Exit if any instances not ready
  if [[ -n "$INSTANCES_NOT_READY" ]]; then
    log_error ""
    log_error "The following instances are not ready for SSM:$INSTANCES_NOT_READY"
    log_error ""
    log_error "To fix this, ensure each instance has:"
    log_error "  1. SSM agent installed (pre-installed on Amazon Linux 2 and newer)"
    log_error "  2. SSM agent running: systemctl status amazon-ssm-agent"
    log_error "  3. Instance profile with AmazonSSMManagedInstanceCore policy attached"
    log_error ""
    log_error "After fixing, re-run this script or skip to the next step"
    exit 1
  fi

  log_info "All instances are SSM-ready"
  echo ""

  # Upload and run script on all instances
  # Create JSON array of commands by reading the script line by line
  SCRIPT_COMMANDS=$(jq -R -s -c 'split("\n")' < /tmp/install-flox.sh)

  # Store command IDs for each instance
  declare -A COMMAND_IDS
  for INSTANCE_ID in $INSTANCE_IDS; do
    echo "Installing on $INSTANCE_ID..."

    COMMAND_ID=$(aws ssm send-command \
      --document-name "AWS-RunShellScript" \
      --instance-ids "$INSTANCE_ID" \
      --parameters "{\"commands\":$SCRIPT_COMMANDS}" \
      --region "$AWS_REGION" \
      --query "Command.CommandId" \
      --output text)

    if [[ -z "$COMMAND_ID" ]]; then
      log_error "Failed to send SSM command to instance $INSTANCE_ID"
      exit 1
    fi

    COMMAND_IDS[$INSTANCE_ID]=$COMMAND_ID
    echo "Command ID: $COMMAND_ID"
  done

  log_info "Installation commands sent"
  echo "⏳ Waiting 90 seconds for installations to complete..."
  sleep 90

  # Check status for each instance
  echo ""
  log_info "Verifying installation status..."
  echo ""

  FAILED_INSTANCES=""
  for INSTANCE_ID in $INSTANCE_IDS; do
    echo "Checking status for $INSTANCE_ID..."

    # Get the command ID for this instance
    COMMAND_ID="${COMMAND_IDS[$INSTANCE_ID]}"

    # Get command status using get-command-invocation (more reliable than list)
    COMMAND_STATUS=$(aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query "Status" \
      --output text 2>/dev/null || echo "")

    if [[ -z "$COMMAND_STATUS" ]]; then
      log_error "Failed to get command status for $INSTANCE_ID"
      FAILED_INSTANCES="$FAILED_INSTANCES $INSTANCE_ID"
      continue
    fi

    echo "Status: $COMMAND_STATUS"

    # Show output (first 20 lines)
    echo "Output:"
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query "StandardOutputContent" \
      --output text 2>/dev/null | head -20

    echo ""

    # Check if successful
    if [[ "$COMMAND_STATUS" != "Success" ]]; then
      log_error "Flox installation failed on $INSTANCE_ID (Status: $COMMAND_STATUS)"

      # Show error output if available
      ERROR_OUTPUT=$(aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE_ID" \
        --region "$AWS_REGION" \
        --query "StandardErrorContent" \
        --output text 2>/dev/null)

      if [[ -n "$ERROR_OUTPUT" ]]; then
        echo "Error output:"
        echo "$ERROR_OUTPUT" | head -20
      fi

      FAILED_INSTANCES="$FAILED_INSTANCES $INSTANCE_ID"
    else
      log_info "Flox installation successful on $INSTANCE_ID"
    fi
    echo ""
  done

  # Exit if any failures
  if [[ -n "$FAILED_INSTANCES" ]]; then
    log_error "Flox installation failed on instances:$FAILED_INSTANCES"
    log_error "Please check the output above for details"
    exit 1
  fi

  log_info "All Flox installations completed successfully"
  echo ""

  # Clean up
  rm -f /tmp/install-flox.sh
else
  log_warn "Skipping Flox installation"
fi
echo ""

# ============================================================================
# STEP 4b: Configure FloxHub Authentication (for private environments)
# ============================================================================
echo "===================================================================="
echo "STEP 4b: Configuring FloxHub authentication"
echo "===================================================================="

# Determine FloxHub token with precedence:
# 1. FLOX_FLOXHUB_TOKEN environment variable (highest priority)
# 2. Read from ~/.config/flox/flox.toml
# 3. Generate from FLOXHUB_CLIENT_ID + FLOXHUB_CLIENT_SECRET
# 4. Skip if none available

FLOX_FLOXHUB_TOKEN="${FLOX_FLOXHUB_TOKEN:-}"

if [[ -z "$FLOX_FLOXHUB_TOKEN" ]]; then
  # Try to read from flox config file
  FLOX_CONFIG_FILE="${HOME}/.config/flox/flox.toml"
  if [[ -f "$FLOX_CONFIG_FILE" ]]; then
    log_info "Reading FloxHub token from $FLOX_CONFIG_FILE..."
    FLOX_FLOXHUB_TOKEN=$(grep '^floxhub_token' "$FLOX_CONFIG_FILE" 2>/dev/null | cut -d'"' -f2 || echo "")

    if [[ -n "$FLOX_FLOXHUB_TOKEN" ]]; then
      log_info "FloxHub token found in config file"
    fi
  fi
fi

if [[ -z "$FLOX_FLOXHUB_TOKEN" ]] && [[ -n "$FLOXHUB_CLIENT_ID" ]] && [[ -n "$FLOXHUB_CLIENT_SECRET" ]]; then
  # Generate token from client credentials
  log_info "Generating FloxHub token from client credentials..."
  FLOX_FLOXHUB_TOKEN=$(curl --fail --silent --request POST \
    --url https://auth.flox.dev/oauth/token \
    --header 'content-type: application/x-www-form-urlencoded' \
    --data "client_id=$FLOXHUB_CLIENT_ID" \
    --data "audience=https://hub.flox.dev/api" \
    --data "grant_type=client_credentials" \
    --data "client_secret=$FLOXHUB_CLIENT_SECRET" \
    | jq -e .access_token -r 2>/dev/null || echo "")

  if [[ -z "$FLOX_FLOXHUB_TOKEN" ]] || [[ "$FLOX_FLOXHUB_TOKEN" == "null" ]]; then
    log_error "Failed to generate FloxHub token from client credentials"
    log_error "Please check FLOXHUB_CLIENT_ID and FLOXHUB_CLIENT_SECRET"
    exit 1
  fi

  log_info "FloxHub token generated successfully"
fi

if [[ -n "$FLOX_FLOXHUB_TOKEN" ]]; then
  log_info "Configuring FloxHub authentication on all nodes..."

  # Create inline commands to configure flox auth on nodes
  # We build the commands array directly with the token embedded
  AUTH_COMMANDS=$(jq -n -c \
    --arg token "$FLOX_FLOXHUB_TOKEN" \
    '[
      "mkdir -p ~/.config/flox",
      "cat > ~/.config/flox/flox.toml << \"FLOXEOF\"\nfloxhub_token = \"\($token)\"\nFLOXEOF",
      "echo \"FloxHub token configured\"",
      "export FLOX_FLOXHUB_TOKEN=\($token)",
      "flox auth status || echo \"Auth status check completed\""
    ]')

  # Store command IDs for verification
  declare -A AUTH_COMMAND_IDS

  for INSTANCE_ID in $INSTANCE_IDS; do
    echo "Configuring FloxHub auth on $INSTANCE_ID..."

    # Send auth configuration commands
    AUTH_COMMAND_ID=$(aws ssm send-command \
      --document-name "AWS-RunShellScript" \
      --instance-ids "$INSTANCE_ID" \
      --parameters "{\"commands\":$AUTH_COMMANDS}" \
      --region "$AWS_REGION" \
      --query "Command.CommandId" \
      --output text)

    if [[ -z "$AUTH_COMMAND_ID" ]]; then
      log_error "Failed to send FloxHub auth command to instance $INSTANCE_ID"
      exit 1
    fi

    AUTH_COMMAND_IDS[$INSTANCE_ID]=$AUTH_COMMAND_ID
    echo "Auth command ID: $AUTH_COMMAND_ID"
  done

  log_info "FloxHub authentication commands sent"
  echo "⏳ Waiting 15 seconds for authentication to complete..."
  sleep 15

  # Verify authentication
  log_info "Verifying FloxHub authentication..."
  AUTH_FAILED=""
  for INSTANCE_ID in $INSTANCE_IDS; do
    echo "Checking auth status on $INSTANCE_ID..."

    AUTH_COMMAND_ID="${AUTH_COMMAND_IDS[$INSTANCE_ID]}"

    STATUS_RESULT=$(aws ssm get-command-invocation \
      --command-id "$AUTH_COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' \
      --output json 2>/dev/null || echo '{}')

    AUTH_STATUS=$(echo "$STATUS_RESULT" | jq -r '.Status // "Unknown"')
    AUTH_OUTPUT=$(echo "$STATUS_RESULT" | jq -r '.Output // ""')

    if [[ "$AUTH_STATUS" == "Success" ]]; then
      log_info "FloxHub authentication successful on $INSTANCE_ID"
    else
      log_warn "FloxHub authentication status: $AUTH_STATUS on $INSTANCE_ID"
      if [[ -n "$AUTH_OUTPUT" ]]; then
        echo "Output: $AUTH_OUTPUT" | head -10
      fi
      AUTH_FAILED="$AUTH_FAILED $INSTANCE_ID"
    fi
  done

  if [[ -n "$AUTH_FAILED" ]]; then
    log_warn "FloxHub authentication verification unclear on some instances:$AUTH_FAILED"
    log_warn "Continuing anyway - nodes may still be able to pull environments"
  else
    log_info "FloxHub authentication configured successfully on all nodes"
  fi
else
  log_warn "No FloxHub authentication configured"
  log_warn "Nodes will only be able to pull public Flox environments"
  log_warn ""
  log_warn "To enable authentication for private environments, use one of:"
  log_warn "  1. Set FLOX_FLOXHUB_TOKEN environment variable"
  log_warn "  2. Run 'flox auth login' (stores token in ~/.config/flox/flox.toml)"
  log_warn "  3. Set FLOXHUB_CLIENT_ID and FLOXHUB_CLIENT_SECRET"
fi
echo ""

# ============================================================================
# STEP 5: Label Nodes and Create RuntimeClass
# ============================================================================
echo "===================================================================="
echo "STEP 5: Labeling nodes and creating RuntimeClass"
echo "===================================================================="

# Verify cluster has nodes
NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
if [[ -z "$NODE_COUNT" ]] || [[ "$NODE_COUNT" -eq 0 ]]; then
  log_error "Cluster has no nodes. Cannot label nodes or install Flox runtime."
  log_error "Please create nodes first or check cluster configuration."
  exit 1
fi

log_info "Found $NODE_COUNT node(s)"

# Label all nodes
kubectl label nodes --all flox-runtime=enabled --overwrite
log_info "Nodes labeled"

# Create RuntimeClass
kubectl apply -f - <<EOF
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: flox
handler: flox
scheduling:
  nodeSelector:
    flox-runtime: enabled
EOF

log_info "RuntimeClass created"
kubectl get runtimeclass
echo ""

# ============================================================================
# STEP 6: Create GitHub OIDC Provider
# ============================================================================
echo "===================================================================="
echo "STEP 6: Setting up GitHub OIDC provider"
echo "===================================================================="

read -p "Create GitHub OIDC provider? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Check if already exists
  EXISTING_OIDC=$(aws iam list-open-id-connect-providers \
    --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" \
    --output text || echo "")

  if [[ -n "$EXISTING_OIDC" ]]; then
    log_info "OIDC provider already exists"
    export OIDC_PROVIDER_ARN="$EXISTING_OIDC"
  else
    # GitHub OIDC thumbprint for token.actions.githubusercontent.com
    # This is the root CA certificate thumbprint for GitHub's OIDC provider
    # Current as of 2024-01. If GitHub rotates certificates, update from:
    # https://github.blog/changelog/ or retrieve with:
    # echo | openssl s_client -servername token.actions.githubusercontent.com -connect token.actions.githubusercontent.com:443 2>/dev/null | openssl x509 -fingerprint -sha1 -noout | cut -d'=' -f2 | tr -d ':' | tr '[:upper:]' '[:lower:]'
    GITHUB_OIDC_THUMBPRINT="6938fd4d98bab03faadb97b34396831e3780aea1"

    OIDC_PROVIDER_ARN=$(aws iam create-open-id-connect-provider \
      --url "https://token.actions.githubusercontent.com" \
      --client-id-list "sts.amazonaws.com" \
      --thumbprint-list "$GITHUB_OIDC_THUMBPRINT" \
      --query "OpenIDConnectProviderArn" \
      --output text)

    if [[ -z "$OIDC_PROVIDER_ARN" ]] || [[ "$OIDC_PROVIDER_ARN" == "None" ]]; then
      log_error "Failed to create OIDC provider"
      exit 1
    fi

    log_info "OIDC provider created"
    export OIDC_PROVIDER_ARN
  fi

  echo "OIDC Provider ARN: $OIDC_PROVIDER_ARN"

  # Append to config file
  echo "export OIDC_PROVIDER_ARN=\"$OIDC_PROVIDER_ARN\"" >> /tmp/eks-setup-config.env
else
  log_warn "Skipping OIDC provider creation"
  log_warn "Loading from existing config if available..."

  export OIDC_PROVIDER_ARN=$(aws iam list-open-id-connect-providers \
    --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" \
    --output text || echo "")

  if [[ -z "$OIDC_PROVIDER_ARN" ]]; then
    log_error "No OIDC provider found. Cannot continue with IAM role creation."
    exit 1
  fi
fi
echo ""

# ============================================================================
# STEP 7: Create IAM Role for GitHub Actions
# ============================================================================
echo "===================================================================="
echo "STEP 7: Creating IAM role for GitHub Actions"
echo "===================================================================="

export ROLE_NAME="GitHubActionsEKSDeployRole"

# Verify OIDC_PROVIDER_ARN is set
if [[ -z "$OIDC_PROVIDER_ARN" ]]; then
  log_error "OIDC_PROVIDER_ARN not set. Run step 6 first."
  exit 1
fi

# Create trust policy
cat > /tmp/github-actions-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "$OIDC_PROVIDER_ARN"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${GITHUB_REPO}:*"
        }
      }
    }
  ]
}
EOF

echo "Trust policy created for repo: $GITHUB_ORG/$GITHUB_REPO"
echo ""

read -p "Create IAM role? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Check if role exists
  if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    log_info "Role already exists, updating trust policy..."
    aws iam update-assume-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-document file:///tmp/github-actions-trust-policy.json
  else
    aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document file:///tmp/github-actions-trust-policy.json \
      --description "Role for GitHub Actions to deploy to EKS"
    log_info "Role created"
  fi

  export ROLE_ARN=$(aws iam get-role \
    --role-name "$ROLE_NAME" \
    --query 'Role.Arn' \
    --output text)

  if [[ -z "$ROLE_ARN" ]] || [[ "$ROLE_ARN" == "None" ]]; then
    log_error "Failed to get role ARN for $ROLE_NAME"
    exit 1
  fi

  echo "Role ARN: $ROLE_ARN"
  echo "export ROLE_ARN=\"$ROLE_ARN\"" >> /tmp/eks-setup-config.env
  echo "export ROLE_NAME=\"$ROLE_NAME\"" >> /tmp/eks-setup-config.env

  # Create and attach EKS policy
  cat > /tmp/github-actions-eks-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:ListClusters",
        "eks:DescribeNodegroup",
        "eks:ListNodegroups"
      ],
      "Resource": "*"
    }
  ]
}
EOF

  # Check if policy exists
  POLICY_ARN=$(aws iam list-policies \
    --scope Local \
    --query "Policies[?PolicyName=='GitHubActionsEKSPolicy'].Arn" \
    --output text || echo "")

  if [[ -z "$POLICY_ARN" ]]; then
    POLICY_ARN=$(aws iam create-policy \
      --policy-name GitHubActionsEKSPolicy \
      --policy-document file:///tmp/github-actions-eks-policy.json \
      --query 'Policy.Arn' \
      --output text)

    if [[ -z "$POLICY_ARN" ]] || [[ "$POLICY_ARN" == "None" ]]; then
      log_error "Failed to create IAM policy GitHubActionsEKSPolicy"
      exit 1
    fi

    log_info "Policy created: $POLICY_ARN"
  else
    log_info "Policy already exists: $POLICY_ARN"
  fi

  # Attach policy to role
  if aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "$POLICY_ARN" 2>/dev/null; then
    log_info "Policy attached to role"
  else
    log_info "Policy already attached"
  fi
else
  log_warn "Skipping IAM role creation"
fi
echo ""

# ============================================================================
# STEP 8: Configure EKS RBAC
# ============================================================================
echo "===================================================================="
echo "STEP 8: Configuring Kubernetes RBAC for GitHub Actions"
echo "===================================================================="

# Note: IAM OIDC workflow uses User identity (mapped from IAM role), not ServiceAccount
# ClusterRole and ClusterRoleBinding don't require a namespace

# Create ClusterRole
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: github-actions-deployer
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods", "services", "configmaps", "secrets", "persistentvolumeclaims"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list"]
EOF
log_info "ClusterRole created"

# Create ClusterRoleBinding
kubectl create clusterrolebinding github-actions-deployer \
  --clusterrole=github-actions-deployer \
  --user=github-actions:github-actions-deployer \
  --dry-run=client -o yaml | kubectl apply -f -
log_info "ClusterRoleBinding created"

# Map IAM role to Kubernetes
if [[ -n "${ROLE_ARN:-}" ]]; then
  read -p "Map IAM role to Kubernetes RBAC? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check if mapping already exists
    if eksctl get iamidentitymapping \
      --cluster "$CLUSTER_NAME" \
      --region "$AWS_REGION" 2>/dev/null | grep -q "$ROLE_ARN"; then
      log_info "IAM identity mapping already exists"
    else
      eksctl create iamidentitymapping \
        --cluster "$CLUSTER_NAME" \
        --region "$AWS_REGION" \
        --arn "$ROLE_ARN" \
        --username github-actions:github-actions-deployer

      log_info "IAM identity mapping created"
    fi

    # Verify
    echo ""
    echo "Current IAM identity mappings:"
    eksctl get iamidentitymapping --cluster "$CLUSTER_NAME" --region "$AWS_REGION"
  else
    log_warn "Skipping IAM identity mapping"
  fi
else
  log_warn "ROLE_ARN not set, skipping IAM mapping"
fi
echo ""

# ============================================================================
# STEP 9: Create Kubernetes Resources
# ============================================================================
echo "===================================================================="
echo "STEP 9: Creating Kubernetes namespace and resources"
echo "===================================================================="

# Create namespace
kubectl create namespace reinvent-demo --dry-run=client -o yaml | kubectl apply -f -
log_info "Namespace 'reinvent-demo' ready"

# Create PVC for ML models
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ml-models-cache
  namespace: reinvent-demo
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
EOF

log_info "PVC created"

# Create ConfigMap for AWS config
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-config
  namespace: reinvent-demo
data:
  region: "$AWS_REGION"
EOF

log_info "ConfigMap created"
echo ""

# ============================================================================
# STEP 10: Test Flox Pod
# ============================================================================
echo "===================================================================="
echo "STEP 10: Testing Flox pod deployment"
echo "===================================================================="

read -p "Deploy test Flox pod? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Delete existing test pod if present
  kubectl delete pod test-flox-pod -n reinvent-demo --ignore-not-found=true

  kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-flox-pod
  namespace: reinvent-demo
  annotations:
    flox.dev/environment: "barstoolbluz/amazon-reinvent-2025-demo-runtime-test:1"
spec:
  runtimeClassName: flox
  containers:
  - name: test
    image: flox/empty:1.0.0
    env:
    - name: PYTHONPATH
      value: "/.flox/run/x86_64-linux.amazon-reinvent-2025-demo-runtime-test.run/lib/python3.13/site-packages:/.flox/cache/python/lib/python3.13/site-packages"
    command:
      - sh
      - -c
      - |
        echo "=== Environment Check ==="
        echo "Python: \$(which python3)"
        echo "Python version: \$(python3 --version)"
        echo "PYTHONPATH: \${PYTHONPATH:-<not set>}"
        echo ""
        echo "=== sys.path Check ==="
        python3 -c "import sys; print('\n'.join(sys.path))"
        echo ""
        echo "=== Package Import Test ==="
        python3 -c "
        import sys
        print(f'Python {sys.version}')
        print('')

        # Try to import packages from custom Flox packages
        try:
            import torch
            print(f'✅ PyTorch {torch.__version__}')
        except ImportError as e:
            print(f'❌ PyTorch import failed: {e}')

        try:
            from transformers import pipeline
            print('✅ Transformers imported')
        except ImportError as e:
            print(f'❌ Transformers import failed: {e}')

        try:
            import boto3
            print(f'✅ Boto3 {boto3.__version__}')
        except ImportError as e:
            print(f'❌ Boto3 import failed: {e}')

        print('')
        print('Environment test completed!')
        "

        # Sleep to keep pod running for inspection
        sleep 120
EOF

  log_info "Test pod created"
  echo "⏳ Waiting for pod to start (max 5 minutes - first run downloads packages)..."

  if kubectl wait --for=condition=Ready pod/test-flox-pod -n reinvent-demo --timeout=300s 2>/dev/null; then
    log_info "Pod is ready!"
  else
    log_warn "Pod didn't become ready in time, checking status..."
  fi

  echo ""
  echo "Pod status:"
  kubectl get pod test-flox-pod -n reinvent-demo

  echo ""
  echo "Pod events:"
  kubectl describe pod test-flox-pod -n reinvent-demo | tail -20

  echo ""
  echo "Pod logs:"
  kubectl logs test-flox-pod -n reinvent-demo 2>/dev/null || log_warn "Logs not available yet"

  echo ""
  read -p "Delete test pod? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    kubectl delete pod test-flox-pod -n reinvent-demo
    log_info "Test pod deleted"
  fi
else
  log_warn "Skipping test pod"
fi
echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo "===================================================================="
echo "SETUP COMPLETE!"
echo "===================================================================="
echo ""
echo "📋 Configuration Summary:"
echo "   Cluster: $CLUSTER_NAME"
echo "   Region: $AWS_REGION"
echo "   Account: $AWS_ACCOUNT_ID"
echo "   Role ARN: ${ROLE_ARN:-NOT SET}"
echo ""
echo "🔐 GitHub Secrets to Configure:"
echo "   Go to: https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/secrets/actions"
echo ""
echo "   Add these SECRETS:"
echo "   - AWS_ROLE_ARN = ${ROLE_ARN:-NOT SET}"
echo ""
echo "   Add these VARIABLES:"
echo "   - EKS_CLUSTER_NAME = $CLUSTER_NAME"
echo "   - AWS_REGION = $AWS_REGION"
echo "   - FLOX_HUB_ORG = $FLOX_HUB_ORG"
echo ""
echo "📝 Next Steps:"
echo "   1. Configure GitHub secrets/variables (see above)"
echo "   2. Create Kubernetes deployment manifests in your repo (k8s/ directory)"
echo "   3. Create GitHub Actions workflow (.github/workflows/deploy-eks.yml)"
echo "   4. Push to GitHub and watch the deployment!"
echo ""
echo "💾 Configuration saved to: /tmp/eks-setup-config.env"
echo "   Reload with: source /tmp/eks-setup-config.env"
echo ""
echo "🧹 Cleanup commands (when you're done testing):"
echo "   eksctl delete cluster --name $CLUSTER_NAME --region $AWS_REGION"
echo ""

# Clean up temporary files
rm -f /tmp/github-actions-trust-policy.json
rm -f /tmp/github-actions-eks-policy.json
log_info "Temporary files cleaned up"
echo ""
