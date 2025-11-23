# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

ML-powered support ticket enrichment pipeline built with Flox, PyTorch, and LocalStack. Demonstrates CPU-optimized ML workloads, Flox environment composition, and imageless Kubernetes deployment on AWS EKS.

**Key Architecture:** Raw tickets → S3 → SQS (event-driven) → ML Worker → DynamoDB + S3 (enriched)

## Project Structure

```
src/
├── generator/           # Ticket generator package (published to FloxHub)
│   └── ticket_generator.py  # Creates realistic tickets, uploads to S3
├── processor/          # ML processor package (published to FloxHub)
│   ├── worker.py       # SQS worker loop, orchestration
│   ├── ml_pipeline.py  # (not present - enrichment logic in worker.py)
│   ├── models.py       # Model loading with @lru_cache
│   ├── embeddings.py   # Semantic embeddings (all-MiniLM-L6-v2)
│   ├── classifier.py   # Intent/urgency classification
│   └── summarizer.py   # Text summarization (DistilBART)
└── common/            # Shared code
    ├── schemas.py      # Pydantic v2 models (RawTicket, EnrichedTicket)
    ├── config.py       # Configuration via pydantic-settings
    └── aws_clients.py  # Boto3 client initialization

.flox/
├── env/manifest.toml   # Main environment (composes both packages)
└── pkgs/
    ├── reinvent-demo-ticket-generator.nix  # Generator build recipe
    └── reinvent-demo-ticket-processor.nix  # Processor build recipe

tests/
├── unit/              # Model/function tests with mocking
└── integration/       # End-to-end pipeline tests with LocalStack
```

## Essential Commands

### Environment Setup
```bash
# Activate environment and start all services (LocalStack, generator, processor)
flox activate --start-services

# Just enter environment without starting services
flox activate

# Check service status
flox services status

# View service logs
flox services logs ticket-generator
flox services logs ticket-processor
```

### LocalStack Resource Management
```bash
# Initialize S3 buckets, SQS queue, DynamoDB table
make setup

# Upload sample tickets to trigger processing
make seed

# Clean and reinitialize all resources
make reset

# Check LocalStack health
make status
```

### Testing
```bash
# Run all tests (41 unit + 12 integration)
pytest -v

# Unit tests only (mocked ML models)
pytest tests/unit/ -v

# Integration tests (requires LocalStack running)
pytest tests/integration/ -v

# Single test file
pytest tests/integration/test_ml_pipeline.py -v -s
```

### Package Building & Publishing
```bash
# Build generator package locally
flox build .flox/pkgs/reinvent-demo-ticket-generator.nix

# Build processor package locally
flox build .flox/pkgs/reinvent-demo-ticket-processor.nix

# Publish to FloxHub (requires auth)
flox publish .flox/pkgs/reinvent-demo-ticket-generator.nix
flox publish .flox/pkgs/reinvent-demo-ticket-processor.nix

# Test packages manually
/nix/store/...-ticket-generator-0.1.0/bin/ticket-generator --help
/nix/store/...-ticket-processor-0.1.0/bin/ticket-processor
```

### Demo Helper Functions
These functions are available after `flox activate --start-services`:
```bash
demo               # Run complete demo walkthrough
run-processor      # Start processor manually (if service not running)
show-results       # View enriched tickets in S3
show-sentiment NEGATIVE  # Query tickets by sentiment
show-urgent        # Show critical/high urgency tickets
```

## Code Architecture

### Data Schemas (Pydantic v2)

**Critical Schema Detail:** The `created_at` field is defined as `int` (Unix timestamp), NOT an ISO string. This is intentional for efficient DynamoDB sorting.

```python
class RawTicket(BaseModel):
    ticket_id: str
    subject: str
    body: str
    created_at: int  # Unix timestamp (e.g., 1700000000)
    customer_id: str
    priority: Optional[str]
    metadata: TicketMetadata

class EnrichmentData(BaseModel):
    embedding: List[float]  # 384-dimensional vector
    intent: str
    intent_confidence: float
    urgency: str
    urgency_confidence: float
    sentiment: str  # "POSITIVE", "NEGATIVE", "NEUTRAL"
    sentiment_confidence: float
    summary: str
    processed_at: str  # ISO format: "2024-01-15T10:30:00Z"
    model_version: str

class EnrichedTicket(BaseModel):
    # Raw fields (flattened)
    ticket_id: str
    subject: str
    body: str
    created_at: int  # Still Unix timestamp
    customer_id: str
    priority: Optional[str]
    metadata: TicketMetadata
    # ML enrichment
    enrichment: EnrichmentData
```

### ML Models

All models are CPU-optimized distilled variants loaded lazily with `@lru_cache`:

1. **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` (22 MB)
   - Output: 384-dimensional vectors
   - Use: Semantic search, ticket similarity
   - Performance: ~300ms per ticket

2. **Sentiment:** `distilbert-base-uncased-finetuned-sst-2-english` (255 MB)
   - Output: POSITIVE, NEGATIVE, NEUTRAL + confidence
   - Performance: ~200ms per ticket

3. **Summarization:** `sshleifer/distilbart-cnn-6-6` (315 MB)
   - Output: 50-token summary
   - Performance: ~500ms per ticket

**Total processing time:** 1.0-2.4s per ticket

### Model Caching

Models cache to `$FLOX_ENV_CACHE/models/` to persist across environment rebuilds:
```bash
# Environment variables set in manifest.toml
MODEL_CACHE_DIR="$FLOX_ENV_CACHE/models"
TRANSFORMERS_CACHE="$FLOX_ENV_CACHE/models/transformers"
HF_HOME="$FLOX_ENV_CACHE/models/huggingface"
```

First activation downloads ~600MB. Subsequent activations reuse cached models.

### AWS Resource Names

**S3 Buckets:**
- `tickets-raw` - Raw ticket uploads (generator writes here)
- `tickets-enriched` - ML-enriched tickets with embeddings (processor writes here)

**SQS Queue:**
- `ticket-processing-queue` - Receives S3 event notifications

**DynamoDB Table:**
- `tickets-metadata` - Queryable metadata (without embeddings due to size)
- Keys: `ticket_id` (hash), `created_at` (range)
- GSI: `urgency-index` for filtering by urgency

**S3 Event Notification:**
- Bucket: `tickets-raw`
- Event: `s3:ObjectCreated:*`
- Destination: `ticket-processing-queue` (SQS)

## Flox Environment Composition

This project uses Flox's environment composition to combine two independently published packages:

```toml
# .flox/env/manifest.toml
[include]
environments = [
    { remote = "barstoolbluz/reinvent-demo-ticket-generator" },
    { remote = "barstoolbluz/reinvent-demo-ticket-processor" }
]
```

Each package has its own service definition. When you run `flox activate --start-services`, all three services start:
1. `localstack` (from main environment)
2. `ticket-generator` (from included environment)
3. `ticket-processor` (from included environment)

## Development Workflow

### Adding ML Features

When adding new ML capabilities:

1. **Add model loading to `src/processor/models.py`:**
   ```python
   @lru_cache(maxsize=1)
   def load_new_model() -> ModelType:
       model = ModelType.from_pretrained(
           "model-name",
           cache_dir=get_model_cache_dir(),
           device="cpu"
       )
       return model
   ```

2. **Create processing function in appropriate module** (`embeddings.py`, `classifier.py`, `summarizer.py`)

3. **Update `EnrichmentData` schema in `src/common/schemas.py`** to include new fields

4. **Add tests in `tests/unit/test_processor.py`** with mocked models

5. **Update DynamoDB schema if needed** in `src/common/schemas.py` (DynamoDBTicket)

### Testing Strategy

- **Unit tests:** Mock all ML models to avoid expensive inference
- **Integration tests:** Use real models but small sample data
- **LocalStack:** Always required for integration tests (S3, SQS, DynamoDB)

Test execution order:
1. Ensure LocalStack is running (`flox activate --start-services` or `make setup`)
2. Run unit tests first (fast, no real models)
3. Run integration tests (slower, loads real models)

### Debugging Tips

**Check SQS queue depth:**
```bash
awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/ticket-processing-queue \
  --attribute-names ApproximateNumberOfMessages
```

**View raw tickets in S3:**
```bash
awslocal s3 ls s3://tickets-raw/
awslocal s3 cp s3://tickets-raw/DEMO-12345.json - | python -m json.tool
```

**Query DynamoDB directly:**
```bash
awslocal dynamodb scan --table-name tickets-metadata --limit 5
```

**Check model cache:**
```bash
ls -lh $FLOX_ENV_CACHE/models/
```

## Production Deployment

### Imageless Kubernetes (EKS)

This project supports imageless Kubernetes deployment using Flox's containerd shim:

**Benefits:**
- 12-22x faster than Docker builds (1-2 min vs 20-30 min)
- 84% storage savings (shared /nix/store)
- No Docker registry required
- Instant rollbacks (change package version in annotation)

**Deployment pattern:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor
spec:
  replicas: 3
  template:
    spec:
      runtimeClassName: flox
      containers:
      - name: processor
        command: ["flox", "activate", "-r", "flox/reinvent-demo-ticket-processor", "--", "ticket-processor"]
        env:
        - name: AWS_REGION
          value: "us-east-1"
        - name: MODEL_CACHE_DIR
          value: "/cache/models"
        volumeMounts:
        - name: model-cache
          mountPath: /cache
      volumes:
      - name: model-cache
        persistentVolumeClaim:
          claimName: ml-models-cache
```

See `docs/IMAGELESS_K8S.md` and `docs/EKS_SETUP_FOR_CI.md` for detailed setup.

### Model Caching in Production

For Kubernetes, use a PVC or emptyDir volume:
- First pod downloads models (~30-60s cold start)
- Subsequent pods reuse cached models (instant start)
- Models persist across pod restarts if using PVC

## Important Notes

### Schema Constraints

- `created_at` is **always** a Unix timestamp integer (not ISO string)
- DynamoDB composite key: `ticket_id` (hash) + `created_at` (range)
- Embeddings (384 floats) NOT stored in DynamoDB due to size limits
- Full enriched data (including embeddings) stored in S3

### Model Performance

- All models are **CPU-only** (no GPU)
- Optimized for x86 AVX2 (Intel Haswell+, AMD Zen 1+)
- ARM support coming when PyTorch ARM builds are available in Flox
- Processing: ~1-2s per ticket, scales linearly with workers

### Environment Variables

Key variables set in `manifest.toml`:
- `AWS_ENDPOINT_URL` - LocalStack endpoint (http://localhost:4566)
- `MODEL_CACHE_DIR` - Model cache location ($FLOX_ENV_CACHE/models)
- `PYTHONUNBUFFERED=1` - Immediate log output

### Package Updates

When updating published packages:
1. Modify `.flox/pkgs/*.nix` build recipes
2. Run `flox build` to test locally
3. Run `flox publish` to push to FloxHub
4. Update version in downstream environments: `flox upgrade`

## Common Issues

**Issue:** Models fail to download
**Cause:** No internet or HuggingFace unavailable
**Fix:** Check connectivity; models cache to `$FLOX_ENV_CACHE/models/`

**Issue:** LocalStack resources not found
**Cause:** Resources not initialized or LocalStack restarted
**Fix:** Run `make setup && make seed`

**Issue:** Tests fail with "Model not found"
**Cause:** Integration tests need real models downloaded
**Fix:** First activation downloads models; wait for completion

**Issue:** SQS messages not being processed
**Cause:** Worker not running or queue URL mismatch
**Fix:** Check `flox services status`; verify queue URL in worker logs
