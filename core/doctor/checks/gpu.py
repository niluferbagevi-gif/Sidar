"""GPU-related Doctor checks."""

from __future__ import annotations

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_gpu_memory_config() -> DoctorCheck:
    return _doctor.check_gpu_memory_config()


def check_docker_test_image() -> DoctorCheck:
    return _doctor.check_docker_test_image()


def check_gpu() -> DoctorCheck:
    return _doctor.check_gpu()


__all__ = ["check_docker_test_image", "check_gpu", "check_gpu_memory_config"]
