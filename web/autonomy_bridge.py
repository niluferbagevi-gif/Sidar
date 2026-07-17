"""Autonomy trigger helpers shared by the web API layer."""

from __future__ import annotations

from typing import Any


def autonomy_service_actor(config: Any, trigger_source: str) -> tuple[str, str]:
    """Return the explicit service actor used by userless autonomy triggers."""
    configured_user = str(
        getattr(config, "AUTONOMY_SERVICE_USER_ID", "")
        or getattr(config, "SYSTEM_USER_ID", "")
        or "system:autonomy"
    ).strip()
    service_user_id = configured_user or "system:autonomy"
    source_label = str(trigger_source or "external").strip() or "external"
    return service_user_id, f"autonomy:{source_label}"


def trim_autonomy_text(value: Any, limit: int = 1200) -> str:
    """Normalize and truncate webhook/autonomy text fields for prompts and logs."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[truncated]"
