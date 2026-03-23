import asyncio
from collections import deque
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_event_stream_module():
    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    sys.modules.setdefault("agent", agent_pkg)
    sys.modules.setdefault("agent.core", core_pkg)


    if "redis" not in sys.modules:
        redis_mod = types.ModuleType("redis")
        redis_asyncio_mod = types.ModuleType("redis.asyncio")
        redis_ex_mod = types.ModuleType("redis.exceptions")

        class _Redis:  # pragma: no cover - lightweight import stub
            @classmethod
            def from_url(cls, *args, **kwargs):
                raise RuntimeError("stub")

        class _ResponseError(Exception):
            pass

        redis_asyncio_mod.Redis = _Redis
        redis_ex_mod.ResponseError = _ResponseError
        redis_mod.asyncio = redis_asyncio_mod
        redis_mod.exceptions = redis_ex_mod

        sys.modules["redis"] = redis_mod
        sys.modules["redis.asyncio"] = redis_asyncio_mod
        sys.modules["redis.exceptions"] = redis_ex_mod

    spec = importlib.util.spec_from_file_location(
        "agent.core.event_stream",
        ROOT / "agent" / "core" / "event_stream.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["agent.core.event_stream"] = module
    spec.loader.exec_module(module)
    return module


_event_stream = _load_event_stream_module()
AgentEvent = _event_stream.AgentEvent
AgentEventBus = _event_stream.AgentEventBus
get_agent_event_bus = _event_stream.get_agent_event_bus


def test_event_bus_publish_and_subscribe_roundtrip():
    bus = get_agent_event_bus()

    async def _run():
        sid, q = bus.subscribe()
        await bus.publish("supervisor", "Kod yazılıyor")
        evt = await asyncio.wait_for(q.get(), timeout=1)
        bus.unsubscribe(sid)
        return evt

    evt = asyncio.run(_run())
    assert evt.source == "supervisor"
    assert "Kod yazılıyor" in evt.message


def test_event_bus_publish_without_subscribers_is_a_noop_locally(monkeypatch):
    bus = AgentEventBus()
    published = []

    async def _publish_stub(evt):
        published.append((evt.source, evt.message))
        return False

    monkeypatch.setattr(bus, "_publish_via_redis", _publish_stub)

    asyncio.run(bus.publish("supervisor", "kimse dinlemiyor"))

    assert bus._subscribers == {}
    assert published == [("supervisor", "kimse dinlemiyor")]


def test_event_bus_listener_switches_to_local_fallback_on_redis_disconnect(monkeypatch):
    bus = AgentEventBus()
    bus._redis_available = True

    cleaned = {"value": False}

    class _FailingRedis:
        async def xreadgroup(self, **kwargs):
            raise _event_stream.ResponseError("redis bağlantısı koptu")

    async def _cleanup_stub():
        cleaned["value"] = True
        bus._redis_client = None

    bus._redis_client = _FailingRedis()
    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup_stub)

    asyncio.run(bus._redis_listener_loop())

    assert bus._redis_available is False
    assert cleaned["value"] is True


def test_event_bus_fanout_buffers_full_queues_instead_of_unsubscribe():
    bus = AgentEventBus()

    full_q = asyncio.Queue(maxsize=10)
    survivor_q = asyncio.Queue(maxsize=10)
    for i in range(10):
        full_q.put_nowait(AgentEvent(ts=float(i), source="seed", message=f"m{i}"))

    bus._subscribers = {1: full_q, 2: survivor_q}
    bus._buffered_events = {1: deque(maxlen=10), 2: deque(maxlen=10)}
    evt = AgentEvent(ts=1.0, source="supervisor", message="devam")

    bus._fanout_local(evt)

    assert 1 in bus._subscribers
    assert 2 in bus._subscribers
    got = survivor_q.get_nowait()
    assert got.message == "devam"
    assert len(bus._buffered_events[1]) == 1
    assert bus._buffered_events[1][0].message == "devam"


def test_event_bus_drain_buffered_events_once_moves_waiting_events():
    bus = AgentEventBus()
    q = asyncio.Queue(maxsize=1)
    sid = 10
    bus._subscribers = {sid: q}
    bus._buffered_events = {sid: deque(maxlen=10)}
    q.put_nowait(AgentEvent(ts=0.0, source="seed", message="seed"))
    bus._buffered_events[sid].append(AgentEvent(ts=1.0, source="supervisor", message="buffered"))

    async def _run():
        first = await bus._drain_buffered_events_once()
        assert first is True
        _ = q.get_nowait()  # seed tüket
        second = await bus._drain_buffered_events_once()
        assert second is True
        moved = q.get_nowait()
        third = await bus._drain_buffered_events_once()
        return moved, third

    moved, third = asyncio.run(_run())
    assert moved.message == "buffered"
    assert third is False


def test_publish_via_redis_failure_sets_local_fallback(monkeypatch):
    bus = AgentEventBus()
    bus._redis_available = True

    class _BadRedis:
        async def xadd(self, *_a, **_k):
            raise _event_stream.ResponseError("redis down")

    cleaned = {"called": False}

    async def _ensure():
        return None

    async def _cleanup():
        cleaned["called"] = True
        bus._redis_client = None

    bus._redis_client = _BadRedis()
    monkeypatch.setattr(bus, "_ensure_redis_listener", _ensure)
    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)

    evt = AgentEvent(ts=1.0, source="s", message="m")
    ok = asyncio.run(bus._publish_via_redis(evt))
    assert ok is False
    assert bus._redis_available is False
    assert cleaned["called"] is True
    assert bus._dlq_buffer
    assert bus._dlq_buffer[-1]["reason"] == "publish_failed"


def test_event_bus_listener_handles_invalid_payload_and_ack_failures(monkeypatch):
    bus = AgentEventBus()
    bus._redis_available = True

    class _OneShotRedis:
        def __init__(self):
            self.acked = []
            self.called = 0

        async def xreadgroup(self, **_kwargs):
            self.called += 1
            if self.called == 1:
                return [(
                    "sidar:agent_events",
                    [("1-0", {"payload": "{not-json}"}), ("2-0", {"payload": '{"sid":"other","ts":1,"source":"x","message":"y"}'})],
                )]
            raise RuntimeError("stop loop")

        async def xack(self, _channel, _group, msg_id):
            self.acked.append(msg_id)
            if msg_id == "1-0":
                raise RuntimeError("ack failed")

    redis = _OneShotRedis()
    bus._redis_client = redis

    cleaned = {"called": False}

    async def _cleanup_stub():
        cleaned["called"] = True
        bus._redis_client = None

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup_stub)

    sid, q = bus.subscribe(maxsize=20)
    try:
        asyncio.run(bus._redis_listener_loop())
    finally:
        bus.unsubscribe(sid)

    # invalid payload ignored; foreign sid payload faned out
    evt = q.get_nowait()
    assert evt.source == "x"
    assert evt.message == "y"
    assert "1-0" in redis.acked and "2-0" in redis.acked
    assert cleaned["called"] is True
    reasons = [item["reason"] for item in bus._dlq_buffer]
    assert "invalid_payload" in reasons
    assert "ack_failed" in reasons


def test_event_bus_listener_ignores_same_instance_messages_but_still_acks(monkeypatch):
    bus = AgentEventBus()
    bus._redis_available = True

    class _OneShotRedis:
        def __init__(self):
            self.acked = []
            self.called = 0

        async def xreadgroup(self, **_kwargs):
            self.called += 1
            if self.called == 1:
                return [(
                    "sidar:agent_events",
                    [("1-0", {"payload": json.dumps({"sid": bus._instance_id, "ts": 1, "source": "self", "message": "ignore"})})],
                )]
            raise RuntimeError("stop loop")

        async def xack(self, _channel, _group, msg_id):
            self.acked.append(msg_id)

    redis = _OneShotRedis()
    bus._redis_client = redis

    cleaned = {"called": False}

    async def _cleanup_stub():
        cleaned["called"] = True
        bus._redis_client = None

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup_stub)

    sid, q = bus.subscribe(maxsize=5)
    try:
        asyncio.run(bus._redis_listener_loop())
    finally:
        bus.unsubscribe(sid)

    assert redis.acked == ["1-0"]
    assert q.empty() is True
    assert cleaned["called"] is True
    assert list(bus._dlq_buffer) == []


def test_write_dead_letter_pushes_to_redis_when_available():
    bus = AgentEventBus()
    bus._redis_available = True

    class _Redis:
        def __init__(self):
            self.calls = []

        async def xadd(self, channel, fields, **kwargs):
            self.calls.append((channel, fields, kwargs))

    redis = _Redis()
    bus._redis_client = redis

    asyncio.run(bus._write_dead_letter(reason="manual", payload={"msg": "broken"}))

    assert bus._dlq_buffer[-1]["reason"] == "manual"
    assert redis.calls
    assert redis.calls[0][0] == bus._dlq_channel




def test_write_dead_letter_skips_redis_when_client_missing_or_disabled():
    bus = AgentEventBus()

    class _Redis:
        def __init__(self):
            self.calls = []

        async def xadd(self, channel, fields, **kwargs):
            self.calls.append((channel, fields, kwargs))

    redis = _Redis()
    bus._redis_client = redis
    bus._redis_available = False

    asyncio.run(bus._write_dead_letter(reason="disabled", payload={"msg": "keep-local"}))

    assert bus._dlq_buffer[-1]["reason"] == "disabled"
    assert redis.calls == []

    bus._redis_client = None
    bus._redis_available = True
    asyncio.run(bus._write_dead_letter(reason="missing-client", payload={"msg": "still-local"}))

    assert bus._dlq_buffer[-1]["reason"] == "missing-client"


def test_ensure_listener_falls_back_when_consumer_group_create_errors(monkeypatch):
    bus = AgentEventBus()

    class _FailingRedis:
        async def ping(self):
            return True

        async def xgroup_create(self, **_kwargs):
            raise _event_stream.ResponseError("NOGROUP cannot create consumer group")

        async def close(self):
            return None

    monkeypatch.setattr(_event_stream.Redis, "from_url", lambda *_a, **_k: _FailingRedis())

    asyncio.run(bus._ensure_redis_listener())

    assert bus._redis_available is False
    assert bus._redis_client is None
    assert bus._redis_listener_task is None


def test_event_bus_listener_retries_after_empty_poll_then_falls_back(monkeypatch):
    bus = AgentEventBus()
    bus._redis_available = True

    cleaned = {"value": False}

    class _PollingRedis:
        def __init__(self):
            self.calls = 0

        async def xreadgroup(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return []
            raise _event_stream.ResponseError("listen failed after idle poll")

    async def _cleanup_stub():
        cleaned["value"] = True
        bus._redis_client = None

    redis = _PollingRedis()
    bus._redis_client = redis
    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup_stub)

    asyncio.run(bus._redis_listener_loop())

    assert redis.calls == 2
    assert bus._redis_available is False
    assert cleaned["value"] is True




def test_event_bus_listener_propagates_task_cancellation():
    bus = AgentEventBus()
    bus._redis_available = True

    class _CancelledRedis:
        async def xreadgroup(self, **_kwargs):
            raise asyncio.CancelledError()

    bus._redis_client = _CancelledRedis()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bus._redis_listener_loop())


def test_cleanup_redis_swallows_cancelled_listener_task_and_closes_client():
    bus = AgentEventBus()

    class _CancelledTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

        def __await__(self):
            async def _inner():
                raise asyncio.CancelledError()

            return _inner().__await__()

    class _ClosableRedis:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    task = _CancelledTask()
    redis = _ClosableRedis()
    bus._redis_listener_task = task
    bus._redis_client = redis

    asyncio.run(bus._cleanup_redis())

    assert task.cancel_called is True
    assert redis.closed is True
    assert bus._redis_listener_task is None
    assert bus._redis_client is None

def test_event_bus_fanout_unsubscribes_when_queue_full_and_no_buffer_space():
    bus = AgentEventBus()
    full_q = asyncio.Queue(maxsize=1)
    full_q.put_nowait(AgentEvent(ts=0.0, source="seed", message="seed"))

    bus._subscribers = {1: full_q}
    bus._buffered_events = {}
    bus._fanout_local(AgentEvent(ts=1.0, source="x", message="y"))

    assert 1 not in bus._subscribers


def test_event_bus_drain_buffered_events_once_skips_subscribers_without_buffers():
    bus = AgentEventBus()
    q = asyncio.Queue(maxsize=1)
    bus._subscribers = {1: q}
    bus._buffered_events = {}

    assert asyncio.run(bus._drain_buffered_events_once()) is False
    assert q.empty() is True


def test_event_bus_fanout_unsubscribes_when_existing_buffer_is_full():
    bus = AgentEventBus()
    full_q = asyncio.Queue(maxsize=1)
    full_q.put_nowait(AgentEvent(ts=0.0, source="seed", message="seed"))
    full_buffer = deque([AgentEvent(ts=0.5, source="seed", message="buffered")], maxlen=1)

    bus._subscribers = {7: full_q}
    bus._buffered_events = {7: full_buffer}

    bus._fanout_local(AgentEvent(ts=1.0, source="x", message="drop-me"))

    assert 7 not in bus._subscribers
    assert 7 not in bus._buffered_events

def test_ensure_listener_busygroup_and_publish_success_and_cleanup_cancel(monkeypatch):
    bus = AgentEventBus()

    class _FakeRedis:
        async def ping(self):
            return True

        async def xgroup_create(self, **_kwargs):
            raise _event_stream.ResponseError("BUSYGROUP Consumer Group name already exists")

        async def xadd(self, *_args, **_kwargs):
            return "1-0"

        async def close(self):
            return None

    class _DoneFalseTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            async def _inner():
                return None

            return _inner().__await__()

    fake_listener_task = _DoneFalseTask()
    monkeypatch.setattr(_event_stream.Redis, "from_url", lambda *_a, **_k: _FakeRedis())
    monkeypatch.setattr(asyncio, "create_task", lambda _coro: (_coro.close(), fake_listener_task)[1])

    asyncio.run(bus._ensure_redis_listener())
    assert bus._redis_available is True
    assert bus._redis_listener_task is fake_listener_task

    ok = asyncio.run(bus._publish_via_redis(AgentEvent(ts=1.0, source="s", message="m")))
    assert ok is True

    asyncio.run(bus._cleanup_redis())
    assert fake_listener_task.cancelled is True
    assert bus._redis_client is None


def test_ensure_listener_returns_early_when_disabled_or_already_running():
    bus = AgentEventBus()
    bus._redis_available = False
    asyncio.run(bus._ensure_redis_listener())

    bus2 = AgentEventBus()

    class _Task:
        def done(self):
            return False

    bus2._redis_listener_task = _Task()
    asyncio.run(bus2._ensure_redis_listener())

def test_publish_skips_redis_when_bootstrap_marks_it_unavailable(monkeypatch):
    bus = AgentEventBus()

    async def _ensure():
        bus._redis_available = False

    bus._redis_available = None
    monkeypatch.setattr(bus, "_ensure_redis_listener", _ensure)

    ok = asyncio.run(bus._publish_via_redis(AgentEvent(ts=1.0, source="s", message="m")))
    assert ok is False
    assert bus._redis_client is None