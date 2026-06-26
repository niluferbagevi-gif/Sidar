"""Shared WebSocket lifecycle cleanup helpers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket


class WebSocketLifecycle:
    """Owns deterministic task cancellation and disconnect cleanup for a websocket."""

    def __init__(self, websocket: WebSocket, *, logger: Any | None = None) -> None:
        self.websocket = websocket
        self.logger = logger
        self._cleanup_callbacks: list[Callable[[], Awaitable[Any]]] = []
        self._tasks: list[Any] = []
        self._closed = False
        self._close_lock = asyncio.Lock()

    def track_task(self, task: Any | None) -> Any | None:
        """Register a task-like object that must be cancelled before session shutdown."""
        if task is not None and task not in self._tasks:
            self._tasks.append(task)
        return task

    def add_cleanup(self, callback: Callable[[], Awaitable[Any]]) -> None:
        """Register an idempotent async cleanup callback for session shutdown."""
        self._cleanup_callbacks.append(callback)

    async def cancel_task(self, task: Any | None) -> None:
        """Cancel one task-like object and wait for cancellation to settle."""
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def close(self, *, reason: str = "disconnect") -> None:
        """Run all tracked cleanup exactly once, even under concurrent disconnect paths."""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            for task in list(reversed(self._tasks)):
                await self.cancel_task(task)
            for callback in list(reversed(self._cleanup_callbacks)):
                try:
                    await callback()
                except Exception as exc:  # pragma: no cover - defensive logging only
                    if self.logger is not None:
                        self.logger.debug(
                            "WebSocket cleanup callback failed during %s: %s", reason, exc
                        )
