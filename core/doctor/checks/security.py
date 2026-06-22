"""Security and environment-profile Doctor checks."""

from __future__ import annotations

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_environment_profile() -> DoctorCheck:
    return _doctor.check_environment_profile()


__all__ = ["check_environment_profile"]
