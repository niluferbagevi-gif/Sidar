"""Redis Doctor checks."""

from __future__ import annotations

import os

from core.doctor import DoctorCheck


def check_redis() -> DoctorCheck:
    """Report Redis configuration presence without requiring a live broker."""
    redis_url = os.getenv("REDIS_URL", "").strip()
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
        "REDIS_URL is not set; Redis event bus will use local fallback"
        if backend == "redis"
        else "Redis is not the selected event bus backend"
    )
    return DoctorCheck("redis", status, message, details)


__all__ = ["check_redis"]
