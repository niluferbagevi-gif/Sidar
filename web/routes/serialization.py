"""Side-effect-free serializers shared by Sidar route factories."""

from __future__ import annotations

from typing import Any


def serialize_prompt(record: Any) -> dict[str, Any]:
    """Serialize a prompt registry record while preserving non-numeric legacy ids."""
    prompt_id = getattr(record, "id", 0)
    serialized_id: int | str
    try:
        serialized_id = int(prompt_id)
    except (TypeError, ValueError):
        serialized_id = str(prompt_id or "")

    return {
        "id": serialized_id,
        "role_name": str(getattr(record, "role_name", "") or ""),
        "prompt_text": str(getattr(record, "prompt_text", "") or ""),
        "version": int(getattr(record, "version", 1) or 1),
        "is_active": bool(getattr(record, "is_active", False)),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def serialize_swarm_result(record: Any) -> dict[str, Any]:
    """Serialize a swarm result into the stable orchestration response shape."""
    return {
        "task_id": str(getattr(record, "task_id", "") or ""),
        "agent_role": str(getattr(record, "agent_role", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "summary": str(getattr(record, "summary", "") or ""),
        "elapsed_ms": int(getattr(record, "elapsed_ms", 0) or 0),
        "evidence": list(getattr(record, "evidence", []) or []),
        "handoffs": list(getattr(record, "handoffs", []) or []),
        "graph": dict(getattr(record, "graph", {}) or {}),
    }
