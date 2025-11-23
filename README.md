# AWS re:Invent 2025 Demo - ML Ticket Processing

Flox packages for ML-powered support ticket enrichment with LocalStack.

## Overview

This repository contains two Flox packages that demonstrate a complete ML pipeline for ticket processing. Both packages are published to FloxHub and designed for environment composition.

---

## Packages

### 1. reinvent-demo-ticket-generator

**Published:** [`flox/reinvent-demo-ticket-generator`](https://hub.flox.dev/flox/reinvent-demo-ticket-generator)
**Build Recipe:** [`.flox/pkgs/reinvent-demo-ticket-generator.nix`](.flox/pkgs/reinvent-demo-ticket-generator.nix)
**Version:** 0.1.0

#### Description

Continuously generates realistic support tickets for demonstration purposes. Creates varied tickets across multiple categories and uploads them to S3, triggering the processor service via SQS event notifications.

#### Features

- **6 ticket categories:** login issues, payment issues, bug reports, feature requests, account issues, billing issues
- **19 realistic templates** with variable substitution
- **30+ variable types** for diverse content generation
- **Rate limiting:** Random intervals (8-15s, max 7 tickets/minute)
- **Continuous operation:** Runs as daemon until stopped

#### Build Recipe Details

**Location:** `.flox/pkgs/reinvent-demo-ticket-generator.nix`

**Dependencies:**
```nix
pythonEnv = python313.withPackages (ps: with ps; [
  boto3      # AWS SDK
  botocore   # AWS SDK core
]);
```

**Build Process:**
1. **Source Selection** - Copies only required files via regex filter:
   ```nix
   src = lib.sourceByRegex ../.. [
     "^src(/.*)?$"           # Python source code
     "^pyproject\\.toml$"    # Project metadata
     "^README\\.md$"         # Documentation
   ];
   ```

2. **Installation** - No compilation, pure Python:
   ```nix
   dontBuild = true;
   ```

3. **Package Structure:**
   ```
   $out/
   ├── bin/
   │   └── ticket-generator       # Executable wrapper
   └── lib/python3.13/site-packages/
       └── src/                   # Python source
           └── generator/
               ├── __init__.py
               └── ticket_generator.py
   ```

4. **Executable Creation** - Shell wrapper with Python path setup:
   ```nix
   cat > $out/bin/ticket-generator << EOF
   #!${pythonEnv}/bin/python
   import sys
   sys.path.insert(0, "${pythonEnv}/lib/python3.13/site-packages")
   sys.path.insert(0, "$out/lib/python3.13/site-packages")
   from src.generator.ticket_generator import main
   if __name__ == "__main__":
       main()
   EOF
   chmod +x $out/bin/ticket-generator
   ```

**Key Design Choice:** Uses heredoc without single quotes (`<< EOF` not `<< 'EOF'`) to ensure `$out` variable expansion works correctly. This was a critical bug fix - single quotes would prevent path substitution, causing runtime import errors.

#### Source Code

**Main File:** `src/generator/ticket_generator.py` (272 lines)

**Template System:**
```python
TICKET_TEMPLATES = {
    "login_issue": [
        {
            "subject": "Cannot login to my account",
            "body": "I've been trying to login for {time_period}...",
            "urgency_hints": ["urgent", "critical"],
            "sentiment": "negative"
        },
        # ... more templates
    ],
    # ... more categories
}
```

**Variable Substitution:**
```python
VARIABLES = {
    "time_period": ["hours", "2 hours", "half a day"],
    "error_msg": ["Invalid credentials", "Session expired"],
    # ... 30+ variable types
}
```

**Output Format:**
```python
ticket = {
    "ticket_id": f"DEMO-{random.randint(10000, 99999)}",
    "customer_id": f"CUST-{random.randint(1000, 9999)}",
    "subject": subject,
    "body": body,
    "created_at": int(datetime.now(timezone.utc).timestamp()),  # Unix timestamp
    "priority": random.choice(["low", "medium", "high", "critical"]),
    "metadata": {
        "source": random.choice(["email", "web", "api", "chat"]),
        "language": "en",
        "tags": []
    }
}
```

**Important:** Uses `datetime.now(timezone.utc).timestamp()` (not deprecated `utcnow()`) and produces Unix timestamp integer (not ISO string) to match the `RawTicket` Pydantic schema.

#### Usage

**Direct Execution:**
```bash
# Build from source
cd /home/daedalus/dev/demo-reinvent-2025
flox build .flox/pkgs/reinvent-demo-ticket-generator.nix

# Publish to FloxHub
flox publish .flox/pkgs/reinvent-demo-ticket-generator.nix
```

**As Service (recommended):**
```bash
# Use dedicated service environment
cd /home/daedalus/dev/reinvent-demo-ticket-generator
flox activate --start-services

# Or compose into main environment
cd /home/daedalus/dev/demo-reinvent-2025
flox activate --start-services  # Includes generator via [include]
```

**Service Configuration:**
```toml
[install]
ticket-generator.pkg-path = "flox/reinvent-demo-ticket-generator"

[services]
ticket-generator.command = "ticket-generator"
ticket-generator.is-daemon = true
ticket-generator.shutdown.command = "pkill -f 'ticket-generator' || true"
```

---

### 2. reinvent-demo-ticket-processor

**Published:** [`flox/reinvent-demo-ticket-processor`](https://hub.flox.dev/flox/reinvent-demo-ticket-processor)
**Build Recipe:** [`.flox/pkgs/reinvent-demo-ticket-processor.nix`](.flox/pkgs/reinvent-demo-ticket-processor.nix)
**Version:** 0.1.0

#### Description

ML-powered service that enriches support tickets with semantic embeddings, intent classification, urgency classification, sentiment analysis, and text summarization. Polls SQS queue for ticket notifications, processes tickets through ML pipeline, and stores enriched results in DynamoDB and S3.

#### Features

- **384-dimensional semantic embeddings** (sentence-transformers/all-MiniLM-L6-v2)
- **Intent classification** - Categorizes into login, payment, bug, feature, account, billing
- **Urgency classification** - Determines critical, high, medium, or low priority
- **Sentiment analysis** - POSITIVE, NEGATIVE, or NEUTRAL (DistilBERT)
- **Text summarization** - Concise summary generation (DistilBART)
- **Processing time:** ~1.0-2.4s per ticket
- **Throughput:** Up to 60 tickets/minute
- **CPU-only:** No GPU required

#### Architecture

```
┌─────────────┐     S3 Event      ┌─────────────┐
│   S3 Raw    │ ─────Notify─────► │     SQS     │
│   Tickets   │                   │    Queue    │
└─────────────┘                   └──────┬──────┘
                                         │ Poll (long-poll 20s)
                                         ▼
                                  ┌──────────────┐
                                  │  Processor   │
                                  │  (ML Worker) │
                                  └──────┬───────┘
                                         │
                        ┌────────────────┼────────────────┐
                        ▼                                 ▼
                 ┌─────────────┐                  ┌─────────────┐
                 │  DynamoDB   │                  │ S3 Enriched │
                 │  (metadata) │                  │   (full)    │
                 └─────────────┘                  └─────────────┘
```

#### ML Models

| Model | Purpose | Size | Performance |
|-------|---------|------|-------------|
| **all-MiniLM-L6-v2** | Semantic embeddings | 22 MB | ~300ms |
| **distilbert-sst-2** | Sentiment analysis | 255 MB | ~200ms |
| **distilbart-cnn-6-6** | Text summarization | 315 MB | ~500ms |

**Total:** 592 MB, CPU-optimized distilled models

#### Build Recipe Details

**Location:** `.flox/pkgs/reinvent-demo-ticket-processor.nix`

**Dependencies:**
```nix
pythonEnv = python313.withPackages (ps: with ps; [
  # Core AWS & data
  boto3
  botocore
  pydantic
  pydantic-settings
  python-dateutil

  # ML stack
  pytorch              # ML framework (~500 MB)
  torchvision         # Vision utilities
  transformers        # HuggingFace transformers
  sentence-transformers  # Embeddings
  numpy               # Numerical computing

  # Testing (optional for runtime)
  pytest
  hypothesis
]);
```

**Build Process:**

1. **Source Selection:**
   ```nix
   src = lib.sourceByRegex ../.. [
     "^src(/.*)?$"           # All Python source
     "^setup\\.py$"          # Setup script
     "^README\\.md$"         # Documentation
     "^pyproject\\.toml$"    # Project config
   ];
   ```

2. **Installation:**
   ```nix
   dontBuild = true;  # Pure Python, no compilation
   ```

3. **Package Structure:**
   ```
   $out/
   ├── bin/
   │   └── ticket-processor       # Executable wrapper
   └── lib/python3.13/site-packages/
       └── src/                   # Python source (~2,700 lines)
           ├── common/
           │   ├── config.py      # Configuration
           │   ├── schemas.py     # Pydantic models
           │   └── storage.py     # S3/DynamoDB
           └── processor/
               ├── classifier.py  # Intent/urgency
               ├── ml_pipeline.py # ML orchestration
               ├── models.py      # Model loading/caching
               └── worker.py      # SQS worker loop
   ```

4. **Executable Creation:**
   ```nix
   cat > $out/bin/ticket-processor << EOF
   #!${pythonEnv}/bin/python
   import sys
   sys.path.insert(0, "${pythonEnv}/lib/python3.13/site-packages")
   sys.path.insert(0, "$out/lib/python3.13/site-packages")
   from src.processor.worker import main
   if __name__ == "__main__":
       main()
   EOF
   chmod +x $out/bin/ticket-processor
   ```

**Critical Fix Applied:** Changed from `<< 'EOF'` to `<< EOF` (no single quotes) to allow `$out` variable expansion. Single quotes caused literal `"$out"` string in the path, breaking imports at runtime.

**Package Size:** ~2+ GB with all ML dependencies (PyTorch, transformers, models)

#### Source Code

**Main Components:**

1. **Worker (`src/processor/worker.py`)** - SQS polling and orchestration
   ```python
   class TicketProcessor:
       def poll_and_process(self):
           while True:
               messages = sqs.receive_message(
                   QueueUrl=queue_url,
                   MaxNumberOfMessages=10,
                   WaitTimeSeconds=20  # Long polling
               )
               for message in messages:
                   raw_ticket = fetch_from_s3(message)
                   enriched = self.process_ticket(raw_ticket)
                   store_results(enriched)
   ```

2. **ML Pipeline (`src/processor/ml_pipeline.py`)** - Parallel processing
   ```python
   def enrich_ticket(ticket: RawTicket) -> EnrichmentData:
       # Generate embedding (384-dim vector)
       embedding = generate_embedding(ticket)

       # Classify in parallel
       intent, intent_conf = classify_intent(ticket)
       urgency, urgency_conf = classify_urgency(ticket)
       sentiment, sentiment_conf = classify_sentiment(ticket)

       # Summarize
       summary = generate_summary(ticket)

       return EnrichmentData(
           embedding=embedding,
           intent=intent,
           urgency=urgency,
           sentiment=sentiment,
           summary=summary,
           processed_at=datetime.utcnow().isoformat() + "Z"
       )
   ```

3. **Model Loading (`src/processor/models.py`)** - Lazy loading with caching
   ```python
   @lru_cache(maxsize=1)
   def load_embedding_model() -> SentenceTransformer:
       model = SentenceTransformer(
           "sentence-transformers/all-MiniLM-L6-v2",
           cache_folder=cache_dir,
           device="cpu"
       )
       return model
   ```

4. **Schemas (`src/common/schemas.py`)** - Pydantic v2 models
   ```python
   class RawTicket(BaseModel):
       ticket_id: str
       subject: str
       body: str
       created_at: int  # Unix timestamp (not ISO string!)
       customer_id: str
       priority: Optional[str]
       metadata: TicketMetadata

   class EnrichedTicket(BaseModel):
       # Raw fields (flattened)
       ticket_id: str
       subject: str
       body: str
       created_at: int
       customer_id: str
       priority: Optional[str]
       metadata: TicketMetadata

       # ML enrichment
       enrichment: EnrichmentData
   ```

**Schema Compatibility Note:** The `created_at` field is defined as `int` (Unix timestamp), not string. The ticket generator was updated to match this schema.

#### Usage

**Direct Execution:**
```bash
# Build from source
cd /home/daedalus/dev/demo-reinvent-2025
flox build .flox/pkgs/reinvent-demo-ticket-processor.nix

# Publish to FloxHub
flox publish .flox/pkgs/reinvent-demo-ticket-processor.nix
```

**As Service (recommended):**
```bash
# Use dedicated service environment
cd /home/daedalus/dev/reinvent-demo-ticket-processor
flox activate --start-services

# Or compose into main environment
cd /home/daedalus/dev/demo-reinvent-2025
flox activate --start-services  # Includes processor via [include]
```

**Service Configuration:**
```toml
[install]
ticket-processor.pkg-path = "flox/reinvent-demo-ticket-processor"

[vars]
# LocalStack configuration
AWS_ENDPOINT_URL = "http://localhost:4566"
AWS_REGION = "us-east-1"
AWS_ACCESS_KEY_ID = "test"
AWS_SECRET_ACCESS_KEY = "test"

# Model caching
MODEL_CACHE_DIR = "$FLOX_ENV_CACHE/models"
HF_HOME = "$FLOX_ENV_CACHE/models/huggingface"

[services]
ticket-processor.command = "ticket-processor"
ticket-processor.is-daemon = true
ticket-processor.shutdown.command = "pkill -f 'ticket-processor' || true"
```

**Performance Tuning:**
```toml
[vars]
# Increase workers for higher throughput
NUM_WORKERS = "4"

# Batch size for processing
BATCH_SIZE = "10"

# Model cache to avoid re-downloads
TRANSFORMERS_CACHE = "$FLOX_ENV_CACHE/models/transformers"
```

---

## Environment Composition

The main demo environment composes both packages:

**File:** `.flox/env/manifest.toml`

```toml
[include]
environments = [
    { floxhub = "barstoolbluz/reinvent-demo-ticket-generator" },
    { floxhub = "barstoolbluz/reinvent-demo-ticket-processor" }
]

[services]
localstack.command = "localstack start -d"
localstack.is-daemon = true
localstack.shutdown.command = "localstack stop"
```

**Result:** Single `flox activate --start-services` starts all three services:
- `localstack` - AWS emulation (S3, SQS, DynamoDB)
- `ticket-generator` - Continuous ticket creation
- `ticket-processor` - ML-powered enrichment

---

## Building & Publishing

### Build Locally

```bash
cd /home/daedalus/dev/demo-reinvent-2025

# Build generator
flox build .flox/pkgs/reinvent-demo-ticket-generator.nix

# Build processor
flox build .flox/pkgs/reinvent-demo-ticket-processor.nix

# Test builds
/nix/store/...-ticket-generator-0.1.0/bin/ticket-generator --help
/nix/store/...-ticket-processor-0.1.0/bin/ticket-processor --help
```

### Publish to FloxHub

```bash
# Publish generator
flox publish .flox/pkgs/reinvent-demo-ticket-generator.nix

# Publish processor
flox publish .flox/pkgs/reinvent-demo-ticket-processor.nix

# Verify publication
flox search reinvent-demo-ticket-generator
flox search reinvent-demo-ticket-processor
```

### Version Upgrades

After publishing new versions:

```bash
# Upgrade all environments using these packages
cd /home/daedalus/dev/reinvent-demo-ticket-generator
flox upgrade

cd /home/daedalus/dev/reinvent-demo-ticket-processor
flox upgrade

cd /home/daedalus/dev/demo-reinvent-2025
flox upgrade
```

---

## Quick Start

### Full Demo (All Services)

```bash
cd /home/daedalus/dev/demo-reinvent-2025
flox activate --start-services

# Services start automatically:
# - LocalStack (AWS emulation)
# - ticket-generator (creates tickets)
# - ticket-processor (processes tickets)

# Monitor logs
flox services logs ticket-generator
flox services logs ticket-processor

# Check status
flox services status

# Use helper functions (from profile)
show-results      # View enriched tickets
show-sentiment    # Query by sentiment
show-urgent       # Show critical tickets
demo             # Run complete demo
```

### Individual Services

```bash
# Generator only
cd /home/daedalus/dev/reinvent-demo-ticket-generator
flox activate --start-services

# Processor only
cd /home/daedalus/dev/reinvent-demo-ticket-processor
flox activate --start-services
```

---

## Troubleshooting

### Common Issues

**Issue:** `ModuleNotFoundError: No module named 'src'`
**Cause:** Heredoc used single quotes preventing `$out` expansion
**Fix:** Rebuild package with corrected Nix expression (no single quotes)

**Issue:** `Input should be a valid integer, unable to parse string as an integer`
**Cause:** Old tickets generated before schema fix (ISO string instead of Unix timestamp)
**Fix:** Clear old data and regenerate:
```bash
awslocal sqs purge-queue --queue-url $(awslocal sqs get-queue-url --queue-name ticket-processing-queue --query 'QueueUrl' --output text)
awslocal s3 rm s3://tickets-raw/ --recursive
```

**Issue:** Services won't start
**Cause:** LocalStack not running or resources not created
**Fix:**
```bash
flox services status
make setup
make seed
```

**Issue:** Models fail to download
**Cause:** No internet or HuggingFace unavailable
**Fix:** Check connectivity, models cache to `$FLOX_ENV_CACHE/models/`

---

## AWS Resources

Both packages interact with these LocalStack-emulated AWS services:

### S3 Buckets
- `tickets-raw` - Raw ticket uploads (generator writes here)
- `tickets-enriched` - Enriched tickets with ML data (processor writes here)

### SQS Queue
- `ticket-processing-queue` - Receives S3 event notifications when tickets uploaded

### DynamoDB Table
- `tickets-metadata` - Queryable ticket metadata (without 384-dim embeddings for size)

### S3 Event Notification
Configured on `tickets-raw` bucket:
- **Event:** `s3:ObjectCreated:*`
- **Destination:** `ticket-processing-queue` (SQS)
- **Purpose:** Automatic trigger when generator uploads ticket

---

## Production Deployment

### Kubernetes (Imageless)

Both packages support imageless Kubernetes deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-processor
spec:
  replicas: 3
  template:
    spec:
      runtimeClassName: flox  # Uses Flox runtime instead of Docker
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

**Benefits:**
- **12-22x faster** than Docker builds (1-2 min vs 20-30 min)
- **84% storage savings** (shared /nix/store)
- **No Docker registry** required
- **Instant rollbacks** (just change package version)

### EC2/Server

```bash
# Install Flox
curl -fsSL https://downloads.flox.dev/install | bash

# Activate environment and run as systemd service
flox activate -r flox/reinvent-demo-ticket-processor
systemctl start ticket-processor
```

---

## Testing

### Unit Tests (41 tests)

```bash
cd /home/daedalus/dev/demo-reinvent-2025
flox activate
pytest tests/unit/ -v
```

Tests model loading, embeddings, classification, summarization with mocking.

### Integration Tests (12 tests)

```bash
pytest tests/integration/ -v
```

Tests end-to-end ML pipeline with real models and LocalStack.

### ML Pipeline Test

```bash
pytest tests/integration/test_ml_pipeline.py -v -s
```

Validates complete workflow: S3 → SQS → Processor → DynamoDB + S3

**Coverage:** 100% (53/53 tests passing)

---

## Performance

| Metric | Value |
|--------|-------|
| **Processing Time** | 1.0-2.4s per ticket |
| **Throughput** | Up to 60 tickets/minute |
| **Model Load Time** | 5-10s (one-time startup) |
| **Memory Usage** | <2 GB per worker |
| **Model Size** | 592 MB total (3 models) |
| **Package Size** | ~2+ GB (with PyTorch) |

### Breakdown

| Stage | Time | Percentage |
|-------|------|------------|
| Summarization (DistilBART) | ~500ms | 50% |
| Embedding (MiniLM) | ~300ms | 30% |
| Classification (all) | ~200ms | 20% |

---

## Documentation

- **This README** - Package documentation and build recipes
- **[PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)** - Complete project overview
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture
- **[IMAGELESS_K8S.md](docs/IMAGELESS_K8S.md)** - Kubernetes deployment
- **Phase Summaries** - Implementation details by phase

---

## License

MIT License

---

## Links

- **Flox Documentation:** https://flox.dev/docs
- **FloxHub Generator:** https://hub.flox.dev/flox/reinvent-demo-ticket-generator
- **FloxHub Processor:** https://hub.flox.dev/flox/reinvent-demo-ticket-processor
- **LocalStack:** https://docs.localstack.cloud
- **HuggingFace Models:** https://huggingface.co/models

---

*Built for AWS re:Invent 2025 | Demonstrating Flox environment composition and imageless Kubernetes deployment*
