# EKS Setup Script Review - Issues Found & Fixed

## Issues in Original Script (`EKS_SETUP_COMMANDS.sh`)

### 1. **SSM Command JSON Escaping** ❌
**Problem:** Line 112-116 - The `--parameters` argument used improperly escaped JSON array
```bash
--parameters 'commands=[
  "curl -fsSL https://downloads.flox.dev/install | bash",
  "/root/.flox/bin/flox activate -r flox/containerd-shim-flox-installer --trust",
  "systemctl restart containerd"
]'
```
This would fail because:
- Multiline string in single quotes breaks the command
- No proper JSON encoding of the script

**Fix:** Created a proper installation script, saved to file, then use `jq` to encode:
```bash
cat > /tmp/install-flox.sh <<'FLOXEOF'
#!/bin/bash
# Script content here
FLOXEOF

aws ssm send-command \
  --parameters "commands=$(cat /tmp/install-flox.sh | jq -Rs .)"
```

### 2. **Hardcoded Flox Path** ❌
**Problem:** Assumed `/root/.flox/bin/flox` but Flox can install to different locations
```bash
"/root/.flox/bin/flox activate ..."
```

**Fix:** Added dynamic path detection:
```bash
if [[ -x /root/.flox/bin/flox ]]; then
  FLOX_BIN="/root/.flox/bin/flox"
elif [[ -x /home/ec2-user/.flox/bin/flox ]]; then
  FLOX_BIN="/home/ec2-user/.flox/bin/flox"
elif command -v flox >/dev/null 2>&1; then
  FLOX_BIN="flox"
else
  echo "ERROR: Flox binary not found"
  exit 1
fi
```

### 3. **Missing Validation** ❌
**Problem:** No checks for:
- Empty `$INSTANCE_IDS` before SSM commands
- Successful shim installation
- Required variables being set

**Fix:** Added validation throughout:
```bash
if [[ -z "$INSTANCE_IDS" ]]; then
  log_error "No instances found"
  exit 1
fi

if [[ ! -f /opt/flox/bin/containerd-shim-flox-v1 ]]; then
  echo "ERROR: Shim not installed"
  exit 1
fi
```

### 4. **OIDC Provider Handling** ❌
**Problem:** If user skipped OIDC creation, `$OIDC_PROVIDER_ARN` was unset for role creation

**Fix:** Added fallback to check for existing provider:
```bash
if [[ -z "$OIDC_PROVIDER_ARN" ]]; then
  export OIDC_PROVIDER_ARN=$(aws iam list-open-id-connect-providers ...)
  if [[ -z "$OIDC_PROVIDER_ARN" ]]; then
    log_error "No OIDC provider found. Cannot continue."
    exit 1
  fi
fi
```

### 5. **No Error Verification** ❌
**Problem:** No verification that containerd config actually contains Flox runtime

**Fix:** Added verification step:
```bash
if ! grep -q "flox" /etc/containerd/config.toml; then
  echo "WARNING: Flox runtime not in containerd config"
  exit 1
fi
```

### 6. **SSM Output Too Verbose** ❌
**Problem:** Would dump entire SSM output, hard to read

**Fix:** Limited output and improved formatting:
```bash
# Check each instance individually
for INSTANCE_ID in $INSTANCE_IDS; do
  echo "Status for $INSTANCE_ID:"
  aws ssm list-command-invocations \
    --instance-id "$INSTANCE_ID" \
    --query "CommandInvocations[0].[Status,CommandPlugins[0].Output]" \
    --output text | head -20
done
```

### 7. **Missing Cluster Existence Check** ❌
**Problem:** Would fail if cluster already exists

**Fix:** Added check:
```bash
if aws eks describe-cluster --name "$CLUSTER_NAME" >/dev/null 2>&1; then
  log_warn "Cluster already exists, skipping"
fi
```

### 8. **IAM Policy Scope** ❌
**Problem:** `list-policies` without `--scope Local` would search all AWS-managed policies too

**Fix:**
```bash
POLICY_ARN=$(aws iam list-policies \
  --scope Local \  # Only search customer-managed policies
  --query "Policies[?PolicyName=='GitHubActionsEKSPolicy'].Arn" \
  --output text)
```

### 9. **No Color Output** ❌
**Problem:** Hard to distinguish success/warning/error messages

**Fix:** Added color helpers:
```bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
```

### 10. **Test Pod Not Cleaned Up** ❌
**Problem:** If test pod from previous run existed, would fail

**Fix:** Delete before creating:
```bash
kubectl delete pod test-flox-pod -n reinvent-demo --ignore-not-found=true
```

### 11. **Missing IAM Role Update** ❌
**Problem:** If role exists but trust policy changed (different repo), no update

**Fix:** Update trust policy if role exists:
```bash
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  log_info "Role exists, updating trust policy..."
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document file:///tmp/github-actions-trust-policy.json
fi
```

## New Features Added ✅

1. **Environment variable defaults** - Can preset values or use defaults
2. **Better error messages** - Clear colored output
3. **Idempotency** - Can run multiple times safely
4. **Individual instance checking** - See status per node
5. **Comprehensive verification** - Checks shim, containerd config, etc.
6. **Cleanup instructions** - Shows how to delete cluster when done
7. **Improved wait times** - 90s instead of 60s for Flox installation

## Usage

```bash
# From xplatform-cli-tools environment:
cd /home/daedalus/dev/demo-reinvent-2025/xplatform-cli-tools
flox activate

# Run the fixed script:
bash /home/daedalus/dev/demo-reinvent-2025/docs/EKS_SETUP_COMMANDS_FIXED.sh
```

## Cost Estimate

**While running:**
- EKS control plane: $0.10/hour
- 2x t3.medium nodes: ~$0.0832/hour
- **Total: ~$0.18/hour (~$4.30/day)**

**After testing, delete with:**
```bash
eksctl delete cluster --name reinvent-demo-test --region us-east-1
```
