# Imageless Kubernetes Deployment Guide

This guide explains how to deploy the `ticket-processor` to Kubernetes without building container images, using Flox's containerd shim.

---

## Overview

Traditional Kubernetes deployment requires:
1. Building Docker/OCI images
2. Pushing to container registry
3. Pulling images on each node
4. Managing image versions

**Flox imageless deployment** eliminates this by:
- Using Flox environments directly as runtime
- No image builds or registry required
- Instant updates (just change manifest)
- Guaranteed consistency (Nix derivations)

---

## Architecture

### Traditional vs. Imageless

**Traditional**:
```
Code → Dockerfile → Docker Build → Registry → K8s Pull → Run
```

**Imageless with Flox**:
```
Code → Flox Package → Catalog → K8s RuntimeClass → Run
```

### How It Works

1. **Containerd Shim**: Flox provides a containerd runtime class
2. **Flox Runtime**: Nodes install Flox runtime
3. **Environment Activation**: Pods activate Flox environments
4. **Nix Store**: Shared /nix/store across pods (read-only)

---

## Prerequisites

### Kubernetes Cluster Requirements

- **Kubernetes**: 1.25+ (RuntimeClass support)
- **Containerd**: 1.6+ (runtime shim support)
- **Node OS**: Linux (x86_64 or ARM64)
- **Storage**: Shared /nix/store (recommended: NFS or distributed FS)

### Flox Setup

1. **Flox Catalog**: Package published (`ticket-processor`)
2. **Node Runtime**: Flox installed on all nodes
3. **RuntimeClass**: `flox` runtime class configured

---

## Node Setup

### 1. Install Flox on Nodes

On each Kubernetes node:

```bash
# Install Flox
curl -fsSL https://get.flox.dev | sh

# Verify installation
flox --version
```

### 2. Configure Shared Nix Store (Recommended)

For efficiency, share `/nix/store` across nodes:

**Option A: NFS Mount**

```bash
# On NFS server
sudo mkdir -p /export/nix
sudo chmod 755 /export/nix
echo "/export/nix *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
sudo exportfs -ra

# On each node
sudo mkdir -p /nix
sudo mount -t nfs nfs-server:/export/nix /nix
```

**Option B: Distributed Storage**

Use Ceph, GlusterFS, or cloud provider storage (EBS, EFS, etc.)

### 3. Install Containerd Shim

```bash
# Download Flox containerd shim
curl -L https://flox.dev/shim/containerd-shim-flox-v1 -o /usr/local/bin/containerd-shim-flox-v1
chmod +x /usr/local/bin/containerd-shim-flox-v1

# Configure containerd
cat >> /etc/containerd/config.toml << 'EOF'
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.flox]
  runtime_type = "io.containerd.runc.v2"
  runtime_engine = "/usr/local/bin/containerd-shim-flox-v1"
  runtime_root = ""
EOF

# Restart containerd
sudo systemctl restart containerd
```

---

## Kubernetes Configuration

### 1. Create RuntimeClass

```yaml
# runtime-class.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: flox
handler: flox
scheduling:
  nodeSelector:
    flox.dev/runtime: "installed"
  tolerations:
    - key: flox.dev/runtime
      operator: Equal
      value: "installed"
      effect: NoSchedule
```

Apply:
```bash
kubectl apply -f runtime-class.yaml
```

### 2. Label Nodes

Mark nodes with Flox runtime:

```bash
# Label all nodes (or specific ones)
kubectl label nodes --all flox.dev/runtime=installed

# Or label specific nodes
kubectl label node node-1 node-2 node-3 flox.dev/runtime=installed
```

---

## Deployment Manifests

### Basic Deployment

```yaml
# ticket-processor-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor
  namespace: ml-workloads
  labels:
    app: ticket-processor
    version: v0.1.0
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ticket-processor
  template:
    metadata:
      labels:
        app: ticket-processor
        version: v0.1.0
    spec:
      runtimeClassName: flox  # Use Flox runtime

      # Init container to set up Flox environment
      initContainers:
      - name: flox-init
        image: ghcr.io/flox/flox:latest
        command:
        - /bin/sh
        - -c
        - |
          flox init ticket-processor-env
          cd ticket-processor-env
          flox install ticket-processor
          # Pre-download models (optional)
          flox activate -- python -c "from src.processor.models import preload_all_models; preload_all_models()"
        volumeMounts:
        - name: flox-env
          mountPath: /flox
        - name: model-cache
          mountPath: /cache/models
        env:
        - name: MODEL_CACHE_DIR
          value: /cache/models
        - name: TRANSFORMERS_CACHE
          value: /cache/models/transformers

      containers:
      - name: processor
        image: ghcr.io/flox/flox:latest  # Minimal Flox runtime image
        command:
        - flox
        - activate
        - --
        - ticket-processor

        env:
        # LocalStack configuration
        - name: USE_LOCALSTACK
          value: "false"  # Use real AWS in production

        # AWS Configuration
        - name: AWS_REGION
          value: us-east-1
        - name: AWS_DEFAULT_REGION
          value: us-east-1

        # SQS Configuration
        - name: SQS_QUEUE_NAME
          value: ticket-processing-queue
        - name: SQS_POLL_INTERVAL
          value: "20"
        - name: SQS_MAX_MESSAGES
          value: "10"

        # S3 Configuration
        - name: S3_RAW_BUCKET
          value: tickets-raw
        - name: S3_ENRICHED_BUCKET
          value: tickets-enriched

        # DynamoDB Configuration
        - name: DYNAMODB_TABLE_NAME
          value: tickets

        # Model Configuration
        - name: MODEL_CACHE_DIR
          value: /cache/models
        - name: TRANSFORMERS_CACHE
          value: /cache/models/transformers

        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"

        volumeMounts:
        - name: flox-env
          mountPath: /flox
        - name: model-cache
          mountPath: /cache/models

        # Health checks
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pgrep -f ticket-processor
          initialDelaySeconds: 30
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3

        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pgrep -f ticket-processor
          initialDelaySeconds: 20
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

      volumes:
      - name: flox-env
        emptyDir: {}
      - name: model-cache
        persistentVolumeClaim:
          claimName: model-cache-pvc

      # Service account for AWS IAM roles
      serviceAccountName: ticket-processor

      # Security context
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
```

### ConfigMap for Environment Variables

```yaml
# ticket-processor-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ticket-processor-config
  namespace: ml-workloads
data:
  SQS_QUEUE_NAME: "ticket-processing-queue"
  SQS_POLL_INTERVAL: "20"
  SQS_MAX_MESSAGES: "10"
  S3_RAW_BUCKET: "tickets-raw"
  S3_ENRICHED_BUCKET: "tickets-enriched"
  DYNAMODB_TABLE_NAME: "tickets"
  MODEL_CACHE_DIR: "/cache/models"
  TRANSFORMERS_CACHE: "/cache/models/transformers"
```

### PersistentVolumeClaim for Model Cache

```yaml
# model-cache-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: model-cache-pvc
  namespace: ml-workloads
spec:
  accessModes:
    - ReadWriteMany  # Shared across pods
  resources:
    requests:
      storage: 1Gi  # 592 MB models + buffer
  storageClassName: efs  # Use EFS or equivalent
```

### ServiceAccount with IAM Role (EKS)

```yaml
# service-account.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ticket-processor
  namespace: ml-workloads
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/ticket-processor-role
```

---

## CPU-Specific Variants

Deploy different variants based on node CPU capabilities:

### AVX2 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor-avx2
spec:
  template:
    spec:
      runtimeClassName: flox

      nodeSelector:
        cpu.feature.node.kubernetes.io/AVX2: "true"  # Require AVX2

      initContainers:
      - name: flox-init
        command:
        - flox
        - install
        - ticket-processor-avx2  # AVX2-optimized variant

      # ... rest same as basic deployment ...
```

### AVX512 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor-avx512
spec:
  template:
    spec:
      nodeSelector:
        cpu.feature.node.kubernetes.io/AVX512: "true"  # Require AVX512

      # Install AVX512 variant
      # ... similar to AVX2 ...
```

---

## Deployment

### 1. Create Namespace

```bash
kubectl create namespace ml-workloads
```

### 2. Apply Manifests

```bash
# Apply in order
kubectl apply -f runtime-class.yaml
kubectl apply -f service-account.yaml
kubectl apply -f model-cache-pvc.yaml
kubectl apply -f ticket-processor-config.yaml
kubectl apply -f ticket-processor-deployment.yaml
```

### 3. Verify Deployment

```bash
# Check pods
kubectl get pods -n ml-workloads

# Check logs
kubectl logs -n ml-workloads -l app=ticket-processor --tail=50

# Describe pod
kubectl describe pod -n ml-workloads <pod-name>
```

Expected output:
```
NAME                                READY   STATUS    RESTARTS   AGE
ticket-processor-5d7c8b9f6d-abc12   1/1     Running   0          2m
ticket-processor-5d7c8b9f6d-def34   1/1     Running   0          2m
ticket-processor-5d7c8b9f6d-ghi56   1/1     Running   0          2m
```

---

## Scaling

### Manual Scaling

```bash
# Scale to 5 replicas
kubectl scale deployment ticket-processor -n ml-workloads --replicas=5
```

### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ticket-processor-hpa
  namespace: ml-workloads
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ticket-processor
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

Apply:
```bash
kubectl apply -f hpa.yaml
```

---

## Monitoring

### Prometheus Metrics

Add Prometheus annotations to deployment:

```yaml
spec:
  template:
    metadata:
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
```

### CloudWatch Logs (EKS)

Configure Fluent Bit to ship logs:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
data:
  fluent-bit.conf: |
    [OUTPUT]
        Name cloudwatch_logs
        Match   *
        region us-east-1
        log_group_name /aws/eks/ml-workloads
        log_stream_prefix ticket-processor-
```

---

## Benefits of Imageless Deployment

### 1. No Image Builds
- **Traditional**: Build images for every code change
- **Flox**: Update manifest, redeploy instantly

### 2. No Registry Management
- **Traditional**: Push/pull from Docker registry
- **Flox**: Direct from Flox catalog

### 3. Instant Rollbacks
```bash
# Traditional: Rebuild and push previous image
docker build -t app:v1.2.3 .
docker push app:v1.2.3
kubectl set image deployment/app app=app:v1.2.3

# Flox: Change manifest version
kubectl set env deployment/ticket-processor FLOX_PACKAGE_VERSION=0.0.9
```

### 4. Guaranteed Consistency
- **Traditional**: Image layers can drift
- **Flox**: Nix hashes ensure bit-for-bit reproducibility

### 5. Shared Nix Store
- **Traditional**: Each node downloads full images
- **Flox**: Shared /nix/store, deduplicated packages

### 6. Multi-Architecture Support
- **Traditional**: Build separate images for AMD64/ARM64
- **Flox**: Single package, automatic platform selection

---

## Troubleshooting

### Pod Stuck in Init

**Symptom**: Init container hangs downloading models

**Solution**: Pre-populate model cache on PVC:

```bash
# Create job to pre-download models
kubectl apply -f - << 'EOF'
apiVersion: batch/v1
kind: Job
metadata:
  name: model-preloader
  namespace: ml-workloads
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: preloader
        image: ghcr.io/flox/flox:latest
        command:
        - flox
        - activate
        - --
        - python
        - -c
        - "from src.processor.models import preload_all_models; preload_all_models()"
        volumeMounts:
        - name: model-cache
          mountPath: /cache/models
      volumes:
      - name: model-cache
        persistentVolumeClaim:
          claimName: model-cache-pvc
EOF
```

### RuntimeClass Not Found

**Error**: `Warning  FailedCreate  runtimeclass.node.k8s.io "flox" not found`

**Solution**: Apply RuntimeClass manifest and verify:

```bash
kubectl apply -f runtime-class.yaml
kubectl get runtimeclass flox
```

### AWS Permissions Issues

**Error**: `ClientError: An error occurred (AccessDenied)`

**Solution**: Verify IAM role and service account:

```bash
# Check service account annotation
kubectl describe sa ticket-processor -n ml-workloads

# Verify IAM role policy allows SQS/S3/DynamoDB access
```

---

## Next Steps

- **Phase 5 Complete**: Imageless K8s deployment guide
- **Phase 6 (Optional)**: Lambda container deployment
- **Production**: Implement monitoring, alerting, auto-scaling

---

**Generated**: 2025-11-21
**Project**: LocalStack ML Workload Demo
**Phase**: 4/5 - Imageless Kubernetes Deployment
