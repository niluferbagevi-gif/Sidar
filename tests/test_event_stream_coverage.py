from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from collections import deque
from types import SimpleNamespace

if "redis" not in sys.modules and importlib.util.find_spec("redis") is None:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")

    class _Redis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    fake_redis_asyncio.Redis = _Redis

    fake_redis_exceptions = types.ModuleType("redis.exceptions")

    class _ResponseError(Exception):
        pass

    fake_redis_exceptions.ResponseError = _ResponseError

    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_redis_asyncio
    fake_redis.exceptions = fake_redis_exceptions
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio
    sys.modules["redis.exceptions"] = fake_redis_exceptions

from redis.exceptions import ResponseError

from agent.core import event_stream


def _evt(msg: str = "m") -> event_stream.AgentEvent:
    return event_stream.AgentEvent(ts=1.0, source="agent", message=msg)


def test_subscribe_unsubscribe_and_get_bus_singleton() -> None:
    bus = event_stream.AgentEventBus()
    bus._schedule_redis_bootstrap = lambda: None

    sub_id, queue = bus.subscribe(maxsize=1)
    assert queue.maxsize == 10
    assert sub_id in bus._subscribers

    bus.unsubscribe(sub_id)
    assert sub_id not in bus._subscribers
    assert event_stream.get_agent_event_bus() is event_stream._BUS


def test_schedule_bootstrap_guard_paths(monkeypatch) -> None:
    bus = event_stream.AgentEventBus()
    bus._redis_available = False
    bus._schedule_redis_bootstrap()

    bus._redis_available = None
    bus._redis_bootstrap_task = SimpleNamespace(done=lambda: False)
    bus._schedule_redis_bootstrap()

    bus._redis_bootstrap_task = None
    monkeypatch.setattr(event_stream.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    bus._schedule_redis_bootstrap()


def test_fanout_local_buffers_or_drops_when_queue_full() -> None:
    bus = event_stream.AgentEventBus()
    sid_a, q_a = 1, asyncio.Queue(maxsize=1)
    sid_b, q_b = 2, asyncio.Queue(maxsize=1)
    q_a.put_nowait(_evt("filled-a"))
    q_b.put_nowait(_evt("filled-b"))

    bus._subscribers = {sid_a: q_a, sid_b: q_b}
    bus._buffered_events[sid_a] = deque(maxlen=2)

    bus._fanout_local(_evt("incoming"))

    assert len(bus._buffered_events[sid_a]) == 1
    assert sid_b not in bus._subscribers


def test_drain_buffered_events_once_progress_and_full_queue() -> None:
    bus = event_stream.AgentEventBus()
    sid_a, q_a = 1, asyncio.Queue(maxsize=1)
    sid_b, q_b = 2, asyncio.Queue(maxsize=1)
    q_b.put_nowait(_evt("already-full"))

    bus._subscribers = {sid_a: q_a, sid_b: q_b}
    bus._buffered_events = {sid_a: deque([_evt("buf")], maxlen=2), sid_b: deque([_evt("buf2")], maxlen=2)}

    progressed = asyncio.run(bus._drain_buffered_events_once())

    assert progressed is True
    assert q_a.get_nowait().message == "buf"
    assert len(bus._buffered_events[sid_b]) == 1


def test_publish_calls_local_and_redis_paths(monkeypatch) -> None:
    bus = event_stream.AgentEventBus()
    called = {"fanout": 0, "bootstrap": 0, "publish": 0}

    bus._fanout_local = lambda _evt: called.__setitem__("fanout", called["fanout"] + 1)
    bus._schedule_redis_bootstrap = lambda: called.__setitem__("bootstrap", called["bootstrap"] + 1)

    async def _fake_publish(_evt):
        called["publish"] += 1
        return True

    bus._publish_via_redis = _fake_publish

    asyncio.run(bus.publish("x", "y"))

    assert called == {"fanout": 1, "bootstrap": 1, "publish": 1}


def test_publish_via_redis_short_circuit_and_success() -> None:
    bus = event_stream.AgentEventBus()
    bus._redis_available = False
    assert asyncio.run(bus._publish_via_redis(_evt())) is False

    class _Redis:
        def __init__(self):
            self.calls = []

        async def xadd(self, channel, payload):
            self.calls.append((channel, payload))

    client = _Redis()
    bus._redis_client = client
    bus._redis_available = True

    async def _noop_listener():
        return None

    bus._ensure_redis_listener = _noop_listener

    assert asyncio.run(bus._publish_via_redis(_evt("ok"))) is True
    assert client.calls and client.calls[0][0] == bus._channel


def test_publish_via_redis_failure_writes_dlq_and_cleans_up() -> None:
    bus = event_stream.AgentEventBus()

    class _Redis:
        async def xadd(self, *_args, **_kwargs):
            raise RuntimeError("xadd failed")

    bus._redis_client = _Redis()
    bus._redis_available = True

    async def _noop_listener():
        return None

    writes = []
    cleaned = {"value": False}

    async def _fake_dlq(**kwargs):
        writes.append(kwargs)

    async def _fake_cleanup():
        cleaned["value"] = True

    bus._ensure_redis_listener = _noop_listener
    bus._write_dead_letter = _fake_dlq
    bus._cleanup_redis = _fake_cleanup

    ok = asyncio.run(bus._publish_via_redis(_evt("boom")))

    assert ok is False
    assert bus._redis_available is False
    assert writes and writes[0]["reason"] == "publish_failed"
    assert cleaned["value"] is True


def test_ensure_redis_listener_bootstrap_success_with_busygroup(monkeypatch) -> None:
    bus = event_stream.AgentEventBus()

    class _Redis:
        async def ping(self):
            return True

        async def xgroup_create(self, **_kwargs):
            raise ResponseError("BUSYGROUP Consumer Group name already exists")

    monkeypatch.setattr(event_stream.Redis, "from_url", lambda *_args, **_kwargs: _Redis())

    recorded = {"started": False}

    async def _fake_listener_loop():
        recorded["started"] = True

    bus._redis_listener_loop = _fake_listener_loop

    task = None
    try:
        async def _runner():
            await bus._ensure_redis_listener()
            return bus._redis_listener_task

        task = asyncio.run(_runner())
        assert bus._redis_available is True
        assert task is not None
    finally:
        if task is not None:
            asyncio.run(_cancel_task(task))


async def _cancel_task(task):
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_ensure_redis_listener_failure_sets_fallback(monkeypatch) -> None:
    bus = event_stream.AgentEventBus()

    class _Redis:
        async def ping(self):
            return True

        async def xgroup_create(self, **_kwargs):
            raise ResponseError("NOPE")

    monkeypatch.setattr(event_stream.Redis, "from_url", lambda *_args, **_kwargs: _Redis())
    cleaned = {"value": False}

    async def _fake_cleanup():
        cleaned["value"] = True

    bus._cleanup_redis = _fake_cleanup

    asyncio.run(bus._ensure_redis_listener())

    assert bus._redis_available is False
    assert cleaned["value"] is True


def test_redis_listener_loop_processes_payload_invalid_payload_and_ack_failure() -> None:
    bus = event_stream.AgentEventBus()
    bus._instance_id = "self"

    remote_payload = json.dumps({"sid": "other", "ts": 9.0, "source": "remote", "message": "hello"})
    calls = {"n": 0}

    class _Redis:
        async def xreadgroup(self, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return [
                    (
                        "stream",
                        [
                            ("1-0", {"payload": remote_payload}),
                            ("2-0", {"payload": "{"}),
                        ],
                    )
                ]
            raise RuntimeError("stop loop")

        async def xack(self, *_args, **_kwargs):
            raise RuntimeError("ack failed")

    bus._redis_client = _Redis()

    delivered = []
    dlq = []

    bus._fanout_local = lambda evt: delivered.append(evt)

    async def _fake_dlq(**kwargs):
        dlq.append(kwargs)

    cleaned = {"value": False}

    async def _fake_cleanup():
        cleaned["value"] = True

    bus._write_dead_letter = _fake_dlq
    bus._cleanup_redis = _fake_cleanup

    asyncio.run(bus._redis_listener_loop())

    assert delivered and delivered[0].message == "hello"
    reasons = [item["reason"] for item in dlq]
    assert "invalid_payload" in reasons
    assert "ack_failed" in reasons
    assert bus._redis_available is False
    assert cleaned["value"] is True


def test_cleanup_redis_closes_listener_and_client_paths() -> None:
    bus = event_stream.AgentEventBus()

    async def _never():
        await asyncio.sleep(1)

    async def _runner():
        bus._redis_listener_task = asyncio.create_task(_never())

        class _Client:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True

        client = _Client()
        bus._redis_client = client
        await bus._cleanup_redis()
        return client

    client = asyncio.run(_runner())

    assert client.closed is True
    assert bus._redis_listener_task is None
    assert bus._redis_client is None


def test_write_dead_letter_local_and_redis_failure_path() -> None:
    bus = event_stream.AgentEventBus()

    asyncio.run(bus._write_dead_letter(reason="local_only", payload={"a": 1}, error=RuntimeError("err")))
    assert bus._dlq_buffer and bus._dlq_buffer[-1]["reason"] == "local_only"
    assert "error" in bus._dlq_buffer[-1]

    class _Redis:
        async def xadd(self, *_args, **_kwargs):
            raise RuntimeError("dlq down")

    bus._redis_client = _Redis()
    bus._redis_available = True
    asyncio.run(bus._write_dead_letter(reason="redis_path", payload={"b": 2}))
    assert bus._dlq_buffer[-1]["reason"] == "redis_path"
