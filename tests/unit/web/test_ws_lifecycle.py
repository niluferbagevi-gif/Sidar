from __future__ import annotations

import asyncio

import pytest

from web.routes.ws_lifecycle import WebSocketLifecycle


@pytest.mark.asyncio
async def test_websocket_lifecycle_close_is_idempotent_under_concurrency() -> None:
    lifecycle = WebSocketLifecycle(websocket=object())
    calls = 0

    async def _cleanup() -> None:
        nonlocal calls
        await asyncio.sleep(0)
        calls += 1

    lifecycle.add_cleanup(_cleanup)
    await asyncio.gather(lifecycle.close(reason="a"), lifecycle.close(reason="b"))

    assert calls == 1


def test_track_task_ignores_none_and_duplicate_tasks() -> None:
    lifecycle = WebSocketLifecycle(websocket=object())
    task = object()

    assert lifecycle.track_task(None) is None
    assert lifecycle.track_task(task) is task
    assert lifecycle.track_task(task) is task
    assert lifecycle._tasks == [task]
