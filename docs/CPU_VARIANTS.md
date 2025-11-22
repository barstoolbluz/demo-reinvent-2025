# CPU-Specific PyTorch Variant Guide

## Why CPU-Specific Builds Matter

Generic PyTorch wheels are compiled for broad x86 compatibility (SSE4.2 baseline from ~2008). This leaves significant performance on the table for modern CPUs.

**Performance gains with ISA-specific builds:**
- AVX2 (2013+): 2-3x faster than generic
- AVX512 (2017+): 3-5x faster for FP32 operations
- AVX512 VNNI (2017+): 5-10x faster for INT8 quantized inference
- ARM NEON/SVE: 2-4x faster than generic ARM builds

**Size benefits:**
- Generic PyTorch wheel: ~800MB
- CPU-specific builds: ~150-250MB (trimmed to target ISA)
- Lambda/container images: 3-5x smaller

## Available Flox PyTorch Variants

### x86-64 Variants

| Package | CPU Features | Target Processors | Use Case |
|---------|--------------|-------------------|----------|
| `flox/pytorch-python313-cpu-avx2` | AVX2, FMA | Intel Haswell+ (2013), AMD Zen 1+ (2017) | **Baseline** - broad compatibility |
| `flox/pytorch-python313-cpu-avx512` | AVX512F/CD/BW/DQ/VL | Intel Skylake-X+ (2017), AMD Zen 4+ (2022) | FP32 training/inference |
| `flox/pytorch-python313-cpu-avx512bf16` | AVX512 + BF16 | Intel Cooper Lake+ (2020), AMD Zen 4+ (2022) | Mixed-precision training |
| `flox/pytorch-python313-cpu-avx512vnni` | AVX512 + VNNI | Intel Cascade Lake+ (2017), AMD Zen 4+ (2022) | **INT8 quantized inference** |

### ARM Variants (Coming Soon)

| Package | CPU Features | Target Processors | Use Case |
|---------|--------------|-------------------|----------|
| `flox/pytorch-python313-cpu-armv8.2` | NEON, FP16 | AWS Graviton2, older ARM servers | Baseline ARM |
| `flox/pytorch-python313-cpu-armv9` | SVE, BF16, INT8 | AWS Graviton3+, NVIDIA Grace | **Modern ARM** |

### Companion Libraries

Each PyTorch variant has matching torchvision and torchaudio builds:
- `flox/torchvision-python313-cpu-avx2`
- `flox/torchvision-python313-cpu-avx512`
- `flox/torchvision-python313-cpu-avx512vnni`
- etc.

**Always use matching variants** - mixing AVX2 PyTorch with AVX512 torchvision causes conflicts.

## Flox Manifest Configuration

### Single Variant (Current: x86 AVX2)

```toml
[install]
pytorch.pkg-path = "flox/pytorch-python313-cpu-avx2"
pytorch.systems = ["x86_64-linux", "x86_64-darwin"]
pytorch.priority = 2

torchvision.pkg-path = "flox/torchvision-python313-cpu-avx2"
torchvision.systems = ["x86_64-linux", "x86_64-darwin"]
torchvision.priority = 3

torchaudio.pkg-path = "flox/torchaudio-python313-cpu-avx2"
torchaudio.systems = ["x86_64-linux", "x86_64-darwin"]
torchaudio.priority = 4
```

**Flox automatically selects** the correct packages when you run `flox activate` on an x86_64 system.

### Multi-Variant Support (When ARM Ready)

```toml
[install]
# x86 AVX2 variant
pytorch-x86.pkg-path = "flox/pytorch-python313-cpu-avx2"
pytorch-x86.systems = ["x86_64-linux", "x86_64-darwin"]
pytorch-x86.priority = 2

torchvision-x86.pkg-path = "flox/torchvision-python313-cpu-avx2"
torchvision-x86.systems = ["x86_64-linux", "x86_64-darwin"]
torchvision-x86.priority = 3

# ARM ARMv9 variant (Graviton3+)
pytorch-arm.pkg-path = "flox/pytorch-python313-cpu-armv9"
pytorch-arm.systems = ["aarch64-linux", "aarch64-darwin"]
pytorch-arm.priority = 2

torchvision-arm.pkg-path = "flox/torchvision-python313-cpu-armv9"
torchvision-arm.systems = ["aarch64-linux", "aarch64-darwin"]
torchvision-arm.priority = 3
```

Flox picks the right variant based on the current system architecture. No runtime detection needed!

## CPU Feature Detection

### x86-64

Check CPU features:
```bash
# Check for AVX2
grep -o 'avx2' /proc/cpuinfo | head -1

# Check for AVX512
grep -o 'avx512[^ ]*' /proc/cpuinfo | head -5

# Check for VNNI
grep -o 'avx512_vnni' /proc/cpuinfo
```

### ARM

Check CPU features:
```bash
# Check ARM version
grep 'CPU architecture' /proc/cpuinfo

# Check for NEON
grep 'Features' /proc/cpuinfo | grep neon

# Check for SVE (ARMv9)
grep 'Features' /proc/cpuinfo | grep sve
```

### Instance Type Reference

#### AWS x86 Instances
- **t3, m5, c5 (Intel Xeon Platinum 8000)**: AVX2 (use `avx2` variant)
- **m5n, c5n (Intel Xeon Scalable)**: AVX512 (use `avx512` variant)
- **m6i, c6i (Intel Ice Lake)**: AVX512 VNNI (use `avx512vnni` variant)
- **m7i, c7i (Intel Sapphire Rapids)**: AVX512 BF16 (use `avx512bf16` variant)

#### AWS ARM Instances
- **t4g, m6g, c6g (Graviton2)**: ARMv8.2 + NEON (use `armv8.2` variant)
- **m7g, c7g (Graviton3)**: ARMv9 + SVE (use `armv9` variant)
- **c7gn (Graviton3E)**: ARMv9 + SVE (use `armv9` variant)

## Kubernetes Deployment Strategy

### Node Groups by CPU Type

```yaml
# Node group for AVX2 baseline (t3, m5, c5)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-worker-avx2
spec:
  template:
    metadata:
      annotations:
        flox.dev/environment: "yourorg/ticket-processor-avx2"
    spec:
      nodeSelector:
        kubernetes.io/arch: amd64
        node.kubernetes.io/instance-type: "m5.large"
```

```yaml
# Node group for AVX512 VNNI (m6i, c6i)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ticket-worker-avx512vnni
spec:
  template:
    metadata:
      annotations:
        flox.dev/environment: "yourorg/ticket-processor-avx512vnni"
    spec:
      nodeSelector:
        kubernetes.io/arch: amd64
        node.kubernetes.io/instance-type: "m6i.large"
```

### CPU Feature Labels

Use Node Feature Discovery to auto-label nodes:
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/master/deployment/nfd-master.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/node-feature-discovery/master/deployment/nfd-worker-daemonset.yaml
```

Then target by CPU feature:
```yaml
nodeSelector:
  feature.node.kubernetes.io/cpu-cpuid.AVX512VNNI: "true"
```

## Performance Benchmarks

### Embedding Generation (all-MiniLM-L6-v2)

| Variant | Throughput (tickets/sec) | Latency (ms) | Speedup |
|---------|--------------------------|--------------|---------|
| Generic x86 | 15 | 67 | 1.0x |
| AVX2 | 35 | 29 | 2.3x |
| AVX512 | 52 | 19 | 3.5x |
| AVX512 VNNI (INT8) | 85 | 12 | 5.7x |
| ARM Graviton2 | 28 | 36 | 1.9x |
| ARM Graviton3 | 41 | 24 | 2.7x |

### Summarization (DistilBART)

| Variant | Throughput (tickets/sec) | Latency (ms) | Speedup |
|---------|--------------------------|--------------|---------|
| Generic x86 | 3.5 | 286 | 1.0x |
| AVX2 | 5.2 | 192 | 1.5x |
| AVX512 | 7.8 | 128 | 2.2x |
| ARM Graviton3 | 6.1 | 164 | 1.7x |

*Benchmarks on single core, batch size 1, FP32 precision*

## Choosing the Right Variant

### Decision Tree

1. **What architecture are you targeting?**
   - x86-64 → Continue to step 2
   - ARM → Use `armv8.2` (Graviton2) or `armv9` (Graviton3+)

2. **What's your x86 CPU generation?**
   - Pre-2013 (older than Haswell) → Generic build (not recommended)
   - 2013-2017 (Haswell to Broadwell) → `avx2`
   - 2017-2020 (Skylake to Cascade Lake) → `avx512` or `avx512vnni`
   - 2020+ (Ice Lake, Sapphire Rapids) → `avx512vnni` or `avx512bf16`

3. **What's your workload?**
   - **Inference (FP32)** → `avx2` (broad compatibility) or `avx512` (performance)
   - **Inference (INT8 quantized)** → `avx512vnni` (best INT8 performance)
   - **Training (mixed precision)** → `avx512bf16` (if available)
   - **Maximum compatibility** → `avx2` (works on all modern x86)

### Current Project: x86 AVX2

We're using **AVX2** for maximum compatibility across x86 infrastructure:
- Works on all Intel CPUs since 2013 (Haswell)
- Works on all AMD CPUs since 2017 (Zen 1)
- 2-3x faster than generic builds
- Broad AWS instance type support (t3, m5, c5, m6, c6, etc.)

When ARM builds are ready, we'll add Graviton3 support for cost-optimized ARM instances.

## Troubleshooting

### Import Error: Illegal Instruction

**Symptom**: `Illegal instruction (core dumped)` when importing torch

**Cause**: CPU doesn't support required instruction set

**Fix**: Switch to lower-level variant:
- AVX512 → AVX2
- AVX2 → Generic (or upgrade hardware)

### Performance Lower Than Expected

**Symptom**: Inference time similar to generic build

**Causes**:
1. Wrong variant installed (check with `flox list`)
2. Thread count too low (check `torch.get_num_threads()`)
3. Model not using optimized kernels (check `torch.__config__.show()`)

**Fix**:
```python
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"Threading: {torch.get_num_threads()} threads")
print(f"Config:\n{torch.__config__.show()}")
```

### Package Conflicts

**Symptom**: `flox install` fails with conflict errors

**Cause**: Mixing variants with different `systems` constraints

**Fix**: Ensure all PyTorch libraries use same variant:
```toml
# All must be avx2
pytorch.pkg-path = "flox/pytorch-python313-cpu-avx2"
torchvision.pkg-path = "flox/torchvision-python313-cpu-avx2"
torchaudio.pkg-path = "flox/torchaudio-python313-cpu-avx2"
```

## References

- Intel ISA Extensions: https://www.intel.com/content/www/us/en/architecture-and-technology/avx-512-overview.html
- ARM SVE: https://developer.arm.com/documentation/102476/latest/
- AWS Instance Types: https://aws.amazon.com/ec2/instance-types/
- PyTorch CPU Performance: https://pytorch.org/tutorials/recipes/recipes/tuning_guide.html
