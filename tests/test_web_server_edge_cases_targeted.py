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
            await asyncio.sleep(0.05)
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
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: _Bus())
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: cancel_seen.__setitem__("reset", cancel_seen["reset"] + 1))
    monkeypatch.setattr(mod.asyncio, "create_task", _track_create_task)

    asyncio.run(mod.websocket_chat(_WebSocket()))

    assert cancel_seen["cancelled"] is True
    assert cancel_seen["reset"] >= 0


def test_reap_child_processes_handles_unexpected_waitpid_error(monkeypatch):
    mod = _load_web_server()

    def _boom(_pid, _flags):
        raise RuntimeError("waitpid boom")

    monkeypatch.setattr(mod.os, "waitpid", _boom)
    assert mod._reap_child_processes_nonblocking() == 0


def test_force_shutdown_returns_immediately_when_cleanup_already_done(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = True

    calls = {"reap": 0}

    def _reap():
        calls["reap"] += 1
        return 0

    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", _reap)
    mod._force_shutdown_local_llm_processes()

    assert calls["reap"] == 0


def test_sanitize_capabilities_returns_empty_list_for_none_or_empty_inputs():
    mod = _load_web_server()
    assert mod._sanitize_capabilities(None) == []
    assert mod._sanitize_capabilities([]) == []


def test_admin_list_policies_passes_none_tenant_when_blank(monkeypatch):
    mod = _load_web_server()

    seen = {}

    class _DB:
        async def list_access_policies(self, user_id, tenant_id=None):
            seen["user_id"] = user_id
            seen["tenant_id"] = tenant_id
            return [
                types.SimpleNamespace(
                    id=1,
                    user_id=user_id,
                    tenant_id="default",
                    resource_type="github",
                    resource_id="*",
                    action="read",
                    effect="allow",
                    created_at="now",
                    updated_at="now",
                )
            ]

    class _Mem:
        db = _DB()

    class _Agent:
        memory = _Mem()

    async def _get_agent():
        return _Agent()

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    response = asyncio.run(mod.admin_list_policies("u-1", "   ", _user=object()))
    assert seen == {"user_id": "u-1", "tenant_id": None}
    assert response.content["items"][0]["user_id"] == "u-1"
