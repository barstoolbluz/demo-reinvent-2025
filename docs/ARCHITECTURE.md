# Support Ticket Enrichment Pipeline Architecture

## Overview

Production-ready ML pipeline demonstrating CPU-optimized PyTorch workloads with Flox environments, LocalStack for local development, and imageless Kubernetes deployment on AWS EKS.

## Data Flow

```
┌─────────────┐
│   API/CLI   │ Upload raw tickets (JSON)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│  S3 Bucket: tickets-raw     │
│  s3://tickets-raw/<id>.json │
└──────┬──────────────────────┘
       │ S3 Event Notification
       ▼
┌─────────────────────┐
│  SQS Queue          │
│  ticket-processing  │
└──────┬──────────────┘
       │ Long polling (20s)
       ▼
┌─────────────────────────────────────────┐
│  Worker (K8s Pod or Lambda)             │
│  ┌───────────────────────────────────┐  │
│  │ 1. Fetch ticket from S3           │  │
│  │ 2. Load models (cached)           │  │
│  │ 3. Generate embedding (384-dim)   │  │
│  │ 4. Classify intent & urgency      │  │
│  │ 5. Generate summary               │  │
│  └───────────────────────────────────┘  │
└──────┬───────────────────────┬──────────┘
       │                       │
       ▼                       ▼
┌─────────────────┐    ┌──────────────────────┐
│  DynamoDB       │    │  S3: tickets-enriched│
│  Table: tickets │    │  (with embeddings)   │
└─────────────────┘    └──────────────────────┘
```

## Components

### 1. Ticket Ingestion
- Raw tickets uploaded to S3 as JSON
- S3 event triggers SQS message
- Schema: `{ticket_id, subject, body, priority, created_at, customer_id}`

### 2. Worker Process
- Polls SQS queue (long polling for efficiency)
- Fetches ticket from S3
- Runs ML pipeline
- Stores results in DynamoDB + enriched S3 bucket

### 3. ML Pipeline

#### Embedding Generation
- Model: `sentence-transformers/all-MiniLM-L6-v2` (22MB)
- Output: 384-dimensional vector for semantic search
- Use case: Ticket similarity, routing, clustering

#### Intent Classification
- Keyword-based classification with confidence scoring
- Categories: login_issue, payment_issue, feature_request, bug_report, account_management
- Helps automatic routing to correct team

#### Urgency Classification
- Combines explicit priority field with keyword detection
- Levels: critical, high, medium, low
- Keywords: urgent, emergency, asap (critical), can't, problem (high), etc.

#### Summarization
- Model: `sshleifer/distilbart-cnn-6-6` (315MB)
- Generates concise summary (50 tokens max)
- Useful for dashboards and quick triage

### 4. Storage

#### DynamoDB
- Primary key: `ticket_id` (hash), `created_at` (range)
- Stores: metadata, intent, urgency, summary (no embedding due to size)
- GSI: `urgency-index` for filtering by urgency level

#### S3 (Enriched)
- Complete enriched data including 384-dim embedding
- Used for semantic search, ML training, analytics

## CPU-Specific Optimization

### x86 AVX2 (Current)
- Target: Intel Haswell+ (2013), AMD Zen 1+ (2017)
- PyTorch: `flox/pytorch-python313-cpu-avx2`
- Optimizations: Vectorized operations, FP32 SIMD
- Performance: 2-3x faster than generic x86 build

### Future: ARM Support
When ARM PyTorch builds are ready:
- Graviton2 (ARMv8.2): NEON, half-precision
- Graviton3+ (ARMv9): SVE, int8, better cache
- Flox automatically selects correct variant via `systems` attribute

## Local Development (LocalStack)

LocalStack Community Edition emulates:
- **S3**: Object storage for tickets
- **SQS**: Message queue for processing
- **DynamoDB**: Metadata storage
- **Lambda**: (optional) Function execution

**Not emulated**: EKS, ECR (use real AWS or skip)

### LocalStack as Flox Service
```toml
[services]
localstack.command = "localstack start -d"
localstack.is-daemon = true
```

Start with: `flox activate -s`

## Production Deployment

### Imageless Kubernetes (EKS)
- No Docker builds or image registries
- Pods reference Flox environments via annotation:
  ```yaml
  annotations:
    flox.dev/environment: "yourorg/ticket-processor"
  ```
- Flox containerd shim pulls environment from FloxHub
- Dependencies cached in `/nix/store` on nodes
- Update flow: `flox push` → `kubectl rollout restart`

### Lambda Container (Optional)
- Built with `flox containerize`
- Image size: <10GB (CPU-optimized PyTorch)
- Triggered by SQS messages
- Use for bursty, infrequent workloads

## Model Caching Strategy

### Development
- Models cached in `$FLOX_ENV_CACHE/models/`
- Survives environment rebuilds
- First activation downloads ~600MB

### Kubernetes
- emptyDir volume mounted at `/mnt/models`
- First pod on node downloads models (30-60s)
- Subsequent pods reuse cached models (instant start)
- Alternative: PVC for persistent cache across node replacements

### Lambda
- Models in `/tmp` (10GB ephemeral storage)
- Cold start: 15-30s (includes model loading)
- Warm invocations: <1s
- Consider Lambda Layers or EFS for shared cache

## Performance Characteristics

### Inference Time (x86 AVX2, per ticket)
- Embedding: ~50ms
- Classification: ~20ms (keyword-based)
- Summarization: ~200ms
- **Total: ~270ms per ticket**

### Throughput
- Single worker: ~3-4 tickets/second
- K8s (10 pods): ~30-40 tickets/second
- Scales linearly with pod count

### Cold Start
- K8s first pod: 30-60s (model download)
- K8s subsequent pods: <5s (cached models)
- Lambda: 15-30s (includes model load to /tmp)

## Cost Optimization

### CPU-Only Rationale
- Distilled models run efficiently on CPU
- No GPU scheduling complexity
- Better multi-tenancy and resource utilization
- ~10x cheaper per inference for small models

### LocalStack Benefits
- Zero AWS costs in development
- Fast iteration cycles
- Test full pipeline locally

### Imageless K8s Benefits
- No Docker build time (CI/CD faster)
- No registry storage costs
- Instant environment updates via FloxHub

## Security Considerations

### Secrets Management
- Never store in `$FLOX_ENV_CACHE`
- Use AWS Secrets Manager in production
- Environment variables for runtime overrides
- IAM roles for EKS pods (IRSA)

### Model Integrity
- Models downloaded from Hugging Face Hub
- Cache in trusted storage
- Verify checksums in production

## Monitoring & Observability

### Metrics
- SQS queue depth
- Processing latency (p50, p99)
- Model inference time per operation
- Error rate by error type

### Logging
- Worker logs to stdout (K8s) or CloudWatch (Lambda)
- Include ticket_id for tracing
- Log level configurable via environment

### Health Checks
- K8s liveness: HTTP endpoint
- K8s readiness: Models loaded
- Lambda: DLQ for failed messages

## Future Enhancements

1. **Multi-Architecture Support**: Add ARM variants when builds ready
2. **Semantic Search API**: Query by embedding similarity
3. **Real-time Classification**: WebSocket streaming
4. **A/B Testing**: Multiple model versions in parallel
5. **Model Fine-tuning**: Retrain on historical tickets
