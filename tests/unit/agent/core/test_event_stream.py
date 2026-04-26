from __future__ import annotations

import asyncio
import json
import sys
import time
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
from agent.core.event_stream import AgentEvent, AgentEventBus, BaseEventBusBackend, get_agent_event_bus


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


class DummyRabbitIncoming:
    def __init__(self, body: bytes, *, ack_raises: bool = False) -> None:
        self.body = body
        self.acked = False
        self._ack_raises = ack_raises

    async def ack(self) -> None:
        self.acked = True
        if self._ack_raises:
            raise RuntimeError("rabbit ack failed")


class DummyRabbitIterator:
    def __init__(self, items: list[DummyRabbitIncoming]) -> None:
        self._items = list(items)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
        return False

    def __aiter__(self):
        return self

    async def __anext__(self) -> DummyRabbitIncoming:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class DummyRabbitQueue:
    def __init__(self, items: list[DummyRabbitIncoming] | None = None) -> None:
        self._items = items or []

    def iterator(self) -> DummyRabbitIterator:
        return DummyRabbitIterator(self._items)


class DummyRabbitExchange:
    def __init__(self) -> None:
        self.published: list[tuple[object, str]] = []
        self.raise_on_publish = False

    async def publish(self, message, routing_key: str) -> None:
        if self.raise_on_publish:
            raise RuntimeError("rabbit publish failed")
        self.published.append((message, routing_key))


class DummyRabbitChannel:
    def __init__(self, queue: DummyRabbitQueue | None = None) -> None:
        self.default_exchange = DummyRabbitExchange()
        self.queue = queue or DummyRabbitQueue()
        self.closed = False

    async def declare_queue(self, _name: str, durable: bool = True) -> DummyRabbitQueue:
        assert durable is True
        return self.queue

    async def close(self) -> None:
        self.closed = True


class DummyRabbitConnection:
    def __init__(self, channel: DummyRabbitChannel | None = None) -> None:
        self._channel = channel or DummyRabbitChannel()
        self.closed = False

    async def channel(self) -> DummyRabbitChannel:
        return self._channel

    async def close(self) -> None:
        self.closed = True


class DummyKafkaMessage:
    def __init__(self, value: bytes) -> None:
        self.value = value


class DummyKafkaProducer:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, bytes]] = []
        self.raise_on_send = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, payload: bytes) -> None:
        if self.raise_on_send:
            raise RuntimeError("kafka publish failed")
        self.sent.append((topic, payload))


class DummyKafkaConsumer:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.messages: list[object] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def getone(self):
        if not self.messages:
            await asyncio.sleep(0)
            return DummyKafkaMessage(b"{}")
        item = self.messages.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


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


def test_ensure_redis_loop_compatibility_returns_for_non_redis_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._backend = "kafka"
    bus._redis_client = DummyRedis()
    bus._redis_loop = object()
    bus._redis_available = True

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_cleanup_redis", _cleanup)
    asyncio.run(bus._ensure_redis_loop_compatibility())

    assert cleaned["ok"] is False
    assert bus._redis_available is True
    assert bus._redis_client is not None


def test_ensure_redis_loop_compatibility_returns_without_client_and_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._redis_client = None
    bus._redis_listener_task = None

    called = {"get_loop": False}

    def _get_loop():
        called["get_loop"] = True
        return object()

    monkeypatch.setattr(asyncio, "get_running_loop", _get_loop)
    asyncio.run(bus._ensure_redis_loop_compatibility())

    assert called["get_loop"] is False
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


@pytest.mark.asyncio
async def test_write_dead_letter_without_error_keeps_item_minimal(bus: AgentEventBus) -> None:
    await bus._write_dead_letter(reason="no_error", payload={"kind": "minimal"}, error=None)

    assert len(bus._dlq_buffer) == 1
    last_item = bus._dlq_buffer[-1]
    assert last_item["reason"] == "no_error"
    assert last_item["payload"] == {"kind": "minimal"}
    assert "error" not in last_item


@pytest.mark.asyncio
async def test_write_dead_letter_skips_redis_write_when_backend_redis_but_unavailable(bus: AgentEventBus) -> None:
    bus._backend = "redis"
    bus._redis_available = False
    bus._redis_client = DummyRedis()

    await bus._write_dead_letter(reason="redis_unavailable", payload={"case": "no_xadd"})

    assert len(bus._dlq_buffer) == 1
    assert bus._dlq_buffer[-1]["reason"] == "redis_unavailable"
    assert bus._redis_client.xadd_calls == []


@pytest.mark.asyncio
async def test_write_dead_letter_persists_to_jsonl_when_path_configured(bus: AgentEventBus, tmp_path) -> None:
    persist_path = tmp_path / "dlq.jsonl"
    bus._dlq_persist_path = str(persist_path)

    await bus._write_dead_letter(reason="persisted", payload={"kind": "io"})

    lines = persist_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["dropped_from_memory"] is False
    assert record["item"]["reason"] == "persisted"
    assert record["item"]["payload"] == {"kind": "io"}


@pytest.mark.asyncio
async def test_write_dead_letter_persistence_runs_via_to_thread(
    bus: AgentEventBus, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persist_path = tmp_path / "dlq_to_thread.jsonl"
    bus._dlq_persist_path = str(persist_path)
    calls: list[str] = []

    async def _to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(event_stream.asyncio, "to_thread", _to_thread)

    await bus._write_dead_letter(reason="threaded", payload={"kind": "offload"})

    assert calls == ["_persist_dead_letter_item_sync"]
    line = persist_path.read_text(encoding="utf-8").strip()
    assert json.loads(line)["item"]["reason"] == "threaded"


@pytest.mark.asyncio
async def test_write_dead_letter_persists_oldest_item_when_memory_buffer_overflows(bus: AgentEventBus, tmp_path) -> None:
    persist_path = tmp_path / "dlq_overflow.jsonl"
    bus._dlq_persist_path = str(persist_path)
    bus._dlq_buffer = deque(maxlen=2)

    await bus._write_dead_letter(reason="first", payload={"n": 1})
    await bus._write_dead_letter(reason="second", payload={"n": 2})
    await bus._write_dead_letter(reason="third", payload={"n": 3})

    lines = persist_path.read_text(encoding="utf-8").strip().splitlines()
    # first + second + dropped(first) marker + third
    assert len(lines) == 4
    records = [json.loads(line) for line in lines]

    dropped_records = [r for r in records if r["dropped_from_memory"] is True]
    assert len(dropped_records) == 1
    assert dropped_records[0]["item"]["reason"] == "first"

    assert [x["reason"] for x in bus._dlq_buffer] == ["second", "third"]


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


def test_schedule_remote_bootstrap_routes_by_backend(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    calls = {"redis": 0, "rabbitmq": 0, "kafka": 0}
    monkeypatch.setattr(bus, "_schedule_redis_bootstrap", lambda: calls.__setitem__("redis", calls["redis"] + 1))
    monkeypatch.setattr(bus, "_schedule_rabbit_bootstrap", lambda: calls.__setitem__("rabbitmq", calls["rabbitmq"] + 1))
    monkeypatch.setattr(bus, "_schedule_kafka_bootstrap", lambda: calls.__setitem__("kafka", calls["kafka"] + 1))

    bus._backend = "rabbitmq"
    bus._schedule_remote_bootstrap()
    bus._backend = "kafka"
    bus._schedule_remote_bootstrap()
    bus._backend = "redis"
    bus._schedule_remote_bootstrap()

    assert calls == {"redis": 1, "rabbitmq": 1, "kafka": 1}


def test_event_bus_uses_backend_strategy_instances(bus: AgentEventBus) -> None:
    assert isinstance(bus._backends["redis"], BaseEventBusBackend)
    assert isinstance(bus._backends["rabbitmq"], BaseEventBusBackend)
    assert isinstance(bus._backends["kafka"], BaseEventBusBackend)


def test_schedule_rabbit_kafka_bootstrap_variants(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    bus._rabbit_available = False
    bus._schedule_rabbit_bootstrap()
    assert bus._rabbit_bootstrap_task is None

    bus._kafka_available = False
    bus._schedule_kafka_bootstrap()
    assert bus._kafka_bootstrap_task is None

    class _RunningTask:
        def done(self) -> bool:
            return False

    bus._rabbit_available = None
    bus._rabbit_bootstrap_task = _RunningTask()
    bus._schedule_rabbit_bootstrap()
    assert isinstance(bus._rabbit_bootstrap_task, _RunningTask)

    bus._kafka_available = None
    bus._kafka_bootstrap_task = _RunningTask()
    bus._schedule_kafka_bootstrap()
    assert isinstance(bus._kafka_bootstrap_task, _RunningTask)

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    bus._rabbit_bootstrap_task = None
    bus._kafka_bootstrap_task = None
    bus._schedule_rabbit_bootstrap()
    bus._schedule_kafka_bootstrap()
    assert bus._rabbit_bootstrap_task is None
    assert bus._kafka_bootstrap_task is None

    created = {"rabbit": None, "kafka": None}

    class _Loop:
        def create_task(self, coro):
            if "rabbit" in repr(coro):
                coro.close()
                created["rabbit"] = object()
                return created["rabbit"]
            coro.close()
            created["kafka"] = object()
            return created["kafka"]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _Loop())
    bus._rabbit_available = None
    bus._kafka_available = None
    bus._schedule_rabbit_bootstrap()
    bus._schedule_kafka_bootstrap()
    assert bus._rabbit_bootstrap_task is created["rabbit"]
    assert bus._kafka_bootstrap_task is created["kafka"]


def test_ensure_rabbit_listener_success_and_failure(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    connection = DummyRabbitConnection()

    class _AioPika:
        @staticmethod
        async def connect_robust(_url: str):
            return connection

    created = {"task": None}

    def _create_task(coro):
        coro.close()
        created["task"] = object()
        return created["task"]

    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _AioPika)
    monkeypatch.setattr(asyncio, "create_task", _create_task)
    asyncio.run(bus._ensure_rabbit_listener())
    assert bus._rabbit_available is True
    assert bus._rabbit_connection is connection
    assert bus._rabbit_listener_task is created["task"]

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    async def _broken_connect(_url: str):
        raise RuntimeError("rabbit connect failed")

    class _BrokenAioPika:
        connect_robust = staticmethod(_broken_connect)

    bus._rabbit_listener_task = None
    bus._rabbit_connection = None
    bus._rabbit_available = None
    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _BrokenAioPika)
    monkeypatch.setattr(bus, "_cleanup_rabbit", _cleanup)
    asyncio.run(bus._ensure_rabbit_listener())
    assert bus._rabbit_available is False
    assert cleaned["ok"] is True


def test_ensure_rabbit_listener_handles_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus
) -> None:
    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(
        event_stream.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'aio_pika'")),
    )
    monkeypatch.setattr(bus, "_cleanup_rabbit", _cleanup)

    asyncio.run(bus._ensure_rabbit_listener())
    assert bus._rabbit_available is False
    assert cleaned["ok"] is True


def test_ensure_kafka_listener_success_and_failure(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    class _AioKafka:
        AIOKafkaProducer = DummyKafkaProducer
        AIOKafkaConsumer = DummyKafkaConsumer

    created = {"task": None}

    def _create_task(coro):
        coro.close()
        created["task"] = object()
        return created["task"]

    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _AioKafka)
    monkeypatch.setattr(asyncio, "create_task", _create_task)
    asyncio.run(bus._ensure_kafka_listener())
    assert bus._kafka_available is True
    assert bus._kafka_listener_task is created["task"]
    assert bus._kafka_producer.started is True
    assert bus._kafka_consumer.started is True

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    class _BrokenProducer(DummyKafkaProducer):
        async def start(self) -> None:
            raise RuntimeError("kafka producer failed")

    class _BrokenAioKafka:
        AIOKafkaProducer = _BrokenProducer
        AIOKafkaConsumer = DummyKafkaConsumer

    bus._kafka_listener_task = None
    bus._kafka_producer = None
    bus._kafka_consumer = None
    bus._kafka_available = None
    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _BrokenAioKafka)
    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup)
    asyncio.run(bus._ensure_kafka_listener())
    assert bus._kafka_available is False
    assert cleaned["ok"] is True


def test_ensure_kafka_listener_handles_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus
) -> None:
    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(
        event_stream.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'aiokafka'")),
    )
    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup)

    asyncio.run(bus._ensure_kafka_listener())
    assert bus._kafka_available is False
    assert cleaned["ok"] is True


def test_rabbit_connection_failure_switches_to_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._backend = "rabbitmq"

    async def _broken_connect(_url: str):
        raise RuntimeError("rabbit unavailable")

    class _BrokenAioPika:
        connect_robust = staticmethod(_broken_connect)

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _BrokenAioPika)
    monkeypatch.setattr(bus, "_cleanup_rabbit", _cleanup)
    monkeypatch.setattr(bus, "_schedule_remote_bootstrap", lambda: None)

    async def _scenario() -> None:
        await bus._ensure_rabbit_listener()
        assert bus._rabbit_available is False
        sub_id, queue = bus.subscribe()
        await bus.publish("qa", "rabbit fallback")
        evt = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert evt.source == "qa"
        assert evt.message == "rabbit fallback"
        bus.unsubscribe(sub_id)

    asyncio.run(_scenario())
    assert cleaned["ok"] is True


def test_kafka_connection_failure_switches_to_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = AgentEventBus()
    bus._backend = "kafka"

    class _BrokenProducer(DummyKafkaProducer):
        async def start(self) -> None:
            raise RuntimeError("kafka unavailable")

    class _BrokenAioKafka:
        AIOKafkaProducer = _BrokenProducer
        AIOKafkaConsumer = DummyKafkaConsumer

    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _BrokenAioKafka)
    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup)
    monkeypatch.setattr(bus, "_schedule_remote_bootstrap", lambda: None)

    async def _scenario() -> None:
        await bus._ensure_kafka_listener()
        assert bus._kafka_available is False
        sub_id, queue = bus.subscribe()
        await bus.publish("qa", "kafka fallback")
        evt = await asyncio.wait_for(queue.get(), timeout=0.2)
        assert evt.source == "qa"
        assert evt.message == "kafka fallback"
        bus.unsubscribe(sub_id)

    asyncio.run(_scenario())
    assert cleaned["ok"] is True


def test_publish_via_rabbit_and_kafka_paths(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    evt = AgentEvent(ts=1.0, source="qa", message="event")

    bus._rabbit_available = False
    assert asyncio.run(bus._publish_via_rabbit(evt)) is False

    bus._rabbit_available = True
    bus._rabbit_channel = None
    monkeypatch.setattr(bus, "_ensure_rabbit_listener", lambda: asyncio.sleep(0))
    assert asyncio.run(bus._publish_via_rabbit(evt)) is False

    bus._rabbit_available = None
    monkeypatch.setattr(bus, "_ensure_rabbit_listener", lambda: asyncio.sleep(0))
    assert asyncio.run(bus._publish_via_rabbit(evt)) is False

    queue = DummyRabbitQueue()
    channel = DummyRabbitChannel(queue)
    bus._rabbit_channel = channel
    bus._rabbit_available = None

    class _AioPika:
        class Message:
            def __init__(self, body: bytes, content_type: str) -> None:
                self.body = body
                self.content_type = content_type

    monkeypatch.setattr(event_stream.importlib, "import_module", lambda _name: _AioPika)
    monkeypatch.setattr(bus, "_ensure_rabbit_listener", lambda: asyncio.sleep(0))
    bus._rabbit_available = True
    assert asyncio.run(bus._publish_via_rabbit(evt)) is True
    published_message, published_routing_key = channel.default_exchange.published[0]
    assert published_routing_key == bus._channel
    parsed_rabbit_payload = json.loads(published_message.body.decode("utf-8"))
    assert parsed_rabbit_payload["sid"] == bus._instance_id
    assert parsed_rabbit_payload["source"] == "qa"
    assert parsed_rabbit_payload["message"] == "event"
    assert published_message.content_type == "application/json"

    channel.default_exchange.raise_on_publish = True
    written: list[dict] = []
    cleaned = {"rabbit": False, "kafka": False}

    async def _dlq(**kwargs):
        written.append(kwargs)

    async def _cleanup_rabbit() -> None:
        cleaned["rabbit"] = True

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    monkeypatch.setattr(bus, "_cleanup_rabbit", _cleanup_rabbit)
    assert asyncio.run(bus._publish_via_rabbit(evt)) is False
    assert bus._rabbit_available is False
    assert cleaned["rabbit"] is True
    assert written[-1]["reason"] == "publish_failed"

    bus._kafka_available = False
    assert asyncio.run(bus._publish_via_kafka(evt)) is False
    bus._kafka_available = None
    monkeypatch.setattr(bus, "_ensure_kafka_listener", lambda: asyncio.sleep(0))
    assert asyncio.run(bus._publish_via_kafka(evt)) is False

    producer = DummyKafkaProducer()
    bus._kafka_producer = producer
    bus._kafka_available = True
    assert asyncio.run(bus._publish_via_kafka(evt)) is True
    kafka_topic, kafka_raw_payload = producer.sent[0]
    assert kafka_topic == bus._kafka_topic
    parsed_kafka_payload = json.loads(kafka_raw_payload.decode("utf-8"))
    assert parsed_kafka_payload["sid"] == bus._instance_id
    assert parsed_kafka_payload["source"] == "qa"
    assert parsed_kafka_payload["message"] == "event"

    producer.raise_on_send = True

    async def _cleanup_kafka() -> None:
        cleaned["kafka"] = True

    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup_kafka)
    assert asyncio.run(bus._publish_via_kafka(evt)) is False
    assert bus._kafka_available is False
    assert cleaned["kafka"] is True
    assert written[-1]["reason"] == "publish_failed"


def test_publish_via_kafka_failure_writes_dlq_and_cleans_up(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    evt = AgentEvent(ts=7.5, source="coverage", message="kafka fail-safe")
    producer = DummyKafkaProducer()
    producer.raise_on_send = True
    bus._kafka_available = True
    bus._kafka_producer = producer

    monkeypatch.setattr(bus, "_ensure_kafka_listener", lambda: asyncio.sleep(0))

    dlq_entries: list[dict] = []
    cleaned = {"ok": False}

    async def _dlq(**kwargs):
        dlq_entries.append(kwargs)

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup)

    assert asyncio.run(bus._publish_via_kafka(evt)) is False
    assert bus._kafka_available is False
    assert cleaned["ok"] is True
    assert len(dlq_entries) == 1
    assert dlq_entries[0]["reason"] == "publish_failed"
    assert dlq_entries[0]["payload"]["event"]["source"] == "coverage"
    assert dlq_entries[0]["payload"]["event"]["message"] == "kafka fail-safe"


def test_publish_via_rabbit_missing_dependency_writes_dlq_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus
) -> None:
    evt = AgentEvent(ts=2.5, source="resilience", message="rabbit missing module")
    bus._rabbit_available = True
    bus._rabbit_channel = DummyRabbitChannel(DummyRabbitQueue())

    monkeypatch.setattr(bus, "_ensure_rabbit_listener", lambda: asyncio.sleep(0))
    monkeypatch.setattr(
        event_stream.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'aio_pika'")),
    )

    dlq_entries: list[dict] = []
    cleaned = {"ok": False}

    async def _dlq(**kwargs):
        dlq_entries.append(kwargs)

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    monkeypatch.setattr(bus, "_cleanup_rabbit", _cleanup)

    assert asyncio.run(bus._publish_via_rabbit(evt)) is False
    assert bus._rabbit_available is False
    assert cleaned["ok"] is True
    assert dlq_entries[0]["reason"] == "publish_failed"


def test_publish_via_remote_routes(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    evt = AgentEvent(ts=1.0, source="coder", message="route")
    called = {"redis": 0, "rabbit": 0, "kafka": 0}

    async def _redis(_evt: AgentEvent) -> bool:
        called["redis"] += 1
        return True

    async def _rabbit(_evt: AgentEvent) -> bool:
        called["rabbit"] += 1
        return True

    async def _kafka(_evt: AgentEvent) -> bool:
        called["kafka"] += 1
        return True

    monkeypatch.setattr(bus, "_publish_via_redis", _redis)
    monkeypatch.setattr(bus, "_publish_via_rabbit", _rabbit)
    monkeypatch.setattr(bus, "_publish_via_kafka", _kafka)

    bus._backend = "rabbitmq"
    assert asyncio.run(bus._publish_via_remote(evt)) is True
    bus._backend = "kafka"
    assert asyncio.run(bus._publish_via_remote(evt)) is True
    bus._backend = "redis"
    assert asyncio.run(bus._publish_via_remote(evt)) is True
    assert called == {"redis": 1, "rabbit": 1, "kafka": 1}


def test_publish_via_remote_opens_circuit_after_threshold_failures(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    evt = AgentEvent(ts=1.0, source="qa", message="circuit")
    bus._backend = "redis"
    bus._remote_circuit_failure_threshold = 2
    bus._remote_circuit_open_seconds = 30.0
    called = {"redis": 0}

    async def _redis(_evt: AgentEvent) -> bool:
        called["redis"] += 1
        return False

    monkeypatch.setattr(bus, "_publish_via_redis", _redis)

    assert asyncio.run(bus._publish_via_remote(evt)) is False
    assert bus._remote_circuit_consecutive_failures == 1
    assert bus._remote_circuit_open_until == 0.0

    assert asyncio.run(bus._publish_via_remote(evt)) is False
    assert bus._remote_circuit_consecutive_failures == 2
    assert bus._remote_circuit_open_until > time.time()

    assert asyncio.run(bus._publish_via_remote(evt)) is False
    assert called["redis"] == 2


def test_publish_via_remote_resets_circuit_after_success(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    evt = AgentEvent(ts=1.0, source="qa", message="recover")
    bus._backend = "kafka"
    bus._remote_circuit_failure_threshold = 2
    bus._remote_circuit_open_seconds = 60.0
    bus._remote_circuit_consecutive_failures = 1

    async def _kafka(_evt: AgentEvent) -> bool:
        return True

    monkeypatch.setattr(bus, "_publish_via_kafka", _kafka)

    assert asyncio.run(bus._publish_via_remote(evt)) is True
    assert bus._remote_circuit_consecutive_failures == 0
    assert bus._remote_circuit_open_until == 0.0


def test_publish_skips_remote_bootstrap_when_circuit_open(bus: AgentEventBus, monkeypatch: pytest.MonkeyPatch) -> None:
    bus._backend = "redis"
    bus._remote_circuit_open_until = time.time() + 60.0
    calls = {"schedule": 0, "publish_remote": 0}

    monkeypatch.setattr(bus, "_fanout_local", lambda _evt: None)
    monkeypatch.setattr(bus, "_schedule_remote_bootstrap", lambda: calls.__setitem__("schedule", calls["schedule"] + 1))

    async def _publish_remote(_evt: AgentEvent) -> bool:
        calls["publish_remote"] += 1
        return False

    monkeypatch.setattr(bus, "_publish_via_remote", _publish_remote)

    asyncio.run(bus.publish(source="qa", message="skip"))

    assert calls["schedule"] == 0
    assert calls["publish_remote"] == 1


def test_rabbit_listener_loop_variants(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    bus._rabbit_queue = None
    assert asyncio.run(bus._rabbit_listener_loop()) is None

    valid_other = DummyRabbitIncoming(json.dumps({"sid": "other", "ts": 2, "source": "r", "message": "ok"}).encode("utf-8"))
    valid_self = DummyRabbitIncoming(
        json.dumps({"sid": bus._instance_id, "ts": 3, "source": "r", "message": "ignore"}).encode("utf-8")
    )
    invalid = DummyRabbitIncoming(b"{bad-json", ack_raises=True)
    bus._rabbit_queue = DummyRabbitQueue([valid_other, invalid, valid_self])

    fanouts: list[AgentEvent] = []
    dlq_entries: list[dict] = []

    monkeypatch.setattr(bus, "_fanout_local", lambda evt: fanouts.append(evt))

    async def _dlq(**kwargs):
        dlq_entries.append(kwargs)

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    asyncio.run(bus._rabbit_listener_loop())
    assert len(fanouts) == 1
    assert fanouts[0].source == "r"
    assert fanouts[0].message == "ok"
    assert dlq_entries[0]["reason"] == "invalid_payload"
    assert "{bad-json" in dlq_entries[0]["payload"]["payload"]
    assert valid_other.acked is True


def test_kafka_listener_loop_variants(monkeypatch: pytest.MonkeyPatch, bus: AgentEventBus) -> None:
    bus._kafka_consumer = None
    assert asyncio.run(bus._kafka_listener_loop()) is None

    consumer = DummyKafkaConsumer()
    consumer.messages = [RuntimeError("consume failed")]
    bus._kafka_consumer = consumer
    bus._kafka_available = True
    cleaned = {"ok": False}

    async def _cleanup() -> None:
        cleaned["ok"] = True

    monkeypatch.setattr(bus, "_cleanup_kafka", _cleanup)
    asyncio.run(bus._kafka_listener_loop())
    assert bus._kafka_available is False
    assert cleaned["ok"] is True

    consumer = DummyKafkaConsumer()
    consumer.messages = [
        DummyKafkaMessage(json.dumps({"sid": "other", "ts": 4, "source": "k", "message": "ok"}).encode("utf-8")),
        DummyKafkaMessage(b"{bad-json"),
        DummyKafkaMessage(json.dumps({"sid": bus._instance_id, "ts": 5, "source": "k", "message": "ignore"}).encode("utf-8")),
        asyncio.CancelledError(),
    ]
    bus._kafka_consumer = consumer
    bus._kafka_available = True
    fanouts: list[AgentEvent] = []
    dlq_entries: list[dict] = []
    monkeypatch.setattr(bus, "_fanout_local", lambda evt: fanouts.append(evt))

    async def _dlq(**kwargs):
        dlq_entries.append(kwargs)

    monkeypatch.setattr(bus, "_write_dead_letter", _dlq)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bus._kafka_listener_loop())
    assert len(fanouts) == 1
    assert fanouts[0].source == "k"
    assert fanouts[0].message == "ok"
    assert dlq_entries[0]["reason"] == "invalid_payload"
    assert "{bad-json" in dlq_entries[0]["payload"]["payload"]


def test_cleanup_rabbit_and_kafka() -> None:
    bus = AgentEventBus()

    class _AwaitableTask:
        def __init__(self) -> None:
            self.cancel_called = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancel_called = True

        def __await__(self):
            async def _inner():
                raise asyncio.CancelledError()

            return _inner().__await__()

    rabbit_task = _AwaitableTask()
    bus._rabbit_listener_task = rabbit_task
    rabbit_connection = DummyRabbitConnection()
    rabbit_channel = awaitable_channel = rabbit_connection._channel
    bus._rabbit_channel = rabbit_channel
    bus._rabbit_connection = rabbit_connection
    asyncio.run(bus._cleanup_rabbit())
    assert rabbit_task.cancel_called is True
    assert bus._rabbit_listener_task is None
    assert bus._rabbit_channel is None
    assert bus._rabbit_connection is None
    assert awaitable_channel.closed is True
    assert rabbit_connection.closed is True

    kafka_task = _AwaitableTask()
    bus._kafka_listener_task = kafka_task
    producer = DummyKafkaProducer()
    consumer = DummyKafkaConsumer()
    bus._kafka_producer = producer
    bus._kafka_consumer = consumer
    asyncio.run(bus._cleanup_kafka())
    assert kafka_task.cancel_called is True
    assert bus._kafka_listener_task is None
    assert bus._kafka_producer is None
    assert bus._kafka_consumer is None
    assert producer.stopped is True
    assert consumer.stopped is True
