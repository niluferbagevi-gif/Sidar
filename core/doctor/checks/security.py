"""
Security checks for Sidar doctor.

This module checks environment variables for weak secrets using the same
weak-secret detection mechanism as core.doctor.
"""

from __future__ import annotations

from core.doctor import DoctorCheck, _is_weak_secret
import os
from typing import List


def check_security_env() -> DoctorCheck:
    """
    Inspect selected environment variables for weak or empty secret values.

    Returns:
        DoctorCheck: with name 'security_env', status 'pass' when all secrets
        look strong, and 'fail' when one or more secrets are weak.
    """
    # List of sensitive environment variable names to inspect. Extend as needed.
    keys_to_check: List[str] = [
        "JWT_SECRET",
        "JWT_PRIVATE_KEY",
        "SECRET_KEY",
        "API_SECRET",
        "APP_SECRET",
        "SIDAR_API_KEY",
    ]
    warnings: List[str] = []

    for key in keys_to_check:
        value = os.getenv(key, "")
        # Only report when a value is provided; missing keys are ignored.
        if value and _is_weak_secret(value):
            warnings.append(f"{key} is weak or insecure")

    status = "fail" if warnings else "pass"
    message = "; ".join(warnings) if warnings else "Secrets look secure"
    return DoctorCheck(
        "security_env",
        status,
        message,
        {"checked_keys": keys_to_check, "warnings": warnings},
    )
