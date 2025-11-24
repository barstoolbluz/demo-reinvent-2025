#!/usr/bin/env bash
# EKS Setup Script - Step-by-step commands for re:Invent 2025 Demo
# Run these commands from the xplatform-cli-tools Flox environment
# Usage: flox activate -d /path/to/xplatform-cli-tools

set -euo pipefail

# ============================================================================
# STEP 1: Set Environment Variables
# ============================================================================
echo "===================================================================="
echo "STEP 1: Setting up environment variables"
echo "===================================================================="

# Cluster configuration
export CLUSTER_NAME="reinvent-demo-test"
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# GitHub repository (CHANGE THIS to your actual repo)
export GITHUB_ORG="barstoolbluz"  # Change to your GitHub username/org
export GITHUB_REPO="amazon-reinvent-2025-demo-runtime-test"  # Your repo name

# FloxHub organization
export FLOX_HUB_ORG="flox"  # Change if using different org

echo "✅ Configuration:"
echo "   Cluster: $CLUSTER_NAME"
echo "   Region: $AWS_REGION"
echo "   Account: $AWS_ACCOUNT_ID"
echo "   GitHub: $GITHUB_ORG/$GITHUB_REPO"
echo ""

# Save config for later use
cat > /tmp/eks-setup-config.env <<EOF
export CLUSTER_NAME="$CLUSTER_NAME"
export AWS_REGION="$AWS_REGION"
export AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"
export GITHUB_ORG="$GITHUB_ORG"
export GITHUB_REPO="$GITHUB_REPO"
export FLOX_HUB_ORG="$FLOX_HUB_ORG"
EOF

echo "✅ Config saved to /tmp/eks-setup-config.env"
echo "   You can reload with: source /tmp/eks-setup-config.env"
echo ""

# ============================================================================
# STEP 2: Create EKS Cluster
# ============================================================================
echo "===================================================================="
echo "STEP 2: Creating EKS cluster (this takes ~15-20 minutes)"
echo "===================================================================="

read -p "Create EKS cluster now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  eksctl create cluster \
    --name "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --version 1.28 \
    --nodegroup-name standard-workers \
    --node-type t3.medium \
    --nodes 2 \
    --nodes-min 1 \
    --nodes-max 3 \
    --managed \
    --with-oidc

  echo "✅ Cluster created!"
else
  echo "⏭️  Skipping cluster creation"
fi
echo ""

# ============================================================================
# STEP 3: Update kubeconfig
# ============================================================================
echo "===================================================================="
echo "STEP 3: Configuring kubectl"
echo "===================================================================="

aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

echo "✅ kubectl configured"
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
  --output text)

echo "Found instances: $INSTANCE_IDS"

read -p "Install Flox on nodes via SSM? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Run installation command
  COMMAND_ID=$(aws ssm send-command \
    --document-name "AWS-RunShellScript" \
    --instance-ids $INSTANCE_IDS \
    --parameters 'commands=[
      "curl -fsSL https://downloads.flox.dev/install | bash",
      "/root/.flox/bin/flox activate -r flox/containerd-shim-flox-installer --trust",
      "systemctl restart containerd"
    ]' \
    --region "$AWS_REGION" \
    --query "Command.CommandId" \
    --output text)

  echo "✅ Installation command sent: $COMMAND_ID"
  echo "⏳ Waiting 60 seconds for installation to complete..."
  sleep 60

  # Check status
  aws ssm list-command-invocations \
    --command-id "$COMMAND_ID" \
    --region "$AWS_REGION" \
    --details \
    --query "CommandInvocations[*].[InstanceId,Status,CommandPlugins[0].Output]" \
    --output table
else
  echo "⏭️  Skipping Flox installation"
fi
echo ""

# ============================================================================
# STEP 5: Label Nodes and Create RuntimeClass
# ============================================================================
echo "===================================================================="
echo "STEP 5: Labeling nodes and creating RuntimeClass"
echo "===================================================================="

# Label all nodes
kubectl label nodes --all flox-runtime=enabled --overwrite
echo "✅ Nodes labeled"

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

echo "✅ RuntimeClass created"
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
  if aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" --output text | grep -q .; then
    echo "✅ OIDC provider already exists"
  else
    aws iam create-open-id-connect-provider \
      --url "https://token.actions.githubusercontent.com" \
      --client-id-list "sts.amazonaws.com" \
      --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1"
    echo "✅ OIDC provider created"
  fi

  export OIDC_PROVIDER_ARN=$(aws iam list-open-id-connect-providers \
    --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" \
    --output text)

  echo "OIDC Provider ARN: $OIDC_PROVIDER_ARN"

  # Append to config file
  echo "export OIDC_PROVIDER_ARN=\"$OIDC_PROVIDER_ARN\"" >> /tmp/eks-setup-config.env
else
  echo "⏭️  Skipping OIDC provider creation"
fi
echo ""

# ============================================================================
# STEP 7: Create IAM Role for GitHub Actions
# ============================================================================
echo "===================================================================="
echo "STEP 7: Creating IAM role for GitHub Actions"
echo "===================================================================="

export ROLE_NAME="GitHubActionsEKSDeployRole"

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

read -p "Create IAM role? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Check if role exists
  if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "✅ Role already exists"
  else
    aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document file:///tmp/github-actions-trust-policy.json \
      --description "Role for GitHub Actions to deploy to EKS"
    echo "✅ Role created"
  fi

  export ROLE_ARN=$(aws iam get-role \
    --role-name "$ROLE_NAME" \
    --query 'Role.Arn' \
    --output text)

  echo "Role ARN: $ROLE_ARN"
  echo "export ROLE_ARN=\"$ROLE_ARN\"" >> /tmp/eks-setup-config.env

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
  POLICY_ARN=$(aws iam list-policies --query "Policies[?PolicyName=='GitHubActionsEKSPolicy'].Arn" --output text)

  if [[ -z "$POLICY_ARN" ]]; then
    POLICY_ARN=$(aws iam create-policy \
      --policy-name GitHubActionsEKSPolicy \
      --policy-document file:///tmp/github-actions-eks-policy.json \
      --query 'Policy.Arn' \
      --output text)
    echo "✅ Policy created"
  else
    echo "✅ Policy already exists"
  fi

  # Attach policy to role
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "$POLICY_ARN" 2>/dev/null || echo "✅ Policy already attached"
else
  echo "⏭️  Skipping IAM role creation"
fi
echo ""

# ============================================================================
# STEP 8: Configure EKS RBAC
# ============================================================================
echo "===================================================================="
echo "STEP 8: Configuring Kubernetes RBAC for GitHub Actions"
echo "===================================================================="

# Create namespace
kubectl create namespace github-actions --dry-run=client -o yaml | kubectl apply -f -

# Create service account
kubectl create serviceaccount github-actions-deployer -n github-actions --dry-run=client -o yaml | kubectl apply -f -

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
EOF

# Create ClusterRoleBinding
kubectl create clusterrolebinding github-actions-deployer \
  --clusterrole=github-actions-deployer \
  --serviceaccount=github-actions:github-actions-deployer \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ RBAC configured"

# Map IAM role to Kubernetes
read -p "Map IAM role to Kubernetes RBAC? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  eksctl create iamidentitymapping \
    --cluster "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --arn "$ROLE_ARN" \
    --username github-actions:github-actions-deployer

  echo "✅ IAM identity mapping created"

  # Verify
  eksctl get iamidentitymapping --cluster "$CLUSTER_NAME" --region "$AWS_REGION"
else
  echo "⏭️  Skipping IAM identity mapping"
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
echo "✅ Namespace created"

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

echo "✅ PVC created"

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

echo "✅ ConfigMap created"
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
  kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-flox-pod
  namespace: reinvent-demo
  annotations:
    flox.dev/environment: "$FLOX_HUB_ORG/reinvent-demo-ticket-processor"
spec:
  runtimeClassName: flox
  containers:
  - name: test
    image: flox/empty:1.0.0
    command: ["sh", "-c", "echo 'Flox pod works! Environment loaded successfully.'; sleep 30"]
EOF

  echo "⏳ Waiting for pod to start..."
  kubectl wait --for=condition=Ready pod/test-flox-pod -n reinvent-demo --timeout=120s || true

  echo ""
  echo "Pod status:"
  kubectl get pod test-flox-pod -n reinvent-demo

  echo ""
  echo "Pod logs:"
  kubectl logs test-flox-pod -n reinvent-demo || echo "Pod not ready yet"

  echo ""
  read -p "Delete test pod? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    kubectl delete pod test-flox-pod -n reinvent-demo
    echo "✅ Test pod deleted"
  fi
else
  echo "⏭️  Skipping test pod"
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
echo "   Role ARN: $ROLE_ARN"
echo ""
echo "🔐 GitHub Secrets to Configure:"
echo "   Go to: https://github.com/$GITHUB_ORG/$GITHUB_REPO/settings/secrets/actions"
echo ""
echo "   Add these secrets:"
echo "   - AWS_ROLE_ARN = $ROLE_ARN"
echo ""
echo "   Add these variables:"
echo "   - EKS_CLUSTER_NAME = $CLUSTER_NAME"
echo "   - AWS_REGION = $AWS_REGION"
echo "   - FLOX_HUB_ORG = $FLOX_HUB_ORG"
echo ""
echo "📝 Next Steps:"
echo "   1. Create Kubernetes deployment manifests in your repo (k8s/ directory)"
echo "   2. Create GitHub Actions workflow (.github/workflows/deploy-eks.yml)"
echo "   3. Push to GitHub and watch the deployment!"
echo ""
echo "💾 Configuration saved to: /tmp/eks-setup-config.env"
echo "   Reload with: source /tmp/eks-setup-config.env"
echo ""
