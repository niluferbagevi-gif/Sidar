import asyncio
import json
import sys
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


class _ModulePatch:
    def __init__(self, name: str, module: types.ModuleType):
        self.name = name
        self.module = module
        self.previous = sys.modules.get(name)

    def __enter__(self):
        sys.modules[self.name] = self.module
        return self.module

    def __exit__(self, exc_type, exc, tb):
        if self.previous is None:
            sys.modules.pop(self.name, None)
        else:
            sys.modules[self.name] = self.previous
        return False


def test_ddos_rate_limit_middleware_returns_429_for_blocked_requests(monkeypatch):
    mod = _load_web_server()

    async def _limited(*_args, **_kwargs):
        return True

    async def _unexpected_next(_request):
        raise AssertionError("call_next should not run for blocked requests")

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _limited)

    resp = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/api/private"), _unexpected_next))

    assert resp.status_code == 429
    assert "Rate Limit Aşıldı" in resp.content["error"]


def test_spa_fallback_returns_404_for_reserved_or_asset_like_paths(monkeypatch):
    mod = _load_web_server()

    async def _unexpected_index():
        raise AssertionError("index should not be called for reserved or asset paths")

    monkeypatch.setattr(mod, "index", _unexpected_index)

    reserved = asyncio.run(mod.spa_fallback("api/system"))
    asset = asyncio.run(mod.spa_fallback("dashboard/app.js"))

    assert reserved.status_code == 404
    assert asset.status_code == 404


def test_websocket_chat_timeout_sends_error_payload_and_leaves_room(monkeypatch):
    mod = _load_web_server()
    left_rooms = []

    class _DB:
        async def get_user_by_token(self, token):
            if token == "valid-token":
                return types.SimpleNamespace(id="u1", username="alice", role="user")
            return None

    class _Memory:
        def __init__(self):
            self.db = _DB()
            self.active_users = []

        async def set_active_user(self, user_id, username=None):
            self.active_users.append((user_id, username))

        def __len__(self):
            return 1

    agent = types.SimpleNamespace(memory=_Memory(), respond=None)

    async def _get_agent():
        return agent

    async def _not_limited(*_args, **_kwargs):
        return False

    async def _leave_room(websocket):
        left_rooms.append(websocket)

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self.sent = []
            self._payloads = [json.dumps({"action": "auth", "token": "valid-token"})]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise TimeoutError("chat timed out")

        async def send_json(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod, "_leave_collaboration_room", _leave_room)

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert {"auth_ok": True} in ws.sent
    assert ws.sent[-1] == {"error": "WebSocket oturumu beklenmedik şekilde sonlandı.", "done": True}
    assert left_rooms == [ws]
    assert agent.memory.active_users == [("u1", "alice")]


def test_websocket_voice_timeout_is_logged_without_crashing(monkeypatch):
    mod = _load_web_server()
    warnings = []

    class _DB:
        async def get_user_by_token(self, token):
            if token == "voice-token":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        db = _DB()

        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

    async def _respond(_text):
        if False:
            yield "unused"

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=_respond)

    async def _get_agent():
        return agent

    multimodal_mod = types.ModuleType("core.multimodal")
    multimodal_mod.MultimodalPipeline = lambda *_args, **_kwargs: object()

    class _WebSocket:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "voice-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            raise TimeoutError("voice timeout")

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert ws.accepted == "voice-token"
    assert {"auth_ok": True} in ws.sent
    assert any("Voice WebSocket beklenmedik hata: voice timeout" in msg for msg in warnings)