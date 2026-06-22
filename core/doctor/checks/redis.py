"""
Redis readiness check for Sidar doctor.

This module performs a simple connectivity check against a Redis server using
the redis-py client. If the redis module is unavailable or the server cannot
be reached, it returns a warning.
"""

from __future__ import annotations

from core.doctor import DoctorCheck
import os


def check_redis_connectivity() -> DoctorCheck:
    """
    Perform a basic connectivity check against a Redis server.

    Uses the REDIS_URL environment variable to determine the target endpoint.
    Defaults to redis://localhost:6379/0 when not set.
    """
    try:
        import redis  # type: ignore
    except ImportError:
        return DoctorCheck(
            "redis",
            "warn",
            "redis module is not installed; redis checks skipped",
            {"install_commands": ["pip install redis"]},
        )

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip() or "redis://localhost:6379/0"

    try:
        client = redis.from_url(url)
        client.ping()
    except Exception as exc:
        return DoctorCheck(
            "redis",
            "warn",
            "Redis connectivity check failed",
            {"error": str(exc), "url": url},
        )

    return DoctorCheck(
        "redis",
        "pass",
        "Redis connectivity check passed",
        {"url": url},
    )
