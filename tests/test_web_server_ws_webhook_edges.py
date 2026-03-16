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