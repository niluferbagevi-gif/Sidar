from __future__ import annotations

import asyncio
from collections import deque

import pytest
from redis.exceptions import ResponseError

from agent.core.event_stream import AgentEvent, AgentEventBus


class _FakeRedis:
    def __init__(self) -> None:
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []
        self.fail_xadd = False
        self.fail_ack = False
        self.read_payload: object = []
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def xgroup_create(self, **kwargs) -> None:
        if kwargs.get("groupname") == "busy-group":
            raise ResponseError("BUSYGROUP Consumer Group name already exists")

    async def xadd(self, channel: str, payload: dict[str, str], **kwargs) -> str:
        if self.fail_xadd:
            raise RuntimeError("xadd failed")
        self.xadd_calls.append((channel, payload))
        return "1-0"

    async def xreadgroup(self, **kwargs):
        if isinstance(self.read_payload, Exception):
            raise self.read_payload
        data = self.read_payload
        self.read_payload = RuntimeError("loop end")
        return data

    async def xack(self, *args, **kwargs) -> int:
        if self.fail_ack:
            raise RuntimeError("ack failed")
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_and_buffer_drain() -> None:
    bus = AgentEventBus()
    sid, queue = bus.subscribe(maxsize=10)
    bus._redis_available = False

    event = AgentEvent(ts=1.0, source="a", message="m")
    bus._buffered_events[sid] = deque([event])
    progressed = await bus._drain_buffered_events_once()

    assert progressed is True
    assert queue.get_nowait().message == "m"

    bus.unsubscribe(sid)
    assert sid not in bus._subscribers


@pytest.mark.asyncio
async def test_fanout_local_buffers_or_drops_full_subscribers() -> None:
    bus = AgentEventBus()
    # buffered subscriber
    sid1, q1 = bus.subscribe(maxsize=1)
    bus._redis_available = False
    for _ in range(10):
        q1.put_nowait(AgentEvent(ts=0, source="x", message="full"))
    bus._buffered_events[sid1] = deque(maxlen=2)

    # dropped subscriber
    await asyncio.sleep(0.002)
    sid2, q2 = bus.subscribe(maxsize=1)
    for _ in range(10):
        q2.put_nowait(AgentEvent(ts=0, source="x", message="full"))

    bus._fanout_local(AgentEvent(ts=2, source="src", message="next"))

    assert len(bus._buffered_events[sid1]) == 1
    assert sid2 not in bus._subscribers


@pytest.mark.asyncio
async def test_publish_via_redis_success_and_failure_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    fake = _FakeRedis()
    bus._redis_client = fake
    bus._redis_available = True

    ok = await bus._publish_via_redis(AgentEvent(ts=3, source="s", message="ok"))
    assert ok is True
    assert fake.xadd_calls

    fake.fail_xadd = True
    ok = await bus._publish_via_redis(AgentEvent(ts=4, source="s", message="err"))
    assert ok is False
    assert bus._redis_available is False
    assert bus._dlq_buffer[-1]["reason"] == "publish_failed"


@pytest.mark.asyncio
async def test_ensure_listener_handles_busygroup_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    fake = _FakeRedis()
    bus._consumer_group = "busy-group"

    class _RedisFactory:
        @staticmethod
        def from_url(*args, **kwargs):
            return fake

    monkeypatch.setattr("agent.core.event_stream.Redis", _RedisFactory)
    monkeypatch.setattr(bus, "_redis_listener_loop", lambda: asyncio.sleep(0))

    await bus._ensure_redis_listener()
    assert bus._redis_available is True

    await bus._cleanup_redis()
    assert fake.closed is True


@pytest.mark.asyncio
async def test_listener_loop_invalid_payload_and_ack_failure() -> None:
    bus = AgentEventBus()
    fake = _FakeRedis()
    fake.fail_ack = True
    fake.read_payload = [
        (
            "stream",
            [
                ("1-0", {"payload": "{invalid json"}),
            ],
        )
    ]
    bus._redis_client = fake
    bus._redis_available = True

    await bus._redis_listener_loop()

    reasons = [item["reason"] for item in bus._dlq_buffer]
    assert "invalid_payload" in reasons
    assert "ack_failed" in reasons
    assert bus._redis_available is False


@pytest.mark.asyncio
async def test_write_dead_letter_without_redis_channel() -> None:
    bus = AgentEventBus()
    bus._redis_client = None
    bus._redis_available = False

    await bus._write_dead_letter(reason="unit", payload={"k": "v"}, error=RuntimeError("e"))

    assert bus._dlq_buffer[-1]["reason"] == "unit"
    assert "error" in bus._dlq_buffer[-1]
