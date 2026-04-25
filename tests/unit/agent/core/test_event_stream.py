from __future__ import annotations

import asyncio
import json
import sys
import types
from collections import deque

import pytest

# event_stream importu öncesi redis bağımlılığını hafif stub ile sağla
redis_mod = types.ModuleType("redis")
redis_asyncio_mod = types.ModuleType("redis.asyncio")
redis_exceptions_mod = types.ModuleType("redis.exceptions")


class _StubRedis:
    @staticmethod
    def from_url(*_args, **_kwargs):
        raise RuntimeError("stub")


class _StubResponseError(Exception):
    pass


redis_asyncio_mod.Redis = _StubRedis
redis_exceptions_mod.ResponseError = _StubResponseError
sys.modules.setdefault("redis", redis_mod)
sys.modules.setdefault("redis.asyncio", redis_asyncio_mod)
sys.modules.setdefault("redis.exceptions", redis_exceptions_mod)

import agent.core.event_stream as event_stream
from agent.core.event_stream import AgentEvent, AgentEventBus, get_agent_event_bus


class DummyRedis:
    def __init__(self) -> None:
        self.ping_called = False
        self.group_created = False
        self.xadd_calls: list[tuple] = []
        self.closed = False
        self.responses = []
        self.acks: list[str] = []
        self.raise_on_ack: set[str] = set()

    async def ping(self) -> None:
        self.ping_called = True

    async def xgroup_create(self, **_kwargs) -> None:
        self.group_created = True

    async def xadd(self, *args, **kwargs):
        self.xadd_calls.append((args, kwargs))
        return "1-0"

    async def xreadgroup(self, **_kwargs):
        if not self.responses:
            await asyncio.sleep(0)
            return []
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def xack(self, _channel: str, _group: str, msg_id: str) -> int:
        if msg_id in self.raise_on_ack:
            raise RuntimeError("ack boom")
        self.acks.append(msg_id)
        return 1

    async def aclose(self) -> None:
        self.closed = True


class FailingCloseRedis:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class AwaitableCloseRedis:
    def __init__(self) -> None:
        self.closed = False

    def close(self):
        async def _close() -> None:
            self.closed = True

        return _close()


class NonCallableCloseRedis:
    def __init__(self) -> None:
        self.close = "not-callable"


class NonAwaitableCloseRedis:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> str:
        self.closed = True
        return "closed"


@pytest.fixture
def bus() -> AgentEventBus:
    return AgentEventBus()


def test_subscribe_and_unsubscribe(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"ok": False}

    def _schedule() -> None:
        called["ok"] = True

    monkeypatch.setattr(bus, "_schedule_redis_bootstrap", _schedule)

    sid, queue = bus.subscribe(maxsize=3)

    assert sid in bus._subscribers
    assert queue.maxsize == 10
    assert called["ok"] is True

    bus._buffered_events[sid] = deque(maxlen=2)
    bus.unsubscribe(sid)
    assert sid not in bus._subscribers
    assert sid not in bus._buffered_events


def test_schedule_bootstrap_without_loop(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    bus._redis_available = False
    bus._schedule_redis_bootstrap()
    assert bus._redis_bootstrap_task is None

    bus._redis_available = None

    def _no_loop():
        raise RuntimeError("no loop")

    monkeypatch.setattr(asyncio, "get_running_loop", _no_loop)
    bus._schedule_redis_bootstrap()
    assert bus._redis_bootstrap_task is None


def test_schedule_bootstrap_skips_when_task_already_running(bus: AgentEventBus) -> None:
    class _RunningTask:
        def done(self) -> bool:
            return False

    bus._redis_bootstrap_task = _RunningTask()
    bus._schedule_redis_bootstrap()
    assert isinstance(bus._redis_bootstrap_task, _RunningTask)


def test_schedule_bootstrap_creates_task(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    created = {"task": None}

    class _Loop:
        def create_task(self, coro):
            coro.close()
            created["task"] = object()
            return created["task"]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _Loop())
    bus._schedule_redis_bootstrap()
    assert bus._redis_bootstrap_task is created["task"]


def test_publish_fanout_and_redis_call(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    fanout_events: list[AgentEvent] = []

    def _fanout(evt: AgentEvent) -> None:
        fanout_events.append(evt)

    called = {"scheduled": False, "redis": False}

    def _schedule() -> None:
        called["scheduled"] = True

    async def _pub(evt: AgentEvent) -> bool:
        called["redis"] = True
        assert evt.source == "coder"
        assert evt.message == "hello"
        return True

    monkeypatch.setattr(bus, "_fanout_local", _fanout)
    monkeypatch.setattr(bus, "_schedule_redis_bootstrap", _schedule)
    monkeypatch.setattr(bus, "_publish_via_redis", _pub)

    asyncio.run(bus.publish("coder", "hello"))

    assert called == {"scheduled": True, "redis": True}
    assert len(fanout_events) == 1


def test_ensure_listener_success_and_busygroup(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    redis = DummyRedis()

    class _RedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return redis

    async def _group_create(**_kwargs):
        raise event_stream.ResponseError("BUSYGROUP Consumer Group name already exists")

    redis.xgroup_create = _group_create

    async def _listener_once() -> None:
        return None

    monkeypatch.setattr(event_stream, "Redis", _RedisFactory)
    monkeypatch.setattr(bus, "_redis_listener_loop", _listener_once)

    asyncio.run(bus._ensure_redis_listener())

    assert bus._redis_available is True
    assert bus._redis_client is redis
    assert bus._redis_listener_task is not None
    asyncio.run(bus._cleanup_redis())


def test_ensure_listener_early_return_and_non_busygroup_error(
    monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus
) -> None:
    bus._redis_available = False
    asyncio.run(bus._ensure_redis_listener())

    class _RunningTask:
        def done(self) -> bool:
            return False

    bus._redis_available = None
    bus._redis_listener_task = _RunningTask()
    asyncio.run(bus._ensure_redis_listener())

    redis = DummyRedis()
    bus._redis_available = None
    bus._redis_listener_task = None
    bus._redis_client = redis
    monkeypatch.setattr(bus, "_ensure_redis_loop_compatibility", lambda: asyncio.sleep(0))

    async def _group_create(**_kwargs):
        raise event_stream.ResponseError("unexpected response error")

    cleaned = {"ok": False}
    redis.xgroup_create = _group_create

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)
    asyncio.run(bus._ensure_redis_listener())
    assert bus._redis_available is False
    assert cleaned["ok"] is True


@pytest.mark.asyncio
async def test_ensure_listener_returns_when_listener_task_running(bus: AgentEventBus) -> None:
    class _RunningTask:
        def done(self) -> bool:
            return False

    bus._redis_listener_task = _RunningTask()
    bus._redis_loop = asyncio.get_running_loop()
    await bus._ensure_redis_listener()
    assert isinstance(bus._redis_listener_task, _RunningTask)


def test_ensure_listener_failure_triggers_cleanup(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    class _BadRedis(DummyRedis):
        async def ping(self) -> None:
            raise RuntimeError("cannot connect")

    class _RedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return _BadRedis()

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True
        bus._redis_client = None

    monkeypatch.setattr(event_stream, "Redis", _RedisFactory)
    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)

    asyncio.run(bus._ensure_redis_listener())
    assert bus._redis_available is False
    assert cleaned["ok"] is True


def test_publish_via_redis_paths(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    evt = AgentEvent(ts=1.2, source="qa", message="msg")

    bus._redis_available = False
    assert asyncio.run(bus._publish_via_redis(evt)) is False

    bus._redis_available = None
    bus._redis_client = None

    async def _ensure_without_client() -> None:
        bus._redis_available = True

    monkeypatch.setattr(bus, "_ensure_redis_listener", _ensure_without_client)
    monkeypatch.setattr(bus, "_ensure_redis_loop_compatibility", lambda: asyncio.sleep(0))
    assert asyncio.run(bus._publish_via_redis(evt)) is False

    redis = DummyRedis()
    bus._redis_client = redis

    async def _ensure_with_client() -> None:
        bus._redis_available = True

    monkeypatch.setattr(bus, "_ensure_redis_listener", _ensure_with_client)
    monkeypatch.setattr(bus, "_ensure_redis_loop_compatibility", lambda: asyncio.sleep(0))
    assert asyncio.run(bus._publish_via_redis(evt)) is True
    payload = json.loads(redis.xadd_calls[0][0][1]["payload"])
    assert payload["source"] == "qa"

    async def _xadd_fail(*_args, **_kwargs):
        raise RuntimeError("xadd fail")

    redis.xadd = _xadd_fail
    written: list[dict] = []
    cleaned = {"ok": False}

    async def _dlq(**kwargs):
        written.append(kwargs)

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)

    assert asyncio.run(bus._publish_via_redis(evt)) is False
    assert bus._redis_available is False
    assert cleaned["ok"] is True
    assert written[0]["reason"] == "publish_failed"


def test_redis_listener_loop_handles_payload_ack_and_errors(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    redis = DummyRedis()
    bus._redis_client = redis
    bus._redis_available = True

    valid_other = {
        "payload": json.dumps({"sid": "other", "ts": 2, "source": "r", "message": "ok"})
    }
    valid_self = {"payload": json.dumps({"sid": bus._instance_id, "ts": 3, "source": "r", "message": "ignore"})}
    invalid = {"payload": "{not-json"}
    redis.raise_on_ack = {"2-0"}
    redis.responses = [
        [(bus._channel, [("1-0", valid_other), ("2-0", invalid), ("3-0", valid_self)])],
        asyncio.CancelledError(),
    ]

    fanouts: list[AgentEvent] = []
    dlq_reasons: list[str] = []

    def _fanout(evt: AgentEvent) -> None:
        fanouts.append(evt)

    async def _dlq(**kwargs):
        dlq_reasons.append(kwargs["reason"])

    monkeypatch.setattr(bus, "_fanout_local", _fanout)
    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bus._redis_listener_loop())

    assert len(fanouts) == 1
    assert fanouts[0].message == "ok"
    assert "invalid_payload" in dlq_reasons
    assert "ack_failed" in dlq_reasons


def test_redis_listener_loop_empty_response_continue(bus: AgentEventBus) -> None:
    redis = DummyRedis()
    bus._redis_client = redis
    bus._redis_available = True
    redis.responses = [
        [],
        asyncio.CancelledError(),
    ]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bus._redis_listener_loop())


def test_redis_listener_loop_read_error_cleanup(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    class _BrokenRedis(DummyRedis):
        async def xreadgroup(self, **_kwargs):
            raise RuntimeError("read failed")

    bus._redis_client = _BrokenRedis()
    bus._redis_available = True
    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)

    asyncio.run(bus._redis_listener_loop())
    assert bus._redis_available is False
    assert cleaned["ok"] is True


def test_drain_buffered_events_and_fanout(bus: AgentEventBus) -> None:
    sid1 = 1
    sid2 = 2
    q1: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=1)
    q2: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=1)
    bus._subscribers = {sid1: q1, sid2: q2}

    evt1 = AgentEvent(ts=1, source="a", message="m1")
    evt2 = AgentEvent(ts=2, source="a", message="m2")
    bus._buffered_events[sid1] = deque([evt1], maxlen=2)
    bus._buffered_events[sid2] = deque([evt2], maxlen=2)
    q2.put_nowait(AgentEvent(ts=0, source="x", message="full"))

    progressed = asyncio.run(bus._drain_buffered_events_once())
    assert progressed is True
    assert q1.get_nowait().message == "m1"
    assert len(bus._buffered_events[sid2]) == 1

    # fanout: sid1 full+buffer stores, sid2 full+no buffer dropped
    q1.put_nowait(AgentEvent(ts=9, source="x", message="full"))
    bus._buffered_events[sid1] = deque(maxlen=2)
    bus._buffered_events.pop(sid2, None)

    bus._fanout_local(AgentEvent(ts=5, source="y", message="f"))
    assert len(bus._buffered_events[sid1]) == 1
    assert sid2 not in bus._subscribers


def test_drain_buffered_events_skips_missing_buffers(bus: AgentEventBus) -> None:
    sid = 100
    bus._subscribers = {sid: asyncio.Queue(maxsize=1)}
    progressed = asyncio.run(bus._drain_buffered_events_once())
    assert progressed is False


def test_cleanup_redis_handles_cancel_and_close() -> None:
    bus = AgentEventBus()

    class _ListenerTask:
        def __init__(self) -> None:
            self._cancelled = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self._cancelled = True

        def __await__(self):
            async def _inner():
                raise asyncio.CancelledError()

            return _inner().__await__()

    bus._redis_listener_task = _ListenerTask()
    bus._redis_client = DummyRedis()
    asyncio.run(bus._cleanup_redis())

    assert bus._redis_listener_task is None
    assert bus._redis_client is None

    bus._redis_client = FailingCloseRedis()
    asyncio.run(bus._cleanup_redis())
    assert bus._redis_client is None

    redis_with_awaitable_close = AwaitableCloseRedis()
    bus._redis_client = redis_with_awaitable_close
    asyncio.run(bus._cleanup_redis())
    assert redis_with_awaitable_close.closed is True
    assert bus._redis_client is None


def test_cleanup_redis_without_client_or_listener() -> None:
    bus = AgentEventBus()
    asyncio.run(bus._cleanup_redis())
    assert bus._redis_listener_task is None
    assert bus._redis_client is None
    assert bus._redis_loop is None


def test_cleanup_redis_handles_non_callable_and_non_awaitable_close() -> None:
    bus = AgentEventBus()

    bus._redis_client = NonCallableCloseRedis()
    asyncio.run(bus._cleanup_redis())
    assert bus._redis_client is None

    redis_with_sync_close = NonAwaitableCloseRedis()
    bus._redis_client = redis_with_sync_close
    asyncio.run(bus._cleanup_redis())
    assert redis_with_sync_close.closed is True
    assert bus._redis_client is None


def test_ensure_redis_loop_compatibility_resets_cross_loop_state(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._redis_client = DummyRedis()
    bus._redis_loop = object()

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True
        bus._redis_client = None
        bus._redis_listener_task = None
        bus._redis_loop = None

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)
    asyncio.run(bus._ensure_redis_loop_compatibility())

    assert cleaned["ok"] is True
    assert bus._redis_available is None


def test_ensure_redis_loop_compatibility_returns_without_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._redis_client = object()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    asyncio.run(bus._ensure_redis_loop_compatibility())
    assert bus._redis_client is not None


@pytest.mark.asyncio
async def test_ensure_redis_loop_compatibility_returns_when_same_loop() -> None:
    bus = AgentEventBus()
    current_loop = asyncio.get_running_loop()
    bus._redis_client = object()
    bus._redis_loop = current_loop
    await bus._ensure_redis_loop_compatibility()
    assert bus._redis_available is None


def test_write_dead_letter_local_and_redis(bus: AgentEventBus) -> None:
    asyncio.run(bus._write_dead_letter(reason="r1", payload={"a": 1}, error=RuntimeError("boom")))
    assert len(bus._dlq_buffer) == 1
    assert bus._dlq_buffer[-1]["error"] == "boom"

    redis = DummyRedis()
    bus._redis_client = redis
    bus._redis_available = True
    asyncio.run(bus._write_dead_letter(reason="r2", payload={"b": 2}))

    assert len(redis.xadd_calls) == 1
    args, kwargs = redis.xadd_calls[0]
    assert args[0] == bus._dlq_channel
    assert kwargs["approximate"] is True

    async def _xadd_fail(*_args, **_kwargs):
        raise RuntimeError("dlq fail")

    redis.xadd = _xadd_fail
    asyncio.run(bus._write_dead_letter(reason="r3", payload={"c": 3}))


def test_get_agent_event_bus_singleton() -> None:
    assert get_agent_event_bus() is event_stream._BUS
    assert isinstance(get_agent_event_bus(), AgentEventBus)


def test_test_doubles_cover_default_stub_paths() -> None:
    with pytest.raises(RuntimeError, match="stub"):
        _StubRedis.from_url("redis://localhost:6379/0")

    redis = DummyRedis()
    asyncio.run(redis.xgroup_create(name="stream", groupname="group"))
    assert redis.group_created is True

    assert asyncio.run(redis.xreadgroup()) == []
