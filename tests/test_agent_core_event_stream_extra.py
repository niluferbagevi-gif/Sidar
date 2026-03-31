"""
agent/core/event_stream.py için ek birim testleri.
Eksik satırları kapsamak üzere: _ensure_redis_listener, _publish_via_redis,
_cleanup_redis, _write_dead_letter redis yolu, _schedule_redis_bootstrap uç durumlar.
"""
from __future__ import annotations

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

class TestScheduleRedisBootstrap:
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

class TestEnsureRedisListener:
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

class TestPublishViaRedis:
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

class TestCleanupRedis:
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

class TestWriteDeadLetterRedisPath:
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

class TestDrainBufferedEventsFull:
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

class TestRedisListenerLoopOwnSid:
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

class TestPublishFullPath:
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

class TestSingletonEventBus:
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
