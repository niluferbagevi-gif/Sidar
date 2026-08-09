"""Redis Doctor checks."""

from __future__ import annotations

import os

from core.doctor import DoctorCheck


def check_redis() -> DoctorCheck:
    """Report Redis configuration presence without requiring a live broker.

    SIDAR_REDIS_URL is the primary variable actual Redis connections resolve
    through (see core.config_rate_limit.resolve_redis_url); REDIS_URL is only a
    legacy back-compat alias. Checking REDIS_URL alone used to report a false
    "not set" warning for installs that only set SIDAR_REDIS_URL, which is what
    install_sidar.sh's own .env defaults do.
    """
    redis_url = os.getenv("SIDAR_REDIS_URL", "").strip() or os.getenv("REDIS_URL", "").strip()
    backend = os.getenv("SIDAR_EVENT_BUS_BACKEND", "redis").strip().lower() or "redis"
    details = {
        "redis_url_set": bool(redis_url),
        "event_bus_backend": backend,
        "required_for_remote_event_bus": backend == "redis",
    }
    if redis_url:
        return DoctorCheck("redis", "pass", "Redis URL is configured", details)
    status = "warn" if backend == "redis" else "pass"
    message = (
        "Neither SIDAR_REDIS_URL nor REDIS_URL is set; Redis event bus will use local fallback"
        if backend == "redis"
        else "Redis is not the selected event bus backend"
    )
    return DoctorCheck("redis", status, message, details)


__all__ = ["check_redis"]
