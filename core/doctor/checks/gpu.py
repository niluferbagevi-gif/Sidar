"""
GPU readiness check for Sidar doctor.

This module provides a simple GPU availability check using PyTorch. If PyTorch
is not installed or a CUDA device is unavailable, the check returns a warning.
"""

from __future__ import annotations

from core.doctor import DoctorCheck


def check_gpu() -> DoctorCheck:
    """
    Perform a basic GPU availability check.

    Returns:
        DoctorCheck: with name 'gpu', status 'pass' when CUDA is available,
        'warn' otherwise. Details include cuda availability and device count.
    """
    try:
        import torch  # type: ignore
        cuda_available = torch.cuda.is_available()
        device_count = torch.cuda.device_count() if cuda_available else 0
    except Exception as exc:
        # If torch is missing or another exception occurs, skip GPU detection.
        return DoctorCheck(
            "gpu",
            "warn",
            "GPU check failed; falling back to CPU",
            {"error": str(exc)},
        )

    status = "pass" if cuda_available else "warn"
    message = (
        "GPU is available"
        if cuda_available
        else "GPU not available; CPU fallback will be used"
    )
    return DoctorCheck(
        "gpu",
        status,
        message,
        {"cuda_available": cuda_available, "device_count": device_count},
    )
