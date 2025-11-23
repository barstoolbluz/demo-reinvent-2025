# EKS Setup for GitHub Actions CI with Flox Imageless Deployments

**Purpose**: Complete setup guide for enabling GitHub Actions to deploy Flox environments to EKS without Docker images.

**Target**: Claude session with AWS CLI + 1Password access

**Project**: AWS re:Invent 2025 Demo - ML Ticket Processing

---

## Prerequisites

- AWS CLI configured with appropriate credentials
- Access to 1Password for storing secrets
- GitHub repository: (provide repo URL)
- AWS Account ID: (provide account ID)
- Desired AWS Region: (default: us-east-1)

---

## Overview

This setup enables:
1. GitHub Actions to deploy to EKS using OIDC (no long-lived credentials)
2. EKS nodes to run Flox imageless containers
3. Automatic deployment of `ticket-processor` and `ticket-generator` services

---

## Step 1: Create EKS Cluster

### 1.1 Cluster Configuration

**Cluster Name**: `reinvent-demo-cluster` (or choose your own)
**Region**: `us-east-1` (or choose your own)
**Kubernetes Version**: 1.28 or later
**Node Group**: t3.xlarge or larger (ML workload requires 4+ vCPUs, 16GB+ RAM)

### 1.2 Create Cluster

```bash
# Set variables
export CLUSTER_NAME="reinvent-demo-cluster"
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create cluster (using eksctl - install if needed)
eksctl create cluster \
  --name $CLUSTER_NAME \
  --region $AWS_REGION \
  --version 1.28 \
  --nodegroup-name standard-workers \
  --node-type t3.xlarge \
  --nodes 3 \
  --nodes-min 2 \
  --nodes-max 5 \
  --managed
```

**Expected duration**: 15-20 minutes

### 1.3 Verify Cluster

```bash
# Update kubeconfig
aws eks update-kubeconfig --name $CLUSTER_NAME --region $AWS_REGION

# Verify nodes
kubectl get nodes

# Should show 3 nodes in Ready state
```

---

## Step 2: Install Flox Shim on EKS Nodes

### 2.1 Install Flox on Nodes

**Recommended Method**: Include Flox installation in node bootstrap (user data script)

**Option A: User Data Script** (Best for production)

When creating the node group, include this in user data:
```bash
#!/bin/bash
# Install Flox
curl -fsSL https://downloads.flox.dev/install | bash

# Install containerd shim
/root/.flox/bin/flox activate -r flox/containerd-shim-flox-installer --trust

# Restart containerd
systemctl restart containerd
```

**Option B: eksctl with Launch Template**

Create launch template with user data, then reference in eksctl config.

**Option C: SSM Run Command** (For existing nodes)

```bash
# Get node instance IDs
INSTANCE_IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:eks:cluster-name,Values=$CLUSTER_NAME" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" \
  --output text)

# Run installation via SSM
aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids $INSTANCE_IDS \
  --parameters 'commands=["curl -fsSL https://downloads.flox.dev/install | bash","/root/.flox/bin/flox activate -r flox/containerd-shim-flox-installer --trust","systemctl restart containerd"]' \
  --region $AWS_REGION

# Check command status
COMMAND_ID=$(aws ssm list-commands --region $AWS_REGION --max-items 1 --query "Commands[0].CommandId" --output text)
aws ssm list-command-invocations --command-id $COMMAND_ID --region $AWS_REGION --details
```

**Option D: Manual SSH** (For testing/development)

For each node:
```bash
# Get node external IPs
kubectl get nodes -o wide

# SSH to each node (using session manager or SSH key)
aws ssm start-session --target <instance-id>

# On each node:
curl -fsSL https://downloads.flox.dev/install | bash
sudo /root/.flox/bin/flox activate -r flox/containerd-shim-flox-installer --trust
sudo systemctl restart containerd
```

### 2.2 Verify Shim Installation

On each node:
```bash
# Check shim binary exists
ls -la /opt/flox/bin/containerd-shim-flox-v1

# Should show executable file
```

### 2.3 Label Nodes

```bash
# Label all nodes as flox-enabled
kubectl label nodes --all flox-runtime=enabled

# Verify
kubectl get nodes --show-labels | grep flox-runtime
```

---

## Step 3: Create RuntimeClass

```bash
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
```

**Verify**:
```bash
kubectl get runtimeclass
# Should show 'flox'
```

---

## Step 4: Setup GitHub OIDC Provider

### 4.1 Create OIDC Provider for GitHub Actions

```bash
# Get OIDC provider URL
OIDC_PROVIDER="token.actions.githubusercontent.com"

# Create OIDC provider
# Note: Thumbprint is current as of 2024. Verify at:
# https://github.blog/changelog/2023-06-27-github-actions-update-on-oidc-integration-with-aws/
aws iam create-open-id-connect-provider \
  --url "https://${OIDC_PROVIDER}" \
  --client-id-list "sts.amazonaws.com" \
  --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1" \
  --region $AWS_REGION
```

**Get provider ARN**:
```bash
export OIDC_PROVIDER_ARN=$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" \
  --output text)

echo "OIDC Provider ARN: $OIDC_PROVIDER_ARN"
```

**Save to 1Password**:
```bash
# Store for later use
op item create \
  --category=server \
  --title="GitHub Actions OIDC Provider" \
  --vault="AWS" \
  "oidc_provider_arn=$OIDC_PROVIDER_ARN"
```

---

## Step 5: Create IAM Role for GitHub Actions

### 5.1 Create Trust Policy

**Set GitHub repository** (replace with your repo):
```bash
export GITHUB_ORG="your-github-org"
export GITHUB_REPO="demo-reinvent-2025"
```

**Create trust policy**:
```bash
cat > github-actions-trust-policy.json <<EOF
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
```

### 5.2 Create IAM Role

```bash
export ROLE_NAME="GitHubActionsEKSDeployRole"

aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document file://github-actions-trust-policy.json \
  --description "Role for GitHub Actions to deploy to EKS"

# Get role ARN
export ROLE_ARN=$(aws iam get-role \
  --role-name $ROLE_NAME \
  --query 'Role.Arn' \
  --output text)

echo "Role ARN: $ROLE_ARN"
```

**Save to 1Password**:
```bash
op item create \
  --category=server \
  --title="GitHub Actions EKS Role" \
  --vault="AWS" \
  "role_arn=$ROLE_ARN" \
  "role_name=$ROLE_NAME"
```

### 5.3 Attach Policies to Role

**Create custom policy for EKS access**:
```bash
cat > github-actions-eks-policy.json <<EOF
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

# Create policy
aws iam create-policy \
  --policy-name GitHubActionsEKSPolicy \
  --policy-document file://github-actions-eks-policy.json

# Attach to role
export POLICY_ARN=$(aws iam list-policies \
  --query "Policies[?PolicyName=='GitHubActionsEKSPolicy'].Arn" \
  --output text)

aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn $POLICY_ARN
```

**Note**: The custom EKS policy above is required for `aws eks update-kubeconfig` to work. Once kubeconfig is configured, actual Kubernetes permissions come from the ClusterRoleBinding, not AWS IAM.

---

## Step 6: Configure EKS RBAC for GitHub Actions Role

### 6.1 Create Kubernetes ServiceAccount

```bash
kubectl create namespace github-actions

kubectl create serviceaccount github-actions-deployer -n github-actions
```

### 6.2 Create ClusterRole with Deployment Permissions

```bash
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
```

### 6.3 Create ClusterRoleBinding

```bash
kubectl create clusterrolebinding github-actions-deployer \
  --clusterrole=github-actions-deployer \
  --serviceaccount=github-actions:github-actions-deployer
```

### 6.4 Map IAM Role to Kubernetes RBAC

**Edit aws-auth ConfigMap**:
```bash
kubectl edit configmap aws-auth -n kube-system
```

**Add this under `mapRoles`** (replace with your role ARN):
```yaml
mapRoles: |
  - rolearn: arn:aws:iam::ACCOUNT_ID:role/GitHubActionsEKSDeployRole
    username: github-actions:github-actions-deployer
```

**Note**: No groups specified - permissions come from ClusterRoleBinding created in Step 6.3.

**Alternative: Use eksctl** (simpler):
```bash
eksctl create iamidentitymapping \
  --cluster $CLUSTER_NAME \
  --region $AWS_REGION \
  --arn $ROLE_ARN \
  --username github-actions:github-actions-deployer

# Verify
eksctl get iamidentitymapping --cluster $CLUSTER_NAME --region $AWS_REGION
```

---

## Step 7: Create Kubernetes Resources

### 7.1 Create Namespace

```bash
kubectl create namespace reinvent-demo
```

### 7.2 Create PersistentVolumeClaim for ML Models

```bash
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
  # storageClassName: gp3  # Uncomment if gp3 StorageClass exists, otherwise uses default
EOF
```

### 7.3 Create ConfigMap for AWS Configuration

**Option A: Using Real AWS Services** (Production)
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-config
  namespace: reinvent-demo
data:
  region: "us-east-1"
  # No endpoint-url needed - uses real AWS
EOF
```

**Option B: Using LocalStack** (Testing/Demo)

If you've deployed LocalStack to the cluster, configure the endpoint:
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-config
  namespace: reinvent-demo
data:
  endpoint-url: "http://localstack.default.svc.cluster.local:4566"
  region: "us-east-1"
EOF
```

**Note**: This guide does not cover deploying LocalStack to EKS. For production, use real AWS services (Option A). For local testing, use the runtime environment from FloxHub which includes LocalStack.

---

## Step 8: Configure GitHub Repository

### 8.1 Required Secrets

Go to GitHub repository → Settings → Secrets and variables → Actions

**Create these secrets**:

| Name | Value | Source |
|------|-------|--------|
| `AWS_ROLE_ARN` | `arn:aws:iam::ACCOUNT:role/GitHubActionsEKSDeployRole` | From Step 5.2 |

**Create these variables**:

| Name | Value |
|------|-------|
| `EKS_CLUSTER_NAME` | `reinvent-demo-cluster` |
| `AWS_REGION` | `us-east-1` |
| `FLOX_HUB_ORG` | `barstoolbluz` |

### 8.2 Optional: FloxHub Token

If using private FloxHub environments:

```bash
# Create FloxHub token
flox auth login
# ... follow prompts ...

# Store in 1Password
op item create \
  --category=password \
  --title="FloxHub Token" \
  --vault="Tokens" \
  "token=<your-token-here>"
```

Add to GitHub Secrets:
- Name: `FLOX_HUB_TOKEN`
- Value: (token from above)

---

## Step 9: Test Setup

### 9.1 Verify OIDC Provider Setup

**Verify OIDC provider exists**:
```bash
aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')]"

# Should return the provider ARN
```

**Verify trust relationship**:
```bash
aws iam get-role \
  --role-name $ROLE_NAME \
  --query 'Role.AssumeRolePolicyDocument'

# Should show trust policy with GitHub OIDC
```

**Note**: OIDC authentication can only be fully tested within GitHub Actions workflow, not locally.

### 9.2 Test kubectl Access (Using Your Current Credentials)

**Test with your current AWS credentials** (not the GitHub Actions role):
```bash
# Update kubeconfig (using your current credentials, not the GitHub role)
aws eks update-kubeconfig --name $CLUSTER_NAME --region $AWS_REGION

# Verify you can access the cluster
kubectl get nodes

# Verify RuntimeClass exists
kubectl get runtimeclass

# Verify namespace exists
kubectl get namespace reinvent-demo

# Verify RBAC is configured
kubectl get clusterrole github-actions-deployer
kubectl get clusterrolebinding github-actions-deployer
```

**Note**: You cannot test the GitHub Actions role locally because it requires OIDC web identity authentication (only available in GitHub Actions). The role will be tested when you run the actual GitHub Actions workflow.

### 9.3 Test Flox Pod

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-flox-pod
  namespace: reinvent-demo
  annotations:
    flox.dev/environment: "barstoolbluz/reinvent-demo-ticket-processor"
spec:
  runtimeClassName: flox
  containers:
  - name: test
    image: flox/empty:1.0.0
    command: ["sh", "-c", "echo 'Flox pod works!'; sleep 30"]
EOF

# Watch pod start
kubectl get pod test-flox-pod -n reinvent-demo -w

# Should go to Running state
# Check logs
kubectl logs test-flox-pod -n reinvent-demo

# Clean up
kubectl delete pod test-flox-pod -n reinvent-demo
```

---

## Step 10: Save Configuration Summary

### 10.1 Store All Details in 1Password

```bash
# Create comprehensive setup record
op item create \
  --category=server \
  --title="EKS Flox CI Setup" \
  --vault="AWS" \
  "cluster_name=$CLUSTER_NAME" \
  "aws_region=$AWS_REGION" \
  "aws_account_id=$AWS_ACCOUNT_ID" \
  "role_arn=$ROLE_ARN" \
  "role_name=$ROLE_NAME" \
  "oidc_provider_arn=$OIDC_PROVIDER_ARN" \
  "github_org=$GITHUB_ORG" \
  "github_repo=$GITHUB_REPO"
```

### 10.2 Export Configuration File

```bash
cat > eks-setup-config.env <<EOF
# EKS Cluster Configuration
export CLUSTER_NAME="$CLUSTER_NAME"
export AWS_REGION="$AWS_REGION"
export AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"

# GitHub Actions OIDC
export ROLE_ARN="$ROLE_ARN"
export ROLE_NAME="$ROLE_NAME"
export OIDC_PROVIDER_ARN="$OIDC_PROVIDER_ARN"

# GitHub Repository
export GITHUB_ORG="$GITHUB_ORG"
export GITHUB_REPO="$GITHUB_REPO"

# FloxHub
export FLOX_HUB_ORG="barstoolbluz"
EOF

echo "Configuration saved to: eks-setup-config.env"
```

---

## Step 11: Create GitHub Actions Workflow File

### 11.1 Create Kubernetes Deployment Manifests

First, create deployment manifests for your services. Example structure:

**`k8s/ticket-processor-deployment.yaml`**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor
  namespace: reinvent-demo
  annotations:
    flox.dev/environment: "barstoolbluz/reinvent-demo-ticket-processor"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ticket-processor
  template:
    metadata:
      labels:
        app: ticket-processor
      annotations:
        flox.dev/environment: "barstoolbluz/reinvent-demo-ticket-processor"
    spec:
      runtimeClassName: flox
      containers:
      - name: processor
        image: flox/empty:1.0.0
        command: ["ticket-processor"]
        env:
        - name: AWS_REGION
          valueFrom:
            configMapKeyRef:
              name: aws-config
              key: region
        - name: AWS_ENDPOINT_URL
          valueFrom:
            configMapKeyRef:
              name: aws-config
              key: endpoint-url
              optional: true
        - name: FLOX_ENV_CACHE
          value: "/var/flox/cache"
        - name: MODEL_CACHE_DIR
          value: "/var/flox/cache/models"
        - name: TRANSFORMERS_CACHE
          value: "/var/flox/cache/models/transformers"
        - name: HF_HOME
          value: "/var/flox/cache/models/huggingface"
        volumeMounts:
        - name: models-cache
          mountPath: /var/flox/cache
      volumes:
      - name: models-cache
        persistentVolumeClaim:
          claimName: ml-models-cache
```

**`k8s/ticket-generator-deployment.yaml`**: Similar structure, but:
- Replace `ticket-processor` with `ticket-generator`
- Change annotation to `flox.dev/environment: "barstoolbluz/reinvent-demo-ticket-generator"`
- Remove model cache volume mounts (generator doesn't need ML models)
- Keep AWS configuration environment variables

**Important Notes**:
- The `flox.dev/environment` annotation must be on BOTH the Deployment and the Pod template
- The `runtimeClassName: flox` tells Kubernetes to use the Flox containerd shim
- The `image: flox/empty:1.0.0` is a 49-byte stub - the real environment comes from FloxHub
- Environment variables override those in the FloxHub environment manifest

### 11.2 Create GitHub Actions Workflow

Once setup is complete, create `.github/workflows/deploy-eks.yml` in the repository:

```yaml
name: Deploy to EKS

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      - name: Configure kubectl
        run: |
          aws eks update-kubeconfig \
            --name ${{ vars.EKS_CLUSTER_NAME }} \
            --region ${{ vars.AWS_REGION }}

      - name: Deploy ticket-processor
        run: |
          kubectl apply -f k8s/ticket-processor-deployment.yaml

      - name: Deploy ticket-generator
        run: |
          kubectl apply -f k8s/ticket-generator-deployment.yaml

      - name: Wait for rollout
        run: |
          kubectl rollout status deployment/ticket-processor -n reinvent-demo --timeout=5m
          kubectl rollout status deployment/ticket-generator -n reinvent-demo --timeout=5m
```

**Notes**:
- The `id-token: write` permission is required for OIDC authentication
- Flox CLI is not needed in the workflow since deployments pull environments from FloxHub at runtime
- If using private FloxHub environments, the Flox shim on nodes handles authentication (configure via node environment)
- Adjust branch name from `main` if your default branch differs

---

## Troubleshooting

### OIDC Provider Issues

**Error**: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

**Fix**: Verify trust policy includes correct GitHub repo:
```bash
aws iam get-role --role-name $ROLE_NAME --query 'Role.AssumeRolePolicyDocument'
```

### Flox Shim Not Working

**Error**: Pods stuck in ContainerCreating

**Check**:
```bash
# On node
ls -la /opt/flox/bin/containerd-shim-flox-v1

# Check containerd config
cat /etc/containerd/config.toml | grep flox

# Restart containerd
sudo systemctl restart containerd
```

### RBAC Permission Denied

**Error**: "User cannot create resources"

**Fix**: Verify aws-auth ConfigMap:
```bash
kubectl get configmap aws-auth -n kube-system -o yaml
```

---

## Next Steps

After completing this setup:

1. Push GitHub Actions workflow to repository
2. Trigger workflow (push to main or manual dispatch)
3. Verify deployments in EKS cluster
4. Monitor pod logs for successful startup

---

## Reference Links

- **Flox Documentation**: https://flox.dev/docs
- **EKS OIDC Guide**: https://docs.aws.amazon.com/eks/latest/userguide/enable-iam-roles-for-service-accounts.html
- **GitHub Actions OIDC**: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services

---

**Document Version**: 1.0
**Last Updated**: 2025-11-22
**Target Cluster**: EKS with Flox imageless deployments
**CI Platform**: GitHub Actions with OIDC
