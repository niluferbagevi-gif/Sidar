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
    "uv pip install torch torchvision " f"--index-url {PYTORCH_RECOMMENDED_CUDA_INDEX_URL}"
)


def gpu_mixed_precision_default() -> bool:
    """Return the profile-aware FP16 default for GPU-backed production workloads."""
    return os.getenv("SIDAR_ENV", "").strip().lower() == "production"
