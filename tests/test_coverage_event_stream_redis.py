"""
Coverage tests for agent/core/event_stream.py — Redis paths.

Covers lines 69, 71, 86-90, 104-120, 123-160, 174-176
  - _ensure_redis_listener (skips when listener running, creates client)
  - _publish_via_redis (success, fail-cleanup paths)
  - _redis_listener_loop (entries processing, CancelledError, exception)
  - _cleanup_redis (cancel task, close client)
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from agent.core.event_stream import AgentEventBus, AgentEvent


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_bus() -> AgentEventBus:
    bus = AgentEventBus()
    return bus


# ── _ensure_redis_listener skips when already running ────────────────────────

@pytest.mark.asyncio
async def test_ensure_redis_listener_skips_when_listener_already_running():
    """Line 71: returns early when listener task is still running."""
    bus = _make_bus()

    running_task = MagicMock()
    running_task.done.return_value = False
    bus._redis_listener_task = running_task
    bus._redis_available = None  # not False

    # Should return without touching redis
    await bus._ensure_redis_listener()

    # Listener task should be unchanged
    assert bus._redis_listener_task is running_task


@pytest.mark.asyncio
async def test_ensure_redis_listener_skips_when_redis_unavailable():
    """Line 69: returns early when redis_available is False."""
    bus = _make_bus()
    bus._redis_available = False

    await bus._ensure_redis_listener()

    # Nothing should have changed
    assert bus._redis_available is False
    assert bus._redis_client is None


# ── _ensure_redis_listener — connection failure → cleanup ────────────────────

@pytest.mark.asyncio
async def test_ensure_redis_listener_connection_failure():
    """Lines 91-94: on connection failure sets redis_available=False and cleans up."""
    bus = _make_bus()

    with patch("agent.core.event_stream.Redis") as MockRedis:
        MockRedis.from_url.side_effect = ConnectionError("no redis")
        await bus._ensure_redis_listener()

    assert bus._redis_available is False
    assert bus._redis_client is None


# ── _ensure_redis_listener — BUSYGROUP is ignored ────────────────────────────

@pytest.mark.asyncio
async def test_ensure_redis_listener_busygroup_ignored():
    """Lines 86-90: ResponseError with BUSYGROUP is silently ignored."""
    from redis.exceptions import ResponseError

    bus = _make_bus()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"))

    # Prevent actual task creation from running the full loop
    created_tasks = []

    original_create_task = asyncio.create_task

    async def _fake_listener_loop():
        pass

    with patch("agent.core.event_stream.Redis") as MockRedis:
        MockRedis.from_url.return_value = mock_redis
        with patch.object(bus, "_redis_listener_loop", return_value=_fake_listener_loop()):
            with patch("asyncio.create_task") as mock_create_task:
                fake_task = MagicMock()
                mock_create_task.return_value = fake_task
                await bus._ensure_redis_listener()

    assert bus._redis_available is True


# ── _publish_via_redis — returns False when unavailable ─────────────────────

@pytest.mark.asyncio
async def test_publish_via_redis_returns_false_when_unavailable():
    """Line 97-98: returns False immediately when redis is not available."""
    bus = _make_bus()
    bus._redis_available = False

    evt = AgentEvent(ts=time.time(), source="test", message="hello")
    result = await bus._publish_via_redis(evt)

    assert result is False


# ── _publish_via_redis — success path ────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_via_redis_success():
    """Lines 104-115: publishes event to redis stream successfully."""
    bus = _make_bus()
    bus._redis_available = True

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"1-0")
    bus._redis_client = mock_redis

    # Mock _ensure_redis_listener to not do anything
    with patch.object(bus, "_ensure_redis_listener", new_callable=AsyncMock):
        evt = AgentEvent(ts=time.time(), source="src", message="msg")
        result = await bus._publish_via_redis(evt)

    assert result is True
    mock_redis.xadd.assert_called_once()


# ── _publish_via_redis — redis xadd fails → cleanup ─────────────────────────

@pytest.mark.asyncio
async def test_publish_via_redis_xadd_failure_triggers_cleanup():
    """Lines 116-120: xadd failure sets available=False and cleans up."""
    bus = _make_bus()
    bus._redis_available = True

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(side_effect=Exception("xadd fail"))
    bus._redis_client = mock_redis

    with patch.object(bus, "_ensure_redis_listener", new_callable=AsyncMock):
        with patch.object(bus, "_cleanup_redis", new_callable=AsyncMock) as mock_cleanup:
            evt = AgentEvent(ts=time.time(), source="src", message="msg")
            result = await bus._publish_via_redis(evt)

    assert result is False
    assert bus._redis_available is False
    mock_cleanup.assert_called_once()


# ── _redis_listener_loop — processes entries ──────────────────────────────────

@pytest.mark.asyncio
async def test_redis_listener_loop_processes_remote_events():
    """Lines 122-160: listener loop processes events from other instances."""
    bus = _make_bus()

    other_sid = "other-instance-id"
    payload = json.dumps({
        "sid": other_sid,
        "ts": time.time(),
        "source": "remote",
        "message": "remote message",
    })

    # First call returns data, second raises CancelledError to stop loop
    call_count = 0

    async def _xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [("stream", [("1-0", {"payload": payload})])]
        raise asyncio.CancelledError()

    mock_redis = AsyncMock()
    mock_redis.xreadgroup = _xreadgroup
    mock_redis.xack = AsyncMock()
    bus._redis_client = mock_redis

    received = []
    sub_id, q = bus.subscribe()

    with pytest.raises(asyncio.CancelledError):
        await bus._redis_listener_loop()

    bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_redis_listener_loop_skips_own_events():
    """Lines 149: events from same instance (same sid) are not fanned out."""
    bus = _make_bus()

    # Same instance_id as bus
    payload = json.dumps({
        "sid": bus._instance_id,
        "ts": time.time(),
        "source": "self",
        "message": "self message",
    })

    call_count = 0

    async def _xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [("stream", [("1-0", {"payload": payload})])]
        raise asyncio.CancelledError()

    mock_redis = AsyncMock()
    mock_redis.xreadgroup = _xreadgroup
    mock_redis.xack = AsyncMock()
    bus._redis_client = mock_redis

    sub_id, q = bus.subscribe()

    with pytest.raises(asyncio.CancelledError):
        await bus._redis_listener_loop()

    assert q.empty()
    bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_redis_listener_loop_empty_response_continues():
    """Line 141: empty response causes continue (no fan-out)."""
    bus = _make_bus()

    call_count = 0

    async def _xreadgroup(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # empty
        raise asyncio.CancelledError()

    mock_redis = AsyncMock()
    mock_redis.xreadgroup = _xreadgroup
    bus._redis_client = mock_redis

    with pytest.raises(asyncio.CancelledError):
        await bus._redis_listener_loop()


@pytest.mark.asyncio
async def test_redis_listener_loop_exception_triggers_cleanup():
    """Lines 135-139: non-CancelledError exception sets available=False."""
    bus = _make_bus()
    bus._redis_available = True

    async def _xreadgroup(**kwargs):
        raise RuntimeError("network error")

    mock_redis = AsyncMock()
    mock_redis.xreadgroup = _xreadgroup
    bus._redis_client = mock_redis

    with patch.object(bus, "_cleanup_redis", new_callable=AsyncMock) as mock_cleanup:
        await bus._redis_listener_loop()

    assert bus._redis_available is False
    mock_cleanup.assert_called_once()


# ── _cleanup_redis ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_redis_cancels_listener_task():
    """Lines 173-177: _cleanup_redis cancels running listener task."""
    bus = _make_bus()

    # Use an already-done task to avoid CancelledError propagation
    async def _already_done():
        pass

    task = asyncio.create_task(_already_done())
    await asyncio.sleep(0)  # let task finish
    bus._redis_listener_task = task

    mock_redis = AsyncMock()
    mock_redis.aclose = AsyncMock()
    bus._redis_client = mock_redis

    await bus._cleanup_redis()

    assert bus._redis_listener_task is None
    assert bus._redis_client is None


@pytest.mark.asyncio
async def test_cleanup_redis_no_task():
    """_cleanup_redis with no listener task works without error."""
    bus = _make_bus()
    bus._redis_listener_task = None

    mock_redis = AsyncMock()
    mock_redis.aclose = AsyncMock()
    bus._redis_client = mock_redis

    await bus._cleanup_redis()

    assert bus._redis_client is None


# ── _schedule_redis_bootstrap — no running loop ───────────────────────────────

def test_schedule_redis_bootstrap_no_running_loop():
    """Line 63-64: when no event loop is running, bootstrap is skipped."""
    bus = _make_bus()
    bus._redis_available = None
    # Outside async context — should not raise
    bus._schedule_redis_bootstrap()
    assert bus._redis_bootstrap_task is None


# ── publish — fanout + redis ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_fanout_and_redis():
    """publish() calls fanout_local and _publish_via_redis."""
    bus = _make_bus()
    sub_id, q = bus.subscribe()

    with patch.object(bus, "_publish_via_redis", new_callable=AsyncMock, return_value=True):
        with patch.object(bus, "_schedule_redis_bootstrap"):
            await bus.publish("source", "hello world")

    assert not q.empty()
    evt = q.get_nowait()
    assert evt.message == "hello world"
    bus.unsubscribe(sub_id)
