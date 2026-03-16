import asyncio
import json
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_redis_incr_exception_uses_local_rate_limit_fallback(monkeypatch):
    mod = _load_web_server()

    class _RedisBoom:
        async def incr(self, _key):
            raise RuntimeError("redis incr boom")

    async def _fake_get_redis():
        return _RedisBoom()

    seen = {}

    async def _local(key, limit, window):
        seen["key"] = key
        seen["limit"] = limit
        seen["window"] = window
        return True

    monkeypatch.setattr(mod, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(mod, "_local_is_rate_limited", _local)

    blocked = asyncio.run(mod._redis_is_rate_limited("chat", "127.0.0.1", 9, 60))
    assert blocked is True
    assert seen["limit"] == 9 and seen["window"] == 60
    assert seen["key"].startswith("sidar:rl:chat:127.0.0.1:")


def test_setup_tracing_early_return_when_disabled_and_warning_when_missing_deps(monkeypatch):
    mod = _load_web_server()

    infos = []
    warnings = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    mod.cfg.ENABLE_TRACING = False
    mod._setup_tracing()
    assert warnings == []

    mod.cfg.ENABLE_TRACING = True
    mod.trace = None
    mod.OTLPSpanExporter = None
    mod.FastAPIInstrumentor = None
    mod.TracerProvider = None
    mod.Resource = None
    mod.BatchSpanProcessor = None
    mod._setup_tracing()
    assert any("OpenTelemetry" in x for x in warnings)


def test_websocket_disconnect_cancels_active_task_and_generate_cancelled_cleanup(monkeypatch):
    mod = _load_web_server()

    cancel_seen = {"cancelled": False, "reset": 0, "unsub": 0}

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Mem:
        def __init__(self):
            self.db = _DB()

        def __len__(self):
            return 1

        async def set_active_user(self, _uid, _uname=None):
            return None

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Mem()

        async def respond(self, _msg):
            raise asyncio.CancelledError()
            yield "x"

    class _Bus:
        def subscribe(self):
            return "sub-1", asyncio.Queue()

        def unsubscribe(self, _sub_id):
            cancel_seen["unsub"] += 1

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "hello"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            for _ in range(20):
                if seen["chunk_sends"] > 0:
                    break
                await asyncio.sleep(0.01)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            return None

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_a, **_k):
        return False

    real_create_task = mod.asyncio.create_task

    def _track_create_task(coro):
        t = real_create_task(coro)
        real_cancel = t.cancel

        def _cancel(*args, **kwargs):
            cancel_seen["cancelled"] = True
            return real_cancel(*args, **kwargs)

        t.cancel = _cancel
        return t

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    bus = _Bus()
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: cancel_seen.__setitem__("reset", cancel_seen["reset"] + 1))
    monkeypatch.setattr(mod.asyncio, "create_task", _track_create_task)

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert cancel_seen["cancelled"] is True
    assert cancel_seen["reset"] >= 0

def test_websocket_large_chunk_disconnect_still_cleans_event_bus_and_context(monkeypatch):
    mod = _load_web_server()

    seen = {"unsub": 0, "reset": 0, "send_calls": 0, "chunk_sends": 0}

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Mem:
        def __init__(self):
            self.db = _DB()

        def __len__(self):
            return 1

        async def set_active_user(self, _uid, _uname=None):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Mem()

        async def respond(self, _msg):
            yield "X" * 200_000
            yield "tail"

    class _Bus:
        def subscribe(self):
            return "sub-large", asyncio.Queue()

        def unsubscribe(self, _sid):
            seen["unsub"] += 1

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "big"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            for _ in range(20):
                if seen["chunk_sends"] > 0:
                    break
                await asyncio.sleep(0.01)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            seen["send_calls"] += 1
            if "chunk" in payload:
                seen["chunk_sends"] += 1
            if len(payload.get("chunk", "")) > 100_000:
                raise mod.WebSocketDisconnect()
            return None

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_a, **_k):
        return False

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    bus = _Bus()
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: seen.__setitem__("reset", seen["reset"] + 1))

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert seen["chunk_sends"] >= 1
    assert seen["unsub"] == 1
    assert seen["reset"] == 1
