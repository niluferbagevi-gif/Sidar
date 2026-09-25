"""GPU/CUDA configuration constants and hardware-profile helpers."""

from __future__ import annotations

import os

from core import config_gpu_detect

HardwareInfo = config_gpu_detect.HardwareInfo
detect_gpu = config_gpu_detect.detect_gpu
normalize_gpu_memory_fractions = config_gpu_detect.normalize_gpu_memory_fractions
resolve_adaptive_gpu_pool_size = config_gpu_detect.resolve_adaptive_gpu_pool_size

PYTORCH_STABLE_CUDA_WHEEL_TAGS: tuple[str, ...] = ("cu128", "cu126", "cu124")
PYTORCH_RECOMMENDED_CUDA_WHEEL_TAG: str = PYTORCH_STABLE_CUDA_WHEEL_TAGS[0]
PYTORCH_RECOMMENDED_CUDA_INDEX_URL: str = (
    f"https://download.pytorch.org/whl/{PYTORCH_RECOMMENDED_CUDA_WHEEL_TAG}"
)
PYTORCH_RECOMMENDED_CUDA_INSTALL_COMMAND: str = (
    f"uv pip install torch torchvision --index-url {PYTORCH_RECOMMENDED_CUDA_INDEX_URL}"
)


def gpu_mixed_precision_default() -> bool:
    """Return the profile-aware FP16 default for GPU-backed production workloads."""
    return os.getenv("SIDAR_ENV", "").strip().lower() == "production"


def ollama_coding_ctx_for_vram(gpu_vram_mb: int) -> int:
    """Return the auto-tuned Ollama coding context window for the detected VRAM.

    Below 8 GiB this used to fall through untouched, leaving LLMClientSettings'
    fixed 8192 default in place for 6 GB-class cards (RTX 2060/3050, 4060 laptop,
    GTX 1660, ...) — the same context a 8-16 GiB card gets, with none of its VRAM
    headroom.

    A field report (RTX 3070 Ti Laptop, gpu_vram_mb=8192) then showed the >=8192
    tier itself has the identical problem: a card that reports *exactly* the tier
    floor gets that tier's full context with zero margin for the coding model's own
    weights (~5 GiB for qwen2.5-coder:7b q4) plus KV cache plus OS/desktop VRAM
    overhead, and the installer's `/api/generate` JSON smoke test failed with HTTP
    500 (VRAM OOM). 8-12 GiB cards (no comfortable headroom over a ~5 GiB model)
    now get the same 4096 tier as 4-8 GiB cards; only 12 GiB+ cards (RTX 3060 12GB,
    4070, 3080 10-12GB, ...) keep the full 8192 window. 16 GiB+ still gets 16384.
    Floor at 2048 for anything below 4 GiB (including gpu_vram_mb=0, i.e. USE_GPU
    forced on without a successful hardware probe) — 2048 mirrors
    OLLAMA_BATCH_POLICY's own auto_min, the smallest context this codebase already
    treats as meaningful for local Ollama inference.
    """
    if gpu_vram_mb >= 16384:
        return 16384
    if gpu_vram_mb >= 12288:
        return 8192
    if gpu_vram_mb >= 4096:
        return 4096
    return 2048
