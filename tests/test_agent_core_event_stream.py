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

    def test_fanout_uses_buffer_then_drains_when_queue_has_space(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestAgentEventBusPublish:
    def test_publish_delivers_locally(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_redis_unavailable_falls_back(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_available = False
            sub_id, queue = bus.subscribe()
            await bus.publish("agent_x", "yerel mesaj")
            item = await queue.get()
            assert item.message == "yerel mesaj"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_calls_redis_path_when_available(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestAgentEventBusPublishViaRedis:
    def test_publish_via_redis_returns_false_when_unavailable(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_available = False
            evt = es.AgentEvent(ts=1.0, source="s", message="m")
            result = await bus._publish_via_redis(evt)
            assert result is False
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_via_redis_returns_false_when_no_client(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            # _redis_available None → bootstrap denenir ama redis yoksa False olur
            bus._redis_available = False
            bus._redis_client = None
            evt = es.AgentEvent(ts=1.0, source="s", message="m")
            result = await bus._publish_via_redis(evt)
            assert result is False
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestAgentEventBusDLQ:
    def test_write_dead_letter_appends_to_buffer(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_available = False
            await bus._write_dead_letter(reason="test_error", payload={"x": 1})
            assert len(bus._dlq_buffer) == 1
            item = bus._dlq_buffer[0]
            assert item["reason"] == "test_error"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_write_dead_letter_includes_error_str(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_available = False
            exc = ValueError("test exception")
            await bus._write_dead_letter(reason="r", payload={}, error=exc)
            assert "test exception" in bus._dlq_buffer[0]["error"]
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestAgentEventBusCleanup:
    def test_cleanup_redis_no_error_when_clean(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            # Hiç redis client yok — cleanup hata vermemeli
            await bus._cleanup_redis()
            assert bus._redis_client is None
            assert bus._redis_listener_task is None
        import asyncio as _asyncio
        _asyncio.run(_run())

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
    def test_drain_empty_buffers_returns_false(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            result = await bus._drain_buffered_events_once()
            assert result is False
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_drain_with_buffered_event(self):
        async def _run():
            from collections import deque
            es = _get_event_stream()
            bus = es.AgentEventBus()
            sub_id, queue = bus.subscribe(maxsize=10)
            evt = es.AgentEvent(ts=1.0, source="s", message="buffered")
            bus._buffered_events[sub_id] = deque([evt])
            result = await bus._drain_buffered_events_once()
            assert result is True
            assert not queue.empty()
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestAgentEventBusRedisListenerFailures:
    def test_redis_listener_loop_sets_fallback_on_stream_exception(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_available = True
            bus._redis_client = AsyncMock()
            bus._redis_client.xreadgroup = AsyncMock(side_effect=RuntimeError("redis stream disconnected"))
            bus._cleanup_redis = AsyncMock()

            await bus._redis_listener_loop()
            assert bus._redis_available is False
            bus._cleanup_redis.assert_awaited_once()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_redis_listener_loop_invalid_payload_writes_dlq(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._redis_client = AsyncMock()
            bus._redis_client.xreadgroup = AsyncMock(
                side_effect=[
                    [("stream", [("1-0", {"payload": "{invalid json"})])],
                    asyncio.CancelledError(),
                ]
            )
            bus._redis_client.xack = AsyncMock(return_value=1)
            bus._write_dead_letter = AsyncMock()

            with pytest.raises(asyncio.CancelledError):
                await bus._redis_listener_loop()

            assert bus._write_dead_letter.await_count >= 1
            assert any(call.kwargs.get("reason") == "invalid_payload" for call in bus._write_dead_letter.await_args_list)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_redis_listener_loop_ack_failure_writes_dlq(self):
        async def _run():
            es = _get_event_stream()
            bus = es.AgentEventBus()
            bus._instance_id = "self"
            bus._redis_client = AsyncMock()
            bus._redis_client.xreadgroup = AsyncMock(
                side_effect=[
                    [("stream", [("1-1", {"payload": "{\"sid\":\"other\",\"source\":\"a\",\"message\":\"m\",\"ts\":1}"})])],
                    asyncio.CancelledError(),
                ]
            )
            bus._redis_client.xack = AsyncMock(side_effect=RuntimeError("ack lost"))
            bus._write_dead_letter = AsyncMock()

            with pytest.raises(asyncio.CancelledError):
                await bus._redis_listener_loop()

            assert any(call.kwargs.get("reason") == "ack_failed" for call in bus._write_dead_letter.await_args_list)
        import asyncio as _asyncio
        _asyncio.run(_run())

# ===== MERGED FROM tests/test_agent_core_event_stream_extra.py =====

import asyncio
import sys
import types
import pathlib as _pl
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_event_stream_deps(*, ping_raises=False, ping_ok=True, xgroup_busygroup=False, xgroup_raises=False):
    """Redis stub'ı parametrik olarak yapılandırır."""
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

    if "redis" not in sys.modules:
        redis_mod = types.ModuleType("redis")
        sys.modules["redis"] = redis_mod
    redis_mod = sys.modules["redis"]

    if "redis.asyncio" not in sys.modules:
        redis_asyncio = types.ModuleType("redis.asyncio")
        sys.modules["redis.asyncio"] = redis_asyncio
        setattr(redis_mod, "asyncio", redis_asyncio)
    redis_asyncio = sys.modules["redis.asyncio"]

    if "redis.exceptions" not in sys.modules:
        redis_exc = types.ModuleType("redis.exceptions")
        redis_exc.ResponseError = type("ResponseError", (Exception,), {})
        sys.modules["redis.exceptions"] = redis_exc
        setattr(redis_mod, "exceptions", redis_exc)

    ResponseError = sys.modules["redis.exceptions"].ResponseError

    class _MockRedis:
        @classmethod
        def from_url(cls, url, **kwargs):
            inst = AsyncMock()
            if ping_raises:
                inst.ping = AsyncMock(side_effect=ConnectionRefusedError("redis yok"))
            else:
                inst.ping = AsyncMock(return_value=True)
            inst.xadd = AsyncMock()
            inst.xreadgroup = AsyncMock(return_value=[])
            if xgroup_busygroup:
                inst.xgroup_create = AsyncMock(
                    side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
                )
            elif xgroup_raises:
                inst.xgroup_create = AsyncMock(side_effect=ResponseError("ERR some other error"))
            else:
                inst.xgroup_create = AsyncMock()
            inst.xack = AsyncMock()
            inst.aclose = AsyncMock()
            return inst

    redis_asyncio.Redis = _MockRedis


def _get_event_stream(**stub_kwargs):
    _stub_event_stream_deps(**stub_kwargs)
    sys.modules.pop("agent.core.event_stream", None)
    import agent.core.event_stream as es
    return es


# ─────────────────────────────────────────────────────────────────────────────
# _schedule_redis_bootstrap: uç durumlar
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestScheduleRedisBootstrap:
    def test_schedule_skips_when_redis_unavailable(self):
        """_redis_available=False iken bootstrap task yaratılmamalı (L63-64)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False
        bus._schedule_redis_bootstrap()
        assert bus._redis_bootstrap_task is None

    def test_schedule_skips_when_task_already_running(self):
        """Çalışan bir bootstrap task varsa yenisi yaratılmamalı (L65-66)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        running_task = MagicMock()
        running_task.done.return_value = False
        bus._redis_bootstrap_task = running_task
        bus._schedule_redis_bootstrap()
        # Aynı task referansı kalmış olmalı
        assert bus._redis_bootstrap_task is running_task

    def test_schedule_no_running_loop_returns_silently(self):
        """Çalışan asyncio loop yokken RuntimeError yutulmalı (L68-70)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = None
        # Event loop dışında çağrı — RuntimeError yutulmalı, exception çıkmamalı
        bus._schedule_redis_bootstrap()


# ─────────────────────────────────────────────────────────────────────────────
# _ensure_redis_listener
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestEnsureRedisListener:
    def test_returns_early_when_redis_available_false(self):
        """_redis_available=False iken listener başlatılmamalı (L74-75)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False

        async def _run():
            await bus._ensure_redis_listener()
            assert bus._redis_listener_task is None

        asyncio.run(_run())

    def test_returns_early_when_listener_already_running(self):
        """Çalışan listener task varken yenisi başlatılmamalı (L76-77)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        running_task = MagicMock()
        running_task.done.return_value = False
        bus._redis_listener_task = running_task

        async def _run():
            await bus._ensure_redis_listener()
            assert bus._redis_listener_task is running_task

        asyncio.run(_run())

    def test_bootstrap_success_busygroup_error_ignored(self):
        """xgroup_create BUSYGROUP hatası yutulmalı, _redis_available=True olmalı (L89-100)."""
        es = _get_event_stream(xgroup_busygroup=True)
        bus = es.AgentEventBus()

        async def _run():
            def _safe_create_task(coro):
                coro.close()
                mock_task = MagicMock()
                mock_task.done.return_value = False
                return mock_task

            with patch("asyncio.create_task", side_effect=_safe_create_task):
                await bus._ensure_redis_listener()
            assert bus._redis_available is True

        asyncio.run(_run())

    def test_bootstrap_failure_sets_redis_available_false(self):
        """ping başarısız olursa _redis_available=False ve cleanup çağrılmalı (L102-105)."""
        es = _get_event_stream(ping_raises=True)
        bus = es.AgentEventBus()
        bus._cleanup_redis = AsyncMock()

        async def _run():
            await bus._ensure_redis_listener()
            assert bus._redis_available is False
            bus._cleanup_redis.assert_awaited_once()

        asyncio.run(_run())

    def test_bootstrap_xgroup_non_busygroup_error_raises_and_falls_back(self):
        """BUSYGROUP olmayan ResponseError _redis_available=False yapmalı (L96-98)."""
        es = _get_event_stream(xgroup_raises=True)
        bus = es.AgentEventBus()
        bus._cleanup_redis = AsyncMock()

        async def _run():
            await bus._ensure_redis_listener()
            assert bus._redis_available is False

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _publish_via_redis: hata yolları
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestPublishViaRedis:
    def test_returns_false_when_client_is_none_after_bootstrap(self):
        """Bootstrap sonrası client hala None ise False dönmeli (L111-113)."""
        es = _get_event_stream(ping_raises=True)
        bus = es.AgentEventBus()
        bus._redis_available = None
        evt = es.AgentEvent(ts=1.0, source="s", message="m")

        async def _run():
            result = await bus._publish_via_redis(evt)
            assert result is False

        asyncio.run(_run())

    def test_xadd_failure_writes_dlq_and_disables_redis(self):
        """xadd başarısız olursa DLQ'ya yazılmalı ve redis devre dışı bırakılmalı (L127-136)."""
        es = _get_event_stream(ping_ok=True)
        bus = es.AgentEventBus()
        bus._redis_available = True

        client_mock = AsyncMock()
        client_mock.xadd = AsyncMock(side_effect=RuntimeError("xadd failed"))
        bus._redis_client = client_mock
        bus._write_dead_letter = AsyncMock()
        bus._cleanup_redis = AsyncMock()
        bus._ensure_redis_listener = AsyncMock()

        evt = es.AgentEvent(ts=1.0, source="s", message="m")

        async def _run():
            result = await bus._publish_via_redis(evt)
            assert result is False
            assert bus._redis_available is False
            bus._write_dead_letter.assert_awaited_once()
            assert bus._write_dead_letter.call_args.kwargs["reason"] == "publish_failed"
            bus._cleanup_redis.assert_awaited_once()

        asyncio.run(_run())

    def test_xadd_success_returns_true(self):
        """xadd başarılı ise True dönmeli (L126)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True

        client_mock = AsyncMock()
        client_mock.xadd = AsyncMock(return_value="1-0")
        bus._redis_client = client_mock
        bus._ensure_redis_listener = AsyncMock()

        evt = es.AgentEvent(ts=1.0, source="s", message="m")

        async def _run():
            result = await bus._publish_via_redis(evt)
            assert result is True

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _cleanup_redis: görev iptal ve client kapatma
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestCleanupRedis:
    def test_cancels_running_listener_task(self):
        """Çalışan listener task iptal edilmeli (L225-228)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()

        async def _run():
            async def _forever():
                await asyncio.sleep(9999)

            task = asyncio.create_task(_forever())
            bus._redis_listener_task = task

            await bus._cleanup_redis()
            await asyncio.sleep(0)
            assert task.cancelled()
            assert bus._redis_listener_task is None

        asyncio.run(_run())

    def test_closes_redis_client_via_aclose(self):
        """Redis client'ın aclose metodu çağrılmalı (L231-234)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()

        client_mock = AsyncMock()
        client_mock.aclose = AsyncMock()
        bus._redis_client = client_mock

        async def _run():
            await bus._cleanup_redis()
            client_mock.aclose.assert_awaited_once()
            assert bus._redis_client is None

        asyncio.run(_run())

    def test_closes_redis_client_via_close_fallback(self):
        """aclose yoksa close() fallback çağrılmalı (L233)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()

        client_mock = AsyncMock()
        del client_mock.aclose  # aclose yok → fallback
        client_mock.close = AsyncMock()
        bus._redis_client = client_mock

        async def _run():
            await bus._cleanup_redis()
            assert bus._redis_client is None

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _write_dead_letter: redis yolu
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestWriteDeadLetterRedisPath:
    def test_writes_to_redis_dlq_when_available(self):
        """Redis kullanılabilirken DLQ'ya xadd yapılmalı (L250-256)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True

        client_mock = AsyncMock()
        client_mock.xadd = AsyncMock()
        bus._redis_client = client_mock

        async def _run():
            await bus._write_dead_letter(reason="test", payload={"k": "v"})
            client_mock.xadd.assert_awaited_once()

        asyncio.run(_run())

    def test_dlq_redis_xadd_failure_logs_debug_no_exception(self):
        """DLQ xadd başarısız olursa hata yutulmalı, exception çıkmamalı (L257-258)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True

        client_mock = AsyncMock()
        client_mock.xadd = AsyncMock(side_effect=RuntimeError("dlq xadd failed"))
        bus._redis_client = client_mock

        async def _run():
            # Exception çıkmamalı
            await bus._write_dead_letter(reason="dlq_fail", payload={})
            assert len(bus._dlq_buffer) == 1

        asyncio.run(_run())

    def test_skips_redis_dlq_when_client_none(self):
        """Redis client None ise DLQ'ya yalnızca local buffer'a yazılmalı (L247-248)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True
        bus._redis_client = None

        async def _run():
            await bus._write_dead_letter(reason="no_client", payload={"x": 1})
            assert len(bus._dlq_buffer) == 1
            assert bus._dlq_buffer[0]["reason"] == "no_client"

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _drain_buffered_events_once: kuyruk dolu yolu
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestDrainBufferedEventsFull:
    def test_drain_skips_when_queue_full_but_returns_true(self):
        """Kuyruk doluysa event beklemede kalmalı ve any_progress=True dönmeli (L197-199)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        sub_id, queue = bus.subscribe(maxsize=10)

        # Kuyruğu doldur
        for i in range(queue.maxsize):
            queue.put_nowait(es.AgentEvent(ts=float(i), source="s", message=str(i)))

        # Buffer'a bir event ekle
        overflow_evt = es.AgentEvent(ts=99.0, source="s", message="waiting")
        bus._buffered_events[sub_id] = deque([overflow_evt])

        async def _run():
            result = await bus._drain_buffered_events_once()
            # Kuyruk doluydu → event beklemede, ama any_progress=True
            assert result is True
            # Buffer'dan henüz alınmamış olmalı
            assert len(bus._buffered_events[sub_id]) == 1

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _redis_listener_loop: own-sid mesajları atlanmalı
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestRedisListenerLoopOwnSid:
    def test_own_sid_message_not_fanned_out(self):
        """Kendi instance_id'li mesajlar fanout'a gitmemeli (L165)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._instance_id = "myid"
        sub_id, queue = bus.subscribe()

        own_payload = '{"sid":"myid","source":"self","message":"should be skipped","ts":1.0}'
        bus._redis_client = AsyncMock()
        bus._redis_client.xreadgroup = AsyncMock(
            side_effect=[
                [("stream", [("1-0", {"payload": own_payload})])],
                asyncio.CancelledError(),
            ]
        )
        bus._redis_client.xack = AsyncMock()
        bus._write_dead_letter = AsyncMock()

        async def _run():
            with pytest.raises(asyncio.CancelledError):
                await bus._redis_listener_loop()
            # Kuyruğa hiç event gitmemeli
            assert queue.empty()

        asyncio.run(_run())

    def test_empty_response_continues_loop(self):
        """Boş response continue edilmeli, loop devam etmeli (L157-158)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_client = AsyncMock()
        bus._redis_client.xreadgroup = AsyncMock(
            side_effect=[
                [],  # boş → continue
                asyncio.CancelledError(),
            ]
        )
        bus._write_dead_letter = AsyncMock()

        async def _run():
            with pytest.raises(asyncio.CancelledError):
                await bus._redis_listener_loop()
            # DLQ'ya yazılmamalı (boş response hata değil)
            bus._write_dead_letter.assert_not_awaited()

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# Publish: redis available True ve xadd başarılı
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestPublishFullPath:
    def test_publish_with_redis_available_true_and_client(self):
        """publish() redis kullanılabilirken xadd çağrılmalı (L56-60)."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = True

        client_mock = AsyncMock()
        client_mock.xadd = AsyncMock(return_value="1-0")
        bus._redis_client = client_mock
        bus._ensure_redis_listener = AsyncMock()

        sub_id, queue = bus.subscribe()

        async def _run():
            await bus.publish("supervisor", "test")
            client_mock.xadd.assert_awaited_once()
            assert not queue.empty()

        asyncio.run(_run())

    def test_publish_empty_subscribers_no_error(self):
        """Subscriber yokken publish hata vermemeli."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        bus._redis_available = False

        async def _run():
            await bus.publish("src", "msg")  # hata yok

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# get_agent_event_bus singleton
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestSingletonEventBus:
    def test_get_agent_event_bus_is_agent_event_bus_type(self):
        es = _get_event_stream()
        bus = es.get_agent_event_bus()
        assert isinstance(bus, es.AgentEventBus)

    def test_bus_dlq_buffer_maxlen_env_default(self):
        """DLQ buffer maxlen en az 10 olmalı."""
        es = _get_event_stream()
        bus = es.AgentEventBus()
        assert bus._dlq_buffer.maxlen >= 10

    def test_bus_dlq_buffer_maxlen_enforces_minimum_with_small_env(self, monkeypatch):
        monkeypatch.setenv("SIDAR_EVENT_BUS_DLQ_MAXLEN", "1")
        es = _get_event_stream()
        bus = es.AgentEventBus()
        assert bus._dlq_buffer.maxlen == 10
