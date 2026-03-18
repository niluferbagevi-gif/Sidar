import asyncio
import json
import sys
import types

# tests.test_web_server_runtime modülü import edilirken opsiyonel bağımlılıklar gerektiriyor; burada hafif stub sağlıyoruz.
sys.modules.setdefault("jwt", types.ModuleType("jwt"))
pyd_mod = types.ModuleType("pydantic")

class _BaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

def _field(default=None, **_kwargs):
    return default

pyd_mod.BaseModel = _BaseModel
pyd_mod.Field = _field
sys.modules.setdefault("pydantic", pyd_mod)

httpx_mod = types.ModuleType("httpx")
httpx_mod.AsyncClient = object
httpx_mod.Timeout = object
sys.modules.setdefault("httpx", httpx_mod)

bs4_mod = types.ModuleType("bs4")
bs4_mod.BeautifulSoup = object
sys.modules.setdefault("bs4", bs4_mod)

from tests.test_web_server_runtime import _FakeHTTPException, _FakeRequest, _load_web_server


def test_websocket_disconnect_cancels_running_active_task():
    mod = _load_web_server()
    mod.jwt.PyJWTError = Exception
    mod.jwt.decode = lambda token, *_a, **_k: {"sub": "u1", "username": "alice"} if token else {}

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            yield "x"

    class _WebSocket:
        def __init__(self):
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "çalış"}),
            ]
            self.client = types.SimpleNamespace(host="127.0.0.1")

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.01)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            return None

    class _FakeTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

    fake_task = _FakeTask()

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    real_create_task = mod.asyncio.create_task

    def _create_task_stub(_coro):
        _coro.close()
        return fake_task

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited
    mod.asyncio.create_task = _create_task_stub
    try:
        asyncio.run(mod.websocket_chat(_WebSocket()))
    finally:
        mod.asyncio.create_task = real_create_task

    assert fake_task.cancel_called is True




def test_websocket_anyio_closed_resource_cancels_running_task():
    mod = _load_web_server()
    mod.jwt.PyJWTError = Exception
    mod.jwt.decode = lambda token, *_a, **_k: {"sub": "u1", "username": "alice"} if token else {}

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield None

    class _Closed(Exception):
        pass

    mod._ANYIO_CLOSED = _Closed

    class _WebSocket:
        def __init__(self):
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "merhaba"}),
            ]
            self.client = types.SimpleNamespace(host="127.0.0.1")

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise _Closed()

        async def send_json(self, _payload):
            return None

    class _FakeTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

    fake_task = _FakeTask()

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    real_create_task = mod.asyncio.create_task

    def _create_task_stub(_coro):
        _coro.close()
        return fake_task

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited
    mod.asyncio.create_task = _create_task_stub
    try:
        asyncio.run(mod.websocket_chat(_WebSocket()))
    finally:
        mod.asyncio.create_task = real_create_task

    assert fake_task.cancel_called is True


def test_ddos_rate_limit_middleware_uses_local_fallback_after_redis_disconnect(monkeypatch):
    mod = _load_web_server()

    class _RedisBoom:
        async def incr(self, _key):
            raise RuntimeError("redis connection dropped")

    local_calls = []

    async def _fake_get_redis():
        return _RedisBoom()

    async def _fake_local(key, limit, window):
        local_calls.append((key, limit, window))
        return True

    async def _next(_request):
        return types.SimpleNamespace(status_code=200, content={"ok": True})

    monkeypatch.setattr(mod, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(mod, "_local_is_rate_limited", _fake_local)

    resp = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/api/runtime"), _next))

    assert resp.status_code == 429
    assert local_calls and local_calls[0][0].startswith("sidar:rl:ddos:")

def test_github_webhook_hmac_invalid_signature_rejected_and_valid_accepted():
    mod = _load_web_server()
    mod.cfg.GITHUB_WEBHOOK_SECRET = "secret"

    class _Agent:
        def __init__(self):
            self.memory_calls = []

            async def _add(role, text):
                self.memory_calls.append((role, text))

            self.memory = types.SimpleNamespace(add=_add)

    agent = _Agent()

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    body = json.dumps({"pusher": {"name": "bob"}, "ref": "refs/heads/dev"}).encode("utf-8")

    try:
        asyncio.run(
            mod.github_webhook(
                _FakeRequest(body_bytes=body),
                x_github_event="push",
                x_hub_signature_256="sha256=wrong",
            )
        )
        assert False, "expected 401"
    except _FakeHTTPException as exc:
        assert exc.status_code == 401

    assert agent.memory_calls == []

    good_sig = "sha256=" + mod.hmac.new(b"secret", body, mod.hashlib.sha256).hexdigest()
    ok = asyncio.run(
        mod.github_webhook(
            _FakeRequest(body_bytes=body),
            x_github_event="push",
            x_hub_signature_256=good_sig,
        )
    )
    assert ok.status_code == 200
    assert any("bob" in txt for _role, txt in agent.memory_calls)


def test_github_webhook_requires_signature_when_secret_is_set():
    mod = _load_web_server()
    mod.cfg.GITHUB_WEBHOOK_SECRET = "secret"

    try:
        asyncio.run(
            mod.github_webhook(
                _FakeRequest(body_bytes=b"{}"),
                x_github_event="push",
                x_hub_signature_256="",
            )
        )
        assert False, "expected 401"
    except _FakeHTTPException as exc:
        assert exc.status_code == 401

def test_websocket_chat_skips_invalid_json_payload_then_processes_auth_and_send():
    mod = _load_web_server()
    mod.jwt.PyJWTError = Exception
    mod.jwt.decode = lambda token, *_a, **_k: {"sub": "u1", "username": "alice"} if token else {}

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            yield "tamam"

    class _WebSocket:
        def __init__(self):
            self._payloads = [
                "{broken-json}",
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "merhaba"}),
            ]
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.01)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert any(item.get("auth_ok") is True for item in ws.sent)
    assert any(item.get("chunk") == "tamam" for item in ws.sent)
    assert any(item.get("done") is True for item in ws.sent)


def test_app_lifespan_cancels_prewarm_and_runs_shutdown_hooks():
    mod = _load_web_server()

    class _FakeTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

        def __await__(self):
            async def _inner():
                raise asyncio.CancelledError

            return _inner().__await__()

    fake_task = _FakeTask()
    called = {"close_redis": 0, "force_shutdown": 0}

    real_create_task = mod.asyncio.create_task
    mod.asyncio.create_task = lambda coro: (coro.close(), fake_task)[1]

    async def _close_redis():
        called["close_redis"] += 1

    async def _force_shutdown():
        called["force_shutdown"] += 1

    mod._close_redis_client = _close_redis
    mod._async_force_shutdown_local_llm_processes = _force_shutdown

    async def _run():
        async with mod._app_lifespan(mod.app):
            return None

    try:
        asyncio.run(_run())
    finally:
        mod.asyncio.create_task = real_create_task

    assert fake_task.cancel_called is True
    assert called["close_redis"] == 1
    assert called["force_shutdown"] == 1