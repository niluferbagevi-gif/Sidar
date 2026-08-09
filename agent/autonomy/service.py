"""Runtime autonomy state helpers extracted from SidarAgent."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class AutonomyStateOwner(Protocol):
    """Minimal state surface required by autonomy history helpers."""

    _autonomy_history: list[dict[str, Any]]
    _autonomy_lock: asyncio.Lock | None


def ensure_autonomy_runtime_state(owner: AutonomyStateOwner) -> None:
    """Ensure a SidarAgent-like object has autonomy history fields initialized."""
    if not hasattr(owner, "_autonomy_history") or owner._autonomy_history is None:
        owner._autonomy_history = []
    if not hasattr(owner, "_autonomy_lock"):
        owner._autonomy_lock = None


async def append_autonomy_history(owner: AutonomyStateOwner, record: dict[str, Any]) -> None:
    """Append one autonomy record while retaining the latest 50 entries."""
    ensure_autonomy_runtime_state(owner)
    if owner._autonomy_lock is None:
        owner._autonomy_lock = asyncio.Lock()
    async with owner._autonomy_lock:
        history = list(owner._autonomy_history[-49:])
        history.append(dict(record))
        owner._autonomy_history = history


def get_autonomy_activity(owner: AutonomyStateOwner, limit: int = 20) -> dict[str, Any]:
    """Return recent autonomy records with status/source counters."""
    ensure_autonomy_runtime_state(owner)
    normalized_limit = max(1, int(limit or 20))
    items = [dict(item) for item in owner._autonomy_history[-normalized_limit:]]
    counts_by_status: dict[str, int] = {}
    counts_by_source: dict[str, int] = {}
    for item in items:
        status = str(item.get("status", "unknown") or "unknown")
        source = str(item.get("source", "unknown") or "unknown")
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        counts_by_source[source] = counts_by_source.get(source, 0) + 1

    return {
        "items": items,
        "total": len(owner._autonomy_history),
        "returned": len(items),
        "counts_by_status": counts_by_status,
        "counts_by_source": counts_by_source,
        "latest_trigger_id": items[-1]["trigger_id"] if items else "",
    }
