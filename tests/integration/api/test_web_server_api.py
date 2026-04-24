from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest
import pytest_asyncio

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from core.db import Database

if "opentelemetry.instrumentation.httpx" not in sys.modules:
    fake_httpx_mod = SimpleNamespace(HTTPXClientInstrumentor=SimpleNamespace(instrument=lambda *a, **k: None))
    sys.modules["opentelemetry.instrumentation.httpx"] = fake_httpx_mod

import web_server
from web_server import app
from core.llm_client import LLMAPIError


class _DbBackedMemory:
    def __init__(self, db: Database) -> None:
        self.db = db

    def __len__(self) -> int:
        return 0

    async def set_active_user(self, _user_id: str, _username: str) -> None:
        return None

    async def aupdate_title(self, _title: str) -> None:
        return None

    async def update_title(self, _title: str) -> None:
        return None


@pytest_asyncio.fixture
async def web_api_client(monkeypatch: pytest.MonkeyPatch, sqlite_db: Database):
    fake_agent = SimpleNamespace(memory=_DbBackedMemory(sqlite_db), system_prompt="")
    original_overrides = app.dependency_overrides.copy()

    async def _fake_get_agent():
        return fake_agent

    async def _fake_issue_auth_token(_agent, user):
        return f"token-for-{user.username}"

    async def _fake_resolve(_agent, token):
        if token == "token-for-admin":
            return SimpleNamespace(id="admin_id", username="admin", role="admin", tenant_id="default")
        if token == "token-for-user":
            return SimpleNamespace(id="user-1", username="normal_user", role="user", tenant_id="default")
        return None

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_issue_auth_token", _fake_issue_auth_token)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    app.dependency_overrides[web_server._require_admin_user] = (
        lambda: SimpleNamespace(id="admin-1", username="default_admin", role="admin", tenant_id="default")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, sqlite_db, fake_agent
        finally:
            app.dependency_overrides = original_overrides


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_register_and_login_flow_returns_tokens(web_api_client) -> None:
    client, sqlite_db, _fake_agent = web_api_client

    register_response = await client.post(
        "/auth/register",
        json={"username": "alice", "password": "secret123", "tenant_id": "team-a"},
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["user"]["username"] == "alice"
    assert register_payload["access_token"] == "token-for-alice"

    login_response = await client.post("/auth/login", json={"username": "alice", "password": "secret123"})
    assert login_response.status_code == 200
    assert login_response.json()["access_token"] == "token-for-alice"

    bad_login = await client.post("/auth/login", json={"username": "alice", "password": "wrong-pass"})
    assert bad_login.status_code == 401

    assert await sqlite_db.authenticate_user("alice", "secret123") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_prompt_routes_persist_and_activate_prompt(web_api_client) -> None:
    client, _sqlite_db, _fake_agent = web_api_client
    admin_headers = {"Authorization": "Bearer token-for-admin"}
    baseline_list_response = await client.get("/admin/prompts", params={"role_name": "system"}, headers=admin_headers)
    assert baseline_list_response.status_code == 200
    baseline_items = baseline_list_response.json()["items"]

    create_response = await client.post(
        "/admin/prompts",
        json={"role_name": "system", "prompt_text": "Be concise", "activate": True},
        headers=admin_headers,
    )
    assert create_response.status_code == 200
    created_prompt = create_response.json()
    assert created_prompt["role_name"] == "system"
    assert created_prompt["is_active"] is True

    list_response = await client.get("/admin/prompts", params={"role_name": "system"}, headers=admin_headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == len(baseline_items) + 1
    assert items[0]["prompt_text"] == "Be concise"

    activate_response = await client.post(
        "/admin/prompts/activate",
        json={"prompt_id": created_prompt["id"]},
        headers=admin_headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["id"] == created_prompt["id"]

    missing_prompt = await client.post(
        "/admin/prompts/activate",
        json={"prompt_id": 9999},
        headers=admin_headers,
    )
    assert missing_prompt.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_routes_reject_non_admin_users(web_api_client) -> None:
    client, _, _fake_agent = web_api_client

    original_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides.pop(web_server._require_admin_user, None)
        create_response = await client.post(
            "/admin/prompts",
            json={"role_name": "system", "prompt_text": "Hacked", "activate": True},
            headers={"Authorization": "Bearer token-for-user"},
        )
        assert create_response.status_code == 403
    finally:
        app.dependency_overrides = original_overrides


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_me_rejects_invalid_token_and_memory_sync_methods_are_callable(web_api_client) -> None:
    client, _sqlite_db, fake_agent = web_api_client

    unauthorized_response = await client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json()["error"] == "Oturum geçersiz veya süresi dolmuş"

    await fake_agent.memory.update_title("Başlık")


@pytest.mark.integration
def test_chat_websocket_streams_agent_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock(spec=Database)
    fake_agent = SimpleNamespace(memory=_DbBackedMemory(mock_db), system_prompt="")

    async def _fake_get_agent():
        return fake_agent

    async def _fake_resolve(_agent, token):
        if token == "token-for-admin":
            return SimpleNamespace(id="admin_id", username="admin", role="admin", tenant_id="default")
        return None

    async def mock_respond(prompt, **kwargs):
        assert prompt == "Selam"
        yield "Merhaba, "
        yield "size nasıl yardımcı olabilirim?"

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    fake_agent.respond = mock_respond
    assert asyncio.run(_fake_resolve(fake_agent, "invalid-token")) is None
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"action": "auth", "token": "token-for-admin"})
            auth_payload = websocket.receive_json()
            assert auth_payload == {"auth_ok": True}

            websocket.send_json({"message": "Selam"})

            chunks: list[str] = []
            done = False
            while not done:
                event = websocket.receive_json()
                if "chunk" in event:
                    chunks.append(event["chunk"])
                done = bool(event.get("done"))

    assert "".join(chunks) == "Merhaba, size nasıl yardımcı olabilirim?"


@pytest.mark.integration
def test_chat_websocket_rejects_invalid_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock(spec=Database)
    fake_agent = SimpleNamespace(memory=_DbBackedMemory(mock_db), system_prompt="")

    async def _fake_get_agent():
        return fake_agent

    async def _fake_resolve(_agent, token):
        if token == "token-for-admin":
            return SimpleNamespace(id="admin_id", username="admin", role="admin", tenant_id="default")
        return None

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    resolved_admin = asyncio.run(_fake_resolve(fake_agent, "token-for-admin"))
    assert resolved_admin is not None
    assert resolved_admin.role == "admin"
    assert asyncio.run(_fake_resolve(fake_agent, "invalid-token")) is None
    assert asyncio.run(_never_rate_limited()) is False
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_json({"action": "auth", "token": "invalid-token"})
                websocket.receive_json()


@pytest.mark.integration
def test_chat_websocket_header_token_auth_and_room_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Memory:
        active_session_id = None

        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

    class _Agent:
        memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield ""

        async def _try_multi_agent(self, _prompt):
            return "ok"

    async def _fake_get_agent():
        return _Agent()

    async def _fake_resolve(_agent, token):
        if token == "header-token":
            return SimpleNamespace(id="u1", username="ada", role="user", tenant_id="default")
        return None

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat", subprotocols=["header-token"]) as websocket:
            def _recv_until(expected_type: str, max_attempts: int = 6) -> dict:
                for _ in range(max_attempts):
                    event = websocket.receive_json()
                    if event.get("type") == expected_type:
                        return event
                raise AssertionError(f"{expected_type} eventi alınamadı")

            assert websocket.receive_json() == {"auth_ok": True}
            websocket.send_json({"action": "join_room", "room_id": "team:room-1", "display_name": "Ada"})
            room_state = _recv_until("room_state")
            assert room_state["type"] == "room_state"

            websocket.send_json({"message": "@sidar"})
            room_message = _recv_until("room_message")
            assert room_message["type"] == "room_message"
            room_error = _recv_until("room_error")
            assert room_error["type"] == "room_error"
            assert "komut bulunamadı" in room_error["error"]


@pytest.mark.integration
def test_chat_websocket_auth_required_and_missing_token_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = Mock(spec=Database)
    fake_agent = SimpleNamespace(memory=_DbBackedMemory(mock_db), system_prompt="")

    async def _fake_get_agent():
        return fake_agent

    async def _fake_resolve(_agent, _token):
        return None

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_json({"message": "auth yok"})
                websocket.receive_json()

        with pytest.raises(Exception):
            with client.websocket_connect("/ws/chat") as websocket:
                websocket.send_json({"action": "auth", "token": ""})
                websocket.receive_json()


@pytest.mark.integration
def test_chat_websocket_rate_limit_and_cancel_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

    class _Agent:
        memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(0.2)
            yield "late"

    async def _fake_get_agent():
        return _Agent()

    async def _fake_resolve(_agent, token):
        if token == "token-for-user":
            return SimpleNamespace(id="u1", username="ada", role="user", tenant_id="default")
        return None

    limiter = {"calls": 0}

    async def _rate_limit_once(*_args, **_kwargs):
        limiter["calls"] += 1
        return limiter["calls"] == 1

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _rate_limit_once)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"action": "auth", "token": "token-for-user"})
            assert websocket.receive_json() == {"auth_ok": True}

            websocket.send_json({"message": "rate-limited"})
            limited = websocket.receive_json()
            assert limited["done"] is True
            assert "Hız Sınırı" in limited["chunk"]

            websocket.send_json({"message": "uzun işlem"})
            websocket.send_json({"action": "cancel"})
            cancelled = websocket.receive_json()
            assert cancelled["done"] is True
            assert "iptal edildi" in cancelled["chunk"]


@pytest.mark.integration
def test_chat_websocket_llm_api_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

    class _Agent:
        memory = _Memory()

        async def respond(self, _msg):
            raise LLMAPIError("openai", "provider failure", status_code=429, retryable=True)
            yield ""

    async def _fake_get_agent():
        return _Agent()

    async def _fake_resolve(_agent, token):
        if token == "token-for-user":
            return SimpleNamespace(id="u1", username="ada", role="user", tenant_id="default")
        return None

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"action": "auth", "token": "token-for-user"})
            assert websocket.receive_json() == {"auth_ok": True}
            websocket.send_json({"message": "Selam"})
            event = websocket.receive_json()
            assert event["done"] is True
            assert "LLM Hatası" in event["chunk"]
