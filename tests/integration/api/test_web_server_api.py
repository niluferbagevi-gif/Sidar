from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pytest_asyncio

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from core.db import Database
import web_server
from web_server import app


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
