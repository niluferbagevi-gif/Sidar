"""
agent/core/event_stream.py için birim testleri.
Redis bağımlılıkları stub'lanır; yerel fallback yolu test edilir.
"""
from __future__ import annotations

import asyncio
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_event_stream_deps():
    """redis stub'ı oluşturur."""
    # agent package stub
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg
    if "agent.core" not in sys.modules:
        core_pkg = types.ModuleType("agent.core")
        core_pkg.__path__ = [str(_proj / "agent" / "core")]
        core_pkg.__package__ = "agent.core"
        sys.modules["agent.core"] = core_pkg
    else:
        core_pkg = sys.modules["agent.core"]
        if not hasattr(core_pkg, "__path__"):
            core_pkg.__path__ = [str(_proj / "agent" / "core")]
            core_pkg.__package__ = "agent.core"

    # redis stub
    if "redis" not in sys.modules:
        redis_mod = types.ModuleType("redis")
        sys.modules["redis"] = redis_mod

    redis_mod = sys.modules["redis"]

    # redis.asyncio stub
    if "redis.asyncio" not in sys.modules:
        redis_asyncio = types.ModuleType("redis.asyncio")
        sys.modules["redis.asyncio"] = redis_asyncio
        setattr(redis_mod, "asyncio", redis_asyncio)

    redis_asyncio = sys.modules["redis.asyncio"]

    # Redis sınıfı stub — from_url her çağrıda yeni mock döndürür
    class _MockRedis:
        @classmethod
        def from_url(cls, url, **kwargs):
            inst = AsyncMock()
            inst.ping = AsyncMock(side_effect=ConnectionRefusedError("redis yok"))
            inst.xadd = AsyncMock()
            inst.xreadgroup = AsyncMock(return_value=[])
            inst.xgroup_create = AsyncMock()
            inst.xack = AsyncMock()
            inst.aclose = AsyncMock()
            return inst

    if not hasattr(redis_asyncio, "Redis"):
        redis_asyncio.Redis = _MockRedis

    # redis.exceptions stub
    if "redis.exceptions" not in sys.modules:
        redis_exc = types.ModuleType("redis.exceptions")
        redis_exc.ResponseError = type("ResponseError", (Exception,), {})
        sys.modules["redis.exceptions"] = redis_exc
        setattr(redis_mod, "exceptions", redis_exc)


def _get_event_stream():
    _stub_event_stream_deps()
    sys.modules.pop("agent.core.event_stream", None)
    import agent.core.event_stream as es
    return es


class TestAgentEvent:
    def test_agent_event_fields(self):
        es = _get_event_stream()
        evt = es.AgentEvent(ts=1.0, source="test", message="merhaba")
        assert evt.ts == 1.0
        assert evt.source == "test"
        assert evt.message == "merhaba"


class TestAgentEventBusSubscribe:
    def test_subscribe_returns_id_and_queue(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe()
        assert isinstance(sub_id, int)
        assert isinstance(queue, asyncio.Queue)

    def test_subscribe_multiple_adds_to_subscribers(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        # Subscribe birden fazla kez ekleyebilmeli; koleksiyon büyümeli
        initial = len(bus._subscribers)
        bus.subscribe()
        assert len(bus._subscribers) >= initial + 1

    def test_unsubscribe_removes_subscriber(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, _ = bus.subscribe()
        bus.unsubscribe(sub_id)
        assert sub_id not in bus._subscribers

    def test_unsubscribe_nonexistent_no_error(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus.unsubscribe(999999)  # var olmayan id — hata yok


class TestAgentEventBusFanout:
    def test_fanout_local_delivers_to_subscriber(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe()
        evt = es.AgentEvent(ts=1.0, source="src", message="mesaj")
        bus._fanout_local(evt)
        assert not queue.empty()
        item = queue.get_nowait()
        assert item.message == "mesaj"

    def test_fanout_local_delivers_to_single_subscriber(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe()
        evt = es.AgentEvent(ts=1.0, source="src", message="broadcast")
        bus._fanout_local(evt)
        # Abone kuyruğuna event ulaşmış olmalı
        assert not queue.empty()
        assert queue.get_nowait().message == "broadcast"

    def test_fanout_full_queue_drops_subscriber(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        # subscribe: maxsize en az 10 oluyor (max(10, maxsize))
        sub_id, queue = bus.subscribe(maxsize=1)
        actual_maxsize = queue.maxsize  # gerçek maxsize (en az 10)
        # Kuyruğu tamamen doldur
        for i in range(actual_maxsize):
            bus._fanout_local(es.AgentEvent(ts=float(i), source="s", message=str(i)))
        # Kuyruk dolu — bir daha eklenince subscriber düşürülmeli
        bus._fanout_local(es.AgentEvent(ts=float(actual_maxsize), source="s", message="extra"))
        assert sub_id not in bus._subscribers

    def test_no_subscribers_fanout_no_error(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        evt = es.AgentEvent(ts=1.0, source="s", message="m")
        bus._fanout_local(evt)  # hata yok

    @pytest.mark.asyncio
    async def test_fanout_uses_buffer_then_drains_when_queue_has_space(self):
        from collections import deque

        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe(maxsize=10)
        # Kuyruğu doldurup bir buffer tanımla; drop yerine buffer'a yazılmalı.
        for i in range(queue.maxsize):
            queue.put_nowait(es.AgentEvent(ts=float(i), source="seed", message=f"seed-{i}"))
        bus._buffered_events[sub_id] = deque(maxlen=3)

        overflow_evt = es.AgentEvent(ts=99.0, source="src", message="overflow")
        bus._fanout_local(overflow_evt)
        assert sub_id in bus._subscribers
        assert len(bus._buffered_events[sub_id]) == 1

        _ = queue.get_nowait()  # yer aç
        progressed = await bus._drain_buffered_events_once()
        assert progressed is True
        assert any(getattr(item, "message", "") == "overflow" for item in list(queue._queue))


class TestAgentEventBusPublish:
    @pytest.mark.asyncio
    async def test_publish_delivers_locally(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        # Redis kullanılmaması için _redis_available = False olarak ayarla
        bus._redis_available = False
        sub_id, queue = bus.subscribe()
        await bus.publish("supervisor", "test mesajı")
        assert not queue.empty()
        evt = await queue.get()
        assert evt.source == "supervisor"
        assert evt.message == "test mesajı"

    @pytest.mark.asyncio
    async def test_publish_redis_unavailable_falls_back(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False
        sub_id, queue = bus.subscribe()
        await bus.publish("agent_x", "yerel mesaj")
        item = await queue.get()
        assert item.message == "yerel mesaj"

    @pytest.mark.asyncio
    async def test_publish_calls_redis_path_when_available(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True
        sub_id, queue = bus.subscribe()
        bus._publish_via_redis = AsyncMock(return_value=True)

        await bus.publish("agent_y", "redis ve local")

        bus._publish_via_redis.assert_awaited_once()
        local_evt = await queue.get()
        assert local_evt.source == "agent_y"
        assert local_evt.message == "redis ve local"


class TestAgentEventBusPublishViaRedis:
    @pytest.mark.asyncio
    async def test_publish_via_redis_returns_false_when_unavailable(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False
        evt = es.AgentEvent(ts=1.0, source="s", message="m")
        result = await bus._publish_via_redis(evt)
        assert result is False

    @pytest.mark.asyncio
    async def test_publish_via_redis_returns_false_when_no_client(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        # _redis_available None → bootstrap denenir ama redis yoksa False olur
        bus._redis_available = False
        bus._redis_client = None
        evt = es.AgentEvent(ts=1.0, source="s", message="m")
        result = await bus._publish_via_redis(evt)
        assert result is False


class TestAgentEventBusDLQ:
    @pytest.mark.asyncio
    async def test_write_dead_letter_appends_to_buffer(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False
        await bus._write_dead_letter(reason="test_error", payload={"x": 1})
        assert len(bus._dlq_buffer) == 1
        item = bus._dlq_buffer[0]
        assert item["reason"] == "test_error"

    @pytest.mark.asyncio
    async def test_write_dead_letter_includes_error_str(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False
        exc = ValueError("test exception")
        await bus._write_dead_letter(reason="r", payload={}, error=exc)
        assert "test exception" in bus._dlq_buffer[0]["error"]


class TestAgentEventBusCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_redis_no_error_when_clean(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        # Hiç redis client yok — cleanup hata vermemeli
        await bus._cleanup_redis()
        assert bus._redis_client is None
        assert bus._redis_listener_task is None


class TestGetAgentEventBus:
    def test_returns_same_singleton(self):
        es = _get_event_stream()
        bus1 = es.get_agent_event_bus()
        bus2 = es.get_agent_event_bus()
        assert bus1 is bus2

    def test_singleton_is_agent_event_bus_instance(self):
        es = _get_event_stream()
        bus = es.get_agent_event_bus()
        assert isinstance(bus, es.AgentEventBus)


class TestAgentEventBusDrainBuffered:
    @pytest.mark.asyncio
    async def test_drain_empty_buffers_returns_false(self):
        es = _get_event_stream()
        bus = es.AgentEventBus()
        result = await bus._drain_buffered_events_once()
        assert result is False

    @pytest.mark.asyncio
    async def test_drain_with_buffered_event(self):
        from collections import deque
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe(maxsize=10)
        evt = es.AgentEvent(ts=1.0, source="s", message="buffered")
        bus._buffered_events[sub_id] = deque([evt])
        result = await bus._drain_buffered_events_once()
        assert result is True
        assert not queue.empty()
