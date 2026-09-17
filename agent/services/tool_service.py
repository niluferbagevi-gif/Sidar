"""Tool dispatch service for Sidar agent orchestration."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


async def execute_tool(
    tool: str,
    argument: str,
    *,
    resolve_handler: Callable[[str], Any],
) -> str:
    """Resolve and execute one named tool while preserving async/sync handlers."""
    normalized_tool = str(tool or "").strip().lower()
    if not normalized_tool:
        raise ValueError("Araç adı boş olamaz.")

    handler_name = f"_tool_{normalized_tool}"
    handler = resolve_handler(handler_name)
    if handler is None:
        raise ValueError(f"Bilinmeyen araç: {normalized_tool}")
    if not callable(handler):
        raise TypeError(f"Araç işleyicisi çağrılabilir değil: {handler_name}")

    result = handler(argument)
    if inspect.isawaitable(result):
        result = await result
    return str(result)
