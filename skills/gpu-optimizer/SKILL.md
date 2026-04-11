---
name: gpu-optimizer
description: 'GPU optimization for consumer NVIDIA GPUs (8-24GB VRAM) covering mixed precision, gradient checkpointing, XGBoost GPU, CuPy/cuDF migration, and torch.compile. Triggers on: "optimize GPU training", "speed up CUDA", "reduce OOM", "migrate NumPy to CuPy", "manage GPU memory", "benchmark PyTorch".'
metadata:
  version: 1.1.1
  category: data
  tags: [gpu, cuda, vram, pytorch]
  difficulty: advanced
  phase: build
---

# GPU Optimizer

Expert GPU optimization for consumer GPUs with 8–24GB VRAM. Evidence-based patterns only.

## Hardware Profile

Fill in your hardware before applying optimizations:

| Property          | Your Value                                       |
| ----------------- | ------------------------------------------------ |
| GPU model         | (e.g., RTX 4080 Mobile, RTX 3090, RTX 4090)      |
| VRAM              | (e.g., 12GB, 16GB, 24GB)                         |
| CUDA version      | (`nvidia-smi` → top-right)                       |
| TDP / power limit | (laptop vs desktop affects sustained throughput) |
| Driver version    | (`nvidia-smi` → top-left)                        |

Key constraint: VRAM capacity determines which strategies apply. Patterns below are annotated with minimum VRAM requirements where relevant.

## Optimization Categories

### 1. XGBoost GPU Acceleration

**DMatrix vs QuantileDMatrix:**

```python
# GPU-optimized: QuantileDMatrix is 1.8x faster
dtrain = xgb.QuantileDMatrix(X_train.astype(np.float32))
dval = xgb.QuantileDMatrix(X_val.astype(np.float32))

# Standard: DMatrix (use for inference only)
dtest = xgb.DMatrix(X_test.astype(np.float32))
```

**Critical Parameters:**

```python
params = {
    'tree_method': 'hist',        # GPU-accelerated histogram
    'device': 'cuda:0',           # Explicit GPU device
    'max_bin': 256,               # Higher bins = better splits (VRAM permitting)
    'grow_policy': 'depthwise',   # vs 'lossguide' for imbalanced data
    'predictor': 'gpu_predictor', # GPU inference
}

# Training with explicit device
model = xgb.train(params, dtrain, num_boost_round=100)
```

**GPU Verification (fail-fast):**

```python
def verify_gpu():
    """Verify XGBoost GPU availability. Raises if unavailable."""
    import subprocess
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("nvidia-smi failed - no GPU available")
    except FileNotFoundError:
        raise RuntimeError("nvidia-smi not found - no GPU available")

    build_info = xgb.build_info()
    if not build_info.get("USE_CUDA"):
        raise RuntimeError("XGBoost not compiled with CUDA support")
```

**Memory Management:**

```python
# Single-pass training (reuse QuantileDMatrix across slots)
dtrain = xgb.QuantileDMatrix(X_train.astype(np.float32))
for slot_idx in range(num_slots):
    dtrain.set_label(y_train[:, slot_idx])  # Reuse matrix
    model = xgb.train(params, dtrain, num_boost_round=100)
```

### 2. PyTorch Mixed Precision

**BF16 (preferred) vs FP16:**

```python
from torch.amp import autocast, GradScaler

# Auto-detect best precision
if torch.cuda.is_bf16_supported():
    amp_dtype = torch.bfloat16  # Ampere+ GPUs support BF16
else:
    amp_dtype = torch.float16

# Training step
scaler = GradScaler('cuda') if amp_dtype == torch.float16 else None

with autocast('cuda', dtype=amp_dtype):
    output = model(input_ids, attention_mask)
    loss = criterion(output, targets)

# Backward with scaling (FP16 only)
if scaler:
    scaler.scale(loss).backward()
    scaler.step(optimizer)
    scaler.update()
else:
    loss.backward()
    optimizer.step()
```

**Why BF16 > FP16:**

- Same exponent range as FP32 (no overflow/underflow)
- No GradScaler needed (simpler code)
- Ampere and later GPUs have native BF16 Tensor cores

### 3. VRAM Management

**Gradient Checkpointing:**

```python
# Saves ~40% VRAM, adds ~20% compute time
model.gradient_checkpointing_enable()

# For transformers:
model.base_model.model.gradient_checkpointing_enable()
```

**VRAM Monitoring:**

```python
import torch

torch.cuda.reset_peak_memory_stats()
# ... training ...
peak_vram_gb = torch.cuda.max_memory_allocated() / 1024**3
print(f"Peak VRAM: {peak_vram_gb:.2f} GB")

# Clear cache between experiments
torch.cuda.empty_cache()
```

**Gradient Accumulation:**

```python
# Simulate larger batch size without OOM
grad_accum_steps = max(1, target_batch_size // actual_batch_size)

for i, batch in enumerate(dataloader):
    loss = model(batch) / grad_accum_steps
    loss.backward()

    if (i + 1) % grad_accum_steps == 0:
        optimizer.step()
        optimizer.zero_grad()
```

**DoE for VRAM Optimization:**

```python
EXPERIMENTS = [
    {"batch_size": 2,  "seq_len": 128, "grad_ckpt": True,  "amp": "bf16"},
    {"batch_size": 4,  "seq_len": 256, "grad_ckpt": True,  "amp": "bf16"},
    {"batch_size": 8,  "seq_len": 512, "grad_ckpt": False, "amp": "bf16"},
    {"batch_size": 16, "seq_len": 256, "grad_ckpt": False, "amp": "bf16"},
]
```

### 4. Aggressive Vectorization

**Tensor Lookups (not Python loops):**

```python
# Slow: Python loop
for i, token_id in enumerate(input_ids):
    type_id = token_to_type[token_id]
    embeddings[i] = type_embeddings[type_id]

# Fast: Vectorized
type_ids = token_to_type[input_ids]  # Broadcast lookup
embeddings = type_embeddings[type_ids]  # Single GPU kernel
```

**Registered Buffers (persistent GPU data):**

```python
class Model(nn.Module):
    def __init__(self):
        super().__init__()
        # Build lookup tensors once
        type_ids = torch.zeros(vocab_size, dtype=torch.long)
        self.register_buffer('_type_ids', type_ids)  # Stays on GPU

    def forward(self, input_ids):
        return self._type_ids[input_ids]  # Vectorized lookup
```

**Batch Operations:**

```python
# Slow: Per-sample processing
outputs = [model(x.unsqueeze(0)) for x in batch]

# Fast: Batched
outputs = model(batch)  # Single forward pass
```

### 5. CuPy Migration (NumPy → GPU)

**When to Use CuPy:**

- Large array operations (>1M elements)
- Repeated NumPy calls in tight loops
- Preprocessing pipelines before PyTorch/XGBoost

**Migration Pattern:**

```python
import cupy as cp
import numpy as np

# NumPy (CPU)
x = np.random.randn(10000, 1000)
y = np.dot(x, x.T)

# CuPy (GPU) - SAME API
x_gpu = cp.random.randn(10000, 1000)
y_gpu = cp.dot(x_gpu, x_gpu.T)

# Transfer back if needed
y_cpu = cp.asnumpy(y_gpu)
```

**Interop with PyTorch:**

```python
# CuPy → PyTorch (zero-copy)
x_cupy = cp.random.randn(1000, 1000)
x_torch = torch.as_tensor(x_cupy, device='cuda')

# PyTorch → CuPy (zero-copy)
x_torch = torch.randn(1000, 1000, device='cuda')
x_cupy = cp.asarray(x_torch)
```

**Install:**

```bash
uv pip install cupy-cuda12x  # For CUDA 12.x
```

### 6. cuDF Migration (Pandas → GPU)

**When to Use cuDF:**

- DataFrames >1GB
- Groupby/aggregation on large data
- ETL pipelines before model training

**Migration Pattern:**

```python
import cudf
import pandas as pd

# Pandas (CPU)
df = pd.read_csv('large.csv')
grouped = df.groupby('category')['value'].mean()

# cuDF (GPU) - SAME API
df_gpu = cudf.read_csv('large.csv')
grouped_gpu = df_gpu.groupby('category')['value'].mean()

# Transfer back
grouped_cpu = grouped_gpu.to_pandas()
```

**XGBoost Integration:**

```python
import cudf
import xgboost as xgb

# Load data on GPU
df = cudf.read_csv('train.csv')
X = df[feature_cols]
y = df['target']

# Create DMatrix directly from cuDF (no CPU copy)
dtrain = xgb.DMatrix(X, label=y)
```

**Install:**

```bash
# RAPIDS (includes cuDF, cuML, cuGraph)
uv pip install cudf-cu12 --extra-index-url=https://pypi.nvidia.com
```

### 7. PyTorch Compilation & Optimization

**Fused Optimizer:**

```python
# Check availability
use_fused = (
    torch.cuda.is_available()
    and "fused" in torch.optim.AdamW.__init__.__code__.co_varnames
)

optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=1e-3,
    fused=use_fused,  # Single GPU kernel (2-3x faster)
)
```

**Torch Compile:**

```python
# PyTorch 2.0+ compile
if hasattr(torch, "compile"):
    model = torch.compile(model, mode="reduce-overhead")
```

**cuDNN Benchmarking:**

```python
# Auto-tune kernels (slower startup, faster training)
torch.backends.cudnn.benchmark = True

# Disable for determinism
torch.backends.cudnn.deterministic = True
```

### 8. Advanced Loss Functions

**Weighted Slot Loss:**

```python
class WeightedSlotLoss(nn.Module):
    def __init__(self, slot_weights):
        super().__init__()
        self.slot_weights = torch.tensor(slot_weights)

    def forward(self, logits_list, targets):
        weighted_losses = []
        for i, logits in enumerate(logits_list):
            loss = F.cross_entropy(logits, targets[:, i])
            weighted_losses.append(loss * self.slot_weights[i])
        return torch.stack(weighted_losses).sum() / self.slot_weights.sum()
```

**Focal Loss (hard example mining):**

```python
class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0):
        super().__init__()
        self.gamma = gamma

    def forward(self, logits, targets):
        ce_loss = F.cross_entropy(logits, targets, reduction='none')
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma) * ce_loss
        return focal_loss.mean()
```

### 9. Caching & Precomputation

**Position Embedding Cache:**

```python
class Model(nn.Module):
    def __init__(self):
        super().__init__()
        self._pos_cache = {}  # {seq_len: positions}

    def forward(self, x):
        T = x.size(1)
        if T not in self._pos_cache:
            self._pos_cache[T] = torch.arange(T, device=x.device)
            # Limit cache size
            if len(self._pos_cache) > 10:
                self._pos_cache.pop(next(iter(self._pos_cache)))
        return self.pos_embed(self._pos_cache[T])
```

**Attention Mask Cache:**

```python
def _create_causal_mask(self, T, device):
    if T not in self._mask_cache:
        mask = torch.triu(torch.ones(T, T), diagonal=1).bool()
        self._mask_cache[T] = mask.to(device)
    return self._mask_cache[T]
```

## Quick Diagnostics

**Check GPU Utilization:**

```bash
watch -n 1 nvidia-smi  # Monitor in real-time
```

**Profile PyTorch:**

```python
with torch.profiler.profile(
    activities=[torch.profiler.ProfilerActivity.GPU],
    with_stack=True,
) as prof:
    model(batch)

print(prof.key_averages().table(sort_by="cuda_time_total"))
```

**Bottleneck Detection:**

```python
import torch.utils.bottleneck as bottleneck
bottleneck.main(['script.py'])
```

## Migration Checklist

- [ ] **XGBoost**: Use `QuantileDMatrix`, set `device='cuda:0'`
- [ ] **PyTorch**: Enable BF16/FP16, fused optimizer, torch.compile
- [ ] **VRAM**: Gradient checkpointing if approaching VRAM limit
- [ ] **NumPy→CuPy**: For preprocessing >1M elements
- [ ] **Pandas→cuDF**: For DataFrames >1GB
- [ ] **Vectorization**: Replace Python loops with tensor ops
- [ ] **Caching**: Precompute positions, masks, embeddings
- [ ] **Monitor**: Track VRAM usage, profile GPU kernels

## Anti-Patterns

**Avoid:**

- Using `.cpu()` in training loop (kills GPU pipeline)
- Creating tensors on CPU then moving to GPU (create on GPU directly)
- Using Python loops over tensors (vectorize)
- Ignoring VRAM monitoring (leads to OOM crashes)
- Using FP32 when BF16/FP16 works (wastes bandwidth)
- Calling `torch.cuda.synchronize()` unnecessarily (breaks async)

## References

**Documentation:**

- XGBoost GPU: https://xgboost.readthedocs.io/en/stable/gpu/
- PyTorch AMP: https://pytorch.org/docs/stable/amp.html
- CuPy: https://docs.cupy.dev/en/stable/
- cuDF: https://docs.rapids.ai/api/cudf/stable/

## Error Handling

- CUDA not available at runtime: run `nvidia-smi` first to confirm the GPU is visible; if the command fails, verify driver installation with `sudo nvidia-smi` or reinstall drivers before proceeding.
- XGBoost raises `RuntimeError: XGBoost not compiled with CUDA support`: install the CUDA build via `uv pip install xgboost` from a CUDA-enabled environment, or build from source with `-DUSE_CUDA=ON`.
- OOM during training: reduce batch size first (halve it), then enable gradient checkpointing; if OOM persists after both, enable gradient accumulation to simulate the original batch size.
- CuPy import failure (`ImportError` or version mismatch): verify CUDA toolkit version with `nvcc --version` and install the matching CuPy wheel (e.g., `cupy-cuda12x` for CUDA 12.x).
- cuDF install fails or produces CUDA version errors: use the NVIDIA PyPI index (`--extra-index-url=https://pypi.nvidia.com`) and match the `cudf-cu12` suffix to your CUDA major version.
- `torch.compile` produces incorrect results or crashes: disable with `model = model` (no compile) to isolate; known to fail on some custom ops — fall back to eager mode for those layers.

## Limitations

- NVIDIA GPUs only — AMD (ROCm) and Intel Arc GPUs are not covered by these patterns.
- Assumes a single-GPU setup; multi-GPU (DDP, FSDP) requires additional configuration not covered here.
- Patterns are calibrated for consumer GPUs (8–24GB VRAM); datacenter GPUs (A100, H100) have different memory hierarchies and may benefit from different strategies.
- Framework coverage: PyTorch, XGBoost, and RAPIDS (CuPy/cuDF) only — JAX, TensorFlow, and MXNet are out of scope.
- Laptop GPU TDP limits sustained throughput; power-throttled performance can differ significantly from desktop benchmarks even at the same VRAM capacity.

## Output Format

Each optimization recommendation includes a before/after code pair showing the original pattern and the GPU-optimized equivalent.
Performance gain estimates are provided as ranges (e.g., "1.8x faster", "~40% VRAM reduction") based on typical consumer GPU benchmarks — actual gains depend on workload and hardware.
Where a change introduces a trade-off (e.g., gradient checkpointing adds compute time), the trade-off is stated explicitly inline.
