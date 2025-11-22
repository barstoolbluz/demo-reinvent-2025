# Publishing to Flox Catalog Guide

This guide explains how to build and publish the `ticket-processor` package to the Flox catalog.

---

## Table of Contents

1. [Overview](#overview)
2. [Package Structure](#package-structure)
3. [Building the Package](#building-the-package)
4. [Testing the Package](#testing-the-package)
5. [Publishing to Catalog](#publishing-to-catalog)
6. [Using the Published Package](#using-the-published-package)
7. [CPU-Specific Variants](#cpu-specific-variants)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The `ticket-processor` is packaged as a Nix derivation that can be:
- Built locally with `flox build`
- Published to the Flox catalog with `flox publish`
- Installed in any Flox environment
- Deployed to Kubernetes as an imageless workload

**Package Details**:
- **Name**: `ticket-processor`
- **Version**: `0.1.0`
- **Type**: Python application (Python 3.13)
- **Dependencies**: 592 MB ML models + Python libs
- **Executable**: `ticket-processor` command

---

## Package Structure

### Files

```
.flox/pkgs/
└── ticket-processor.nix       # Nix expression defining the package

pyproject.toml                   # Python package metadata
README.md                        # Project documentation

src/
├── common/                      # Shared utilities
│   ├── aws_clients.py
│   ├── config.py
│   └── schemas.py
└── processor/                   # ML processor
    ├── models.py
    ├── embeddings.py
    ├── classifier.py
    ├── summarizer.py
    └── worker.py
```

### Nix Expression Structure

The Nix expression (`.flox/pkgs/ticket-processor.nix`) defines:

1. **Python Environment**: `python313.withPackages` with all dependencies
2. **Source Selection**: Uses `lib.sourceByRegex` to include only necessary files
3. **Install Phase**:
   - Copies Python source to `$out/lib/python3.13/site-packages`
   - Creates executable wrapper at `$out/bin/ticket-processor`
4. **Metadata**: Description, homepage, license, platforms

---

## Building the Package

### Method 1: Using Make

```bash
make build
```

This runs `scripts/build-package.sh` which validates and builds the package.

### Method 2: Using Flox Directly

```bash
flox build .#ticket-processor
```

### Method 3: Manual Nix Build

```bash
nix-build -E 'with import <nixpkgs> {}; callPackage .flox/pkgs/ticket-processor.nix {}'
```

### Build Output

Successful build produces:
```
/nix/store/<hash>-ticket-processor-0.1.0/
├── bin/
│   └── ticket-processor          # Executable
└── lib/
    └── python3.13/
        └── site-packages/
            └── src/              # Python source code
```

---

## Testing the Package

### 1. Test Local Build

After building, test the executable:

```bash
# Check executable exists
ls -lh result/bin/ticket-processor

# Test help/version (if implemented)
./result/bin/ticket-processor --help
```

### 2. Test in Clean Environment

```bash
# Create temporary test environment
flox init test-ticket-processor
cd test-ticket-processor

# Add the package
flox install ticket-processor

# Activate and test
flox activate
ticket-processor --help
```

### 3. Integration Test

Test with LocalStack:

```bash
# Start LocalStack
flox services start

# Initialize resources
make setup

# Seed test data
make seed

# Run worker (should process tickets)
ticket-processor
```

Expected behavior:
- Preloads ML models (~6-10s)
- Connects to LocalStack (SQS, S3, DynamoDB)
- Polls SQS queue
- Processes any available tickets
- Stores enriched data

---

## Publishing to Catalog

### Prerequisites

1. **Flox Account**: Sign up at https://flox.dev
2. **Authentication**: `flox auth login`
3. **Catalog Access**: Request publish permissions from Flox team
4. **Tested Build**: Ensure package builds and runs successfully

### Publishing Process

#### Step 1: Prepare for Publishing

```bash
# Ensure clean build
make build

# Run all tests
make test
pytest tests/unit tests/integration -v

# Verify no uncommitted changes
git status
```

#### Step 2: Publish to Catalog

```bash
# Publish the package
flox publish .#ticket-processor
```

This will:
1. Build the package
2. Run package validation checks
3. Upload to Flox catalog
4. Make available for installation

#### Step 3: Verify Publication

```bash
# Search for the package
flox search ticket-processor

# View package info
flox show ticket-processor
```

### Publication Metadata

The catalog entry will include:
- Package name: `ticket-processor`
- Version: `0.1.0`
- Description: "ML-powered support ticket enrichment processor"
- Dependencies: Automatically extracted from Nix expression
- Platforms: `x86_64-linux`, `x86_64-darwin` (initially)
- License: MIT

---

## Using the Published Package

### In a Flox Environment

Once published, anyone can install it:

```bash
# Create new environment
flox init my-project

# Install ticket-processor
flox install ticket-processor

# Activate environment
flox activate

# Run the processor
ticket-processor
```

### In manifest.toml

```toml
[install]
ticket-processor.pkg-path = "ticket-processor"

# Configure via environment variables
[vars]
MODEL_CACHE_DIR = "$FLOX_ENV_CACHE/models"
USE_LOCALSTACK = "true"
AWS_ENDPOINT_URL = "http://localhost:4566"
SQS_QUEUE_NAME = "ticket-processing-queue"
```

---

## CPU-Specific Variants

The current package uses generic PyTorch builds. For production, create CPU-optimized variants:

### Creating AVX2 Variant

```nix
# .flox/pkgs/ticket-processor-avx2.nix
{
  lib,
  python313,
  python313Packages,
  stdenv,
}: let
  # Use AVX2-optimized PyTorch
  pythonEnv = python313.withPackages (ps: with ps; [
    # ... other deps ...
    pytorch-cpu-avx2  # AVX2-optimized build
  ]);

in stdenv.mkDerivation {
  pname = "ticket-processor-avx2";
  # ... rest same as ticket-processor.nix ...
}
```

### System Constraints

In `manifest.toml`:

```toml
[install]
ticket-processor-avx2.pkg-path = "ticket-processor-avx2"
ticket-processor-avx2.systems = ["x86_64-linux"]

# Only use if AVX2 available
[options]
systems = ["x86_64-linux"]
```

### Planned Variants

| Variant | Target | PyTorch Package | Size | Performance |
|---------|--------|-----------------|------|-------------|
| `ticket-processor` | Generic x86/ARM | `pytorch` | 592 MB | Baseline |
| `ticket-processor-avx2` | x86 AVX2 | `pytorch-cpu-avx2` | 600 MB | 1.5-2x faster |
| `ticket-processor-avx512` | x86 AVX512 | `pytorch-cpu-avx512` | 620 MB | 2-3x faster |
| `ticket-processor-arm` | ARM64 | `pytorch-arm64` | 580 MB | Baseline |

---

## Troubleshooting

### Build Fails: Missing Dependencies

**Error**: `attribute 'sentence-transformers' missing`

**Solution**: Ensure dependency is in nixpkgs or add to Python environment:

```nix
pythonEnv = python313.withPackages (ps: with ps; [
  # If not in ps, build from PyPI
  (ps.buildPythonPackage rec {
    pname = "sentence-transformers";
    version = "2.2.0";
    src = ps.fetchPypi {
      inherit pname version;
      sha256 = "...";
    };
  })
]);
```

### Build Fails: Source Files Not Found

**Error**: `src/ directory not found`

**Solution**: Check `sourceByRegex` pattern in `.flox/pkgs/ticket-processor.nix`:

```nix
src = lib.sourceByRegex ../.. [
  "^src(/.*)?$"        # Include src/ directory and all contents
  "^pyproject\.toml$"
  "^README\.md$"
];
```

### Runtime: ModuleNotFoundError

**Error**: `ModuleNotFoundError: No module named 'src'`

**Solution**: Ensure Python path is set in wrapper:

```bash
# In installPhase
cat > $out/bin/ticket-processor << EOF
#!/usr/bin/env python
import sys
sys.path.insert(0, "$out/lib/python3.13/site-packages")
# ... rest of wrapper ...
EOF
```

### Runtime: Models Not Downloading

**Error**: `Failed to load model: Connection timeout`

**Solution**: Set model cache directory with write permissions:

```bash
export MODEL_CACHE_DIR="$HOME/.cache/models"
export TRANSFORMERS_CACHE="$HOME/.cache/models/transformers"
```

### Publish Fails: Permission Denied

**Error**: `Error: Insufficient permissions to publish`

**Solution**:
1. Contact Flox team to request publish access
2. Verify authentication: `flox auth status`
3. Re-authenticate: `flox auth login`

### Package Not Found After Publishing

**Issue**: Published but `flox search` doesn't find it

**Solution**:
1. Wait 5-10 minutes for catalog indexing
2. Check publication status: `flox publish --status`
3. Verify you're searching correct catalog: `flox catalog list`

---

## Best Practices

### 1. Version Management

Use semantic versioning in `pyproject.toml` and Nix expression:

```toml
# pyproject.toml
version = "0.1.0"  # major.minor.patch
```

```nix
# ticket-processor.nix
let
  version = "0.1.0";
```

Keep both in sync.

### 2. Dependency Pinning

For reproducible builds, pin dependency versions:

```toml
# pyproject.toml
dependencies = [
    "boto3==1.38.32",      # Exact version
    "torch>=2.0.0,<3.0.0", # Version range
]
```

### 3. Testing Before Publishing

**Always run before publishing**:
```bash
# Unit tests
pytest tests/unit -v

# Integration tests
pytest tests/integration -v

# Build test
make build

# Clean environment test
flox init test-env && cd test-env
flox install ../path/to/ticket-processor
flox activate -- ticket-processor --help
```

### 4. Documentation

Include in package:
- `README.md`: Usage instructions
- `pyproject.toml`: Metadata and dependencies
- `docs/`: Detailed documentation
- `examples/`: Usage examples

### 5. Metadata Quality

Provide comprehensive metadata in Nix expression:

```nix
meta = with lib; {
  description = "One-line description";
  longDescription = ''
    Detailed multi-line description.
    Include:
    - What it does
    - Key features
    - Use cases
    - Performance characteristics
  '';
  homepage = "https://github.com/...";
  license = licenses.mit;
  platforms = platforms.linux ++ platforms.darwin;
  maintainers = with maintainers; [ yourname ];
};
```

---

## Next Steps

After publishing `ticket-processor`:

1. **Phase 5: Imageless Kubernetes Deployment**
   - Create K8s manifests with `runtimeClassName: flox`
   - Set up node runtime installation
   - Deploy to EKS

2. **Phase 6: Lambda Container (Optional)**
   - Use `flox containerize` to create container image
   - Deploy to AWS Lambda
   - Configure event sources

3. **Production Optimization**
   - Switch to CPU-specific PyTorch variants (AVX2, AVX512)
   - Implement health checks and monitoring
   - Add horizontal scaling configuration

---

## Resources

- **Flox Documentation**: https://flox.dev/docs
- **Flox Catalog**: https://flox.dev/catalog
- **Nix Package Manual**: https://nixos.org/manual/nixpkgs/stable/
- **Python Packaging**: https://packaging.python.org/

---

**Generated**: 2025-11-21
**Project**: LocalStack ML Workload Demo
**Phase**: 4 - Nix Expression Builds & Packaging
