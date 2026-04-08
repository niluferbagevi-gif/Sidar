from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import web_server
from web_server import app


@dataclass
class _FakeUser:
    id: str
    username: str
    role: str
    tenant_id: str = "default"


@dataclass
class _FakePrompt:
    id: int
    role_name: str
    prompt_text: str
    version: int
    is_active: bool
    created_at: str
    updated_at: str


class _FakeMemoryDB:
    def __init__(self) -> None:
        self._users: dict[str, _FakeUser] = {}
        self._passwords: dict[str, str] = {}
        self._prompts: dict[int, _FakePrompt] = {}
        self._next_prompt_id = 1

    async def register_user(self, username: str, password: str, tenant_id: str) -> _FakeUser:
        if username in self._users:
            raise ValueError("duplicate")
        user = _FakeUser(id=f"u-{len(self._users) + 1}", username=username, role="user", tenant_id=tenant_id)
        self._users[username] = user
        self._passwords[username] = password
        return user

    async def authenticate_user(self, username: str, password: str) -> _FakeUser | None:
        if self._passwords.get(username) != password:
            return None
        return self._users.get(username)

    async def upsert_prompt(self, role_name: str, prompt_text: str, activate: bool) -> _FakePrompt:
        now = datetime.now(timezone.utc).isoformat()
        prompt = _FakePrompt(
            id=self._next_prompt_id,
            role_name=role_name,
            prompt_text=prompt_text,
            version=1,
            is_active=activate,
            created_at=now,
            updated_at=now,
        )
        self._prompts[prompt.id] = prompt
        self._next_prompt_id += 1
        return prompt

    async def list_prompts(self, role_name: str | None = None) -> list[_FakePrompt]:
        items = list(self._prompts.values())
        if role_name:
            return [item for item in items if item.role_name == role_name]
        return items

    async def activate_prompt(self, prompt_id: int) -> _FakePrompt | None:
        target = self._prompts.get(prompt_id)
        if target is None:
            return None
        for item in self._prompts.values():
            if item.role_name == target.role_name:
                item.is_active = item.id == prompt_id
        target.updated_at = datetime.now(timezone.utc).isoformat()
        return target


class _FakeMemory:
    def __init__(self, db: _FakeMemoryDB) -> None:
        self.db = db

    def __len__(self) -> int:
        return 0

    async def set_active_user(self, _user_id: str, _username: str) -> None:
        return None

    async def aupdate_title(self, _title: str) -> None:
        return None

    async def update_title(self, _title: str) -> None:
        return None


@pytest.fixture
def web_api_client(monkeypatch: pytest.MonkeyPatch):
    fake_db = _FakeMemoryDB()
    fake_agent = SimpleNamespace(memory=_FakeMemory(fake_db), system_prompt="")
    original_overrides = app.dependency_overrides.copy()

    async def _fake_get_agent():
        return fake_agent

    async def _fake_issue_auth_token(_agent, user):
        return f"token-for-{user.username}"

    async def _fake_resolve(agent, token):
        if token == "token-for-admin":
            return _FakeUser(id="admin_id", username="admin", role="admin")
        if token == "token-for-user":
            return _FakeUser(id="user-1", username="normal_user", role="user")
        return None

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_issue_auth_token", _fake_issue_auth_token)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    app.dependency_overrides[web_server._require_admin_user] = (
        lambda: _FakeUser(id="admin-1", username="default_admin", role="admin")
    )

    client = TestClient(app)
    try:
        yield client, fake_db, fake_agent
    finally:
        app.dependency_overrides = original_overrides


@pytest.mark.integration
def test_auth_register_and_login_flow_returns_tokens(web_api_client) -> None:
    client, fake_db, _fake_agent = web_api_client

    register_response = client.post(
        "/auth/register",
        json={"username": "alice", "password": "secret123", "tenant_id": "team-a"},
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["user"]["username"] == "alice"
    assert register_payload["access_token"] == "token-for-alice"

    # /auth/login endpoint'i OAuth2 form yerine Pydantic body (_LoginRequest) ile JSON bekliyor.
    login_response = client.post("/auth/login", json={"username": "alice", "password": "secret123"})
    assert login_response.status_code == 200
    assert login_response.json()["access_token"] == "token-for-alice"

    bad_login = client.post("/auth/login", json={"username": "alice", "password": "wrong-pass"})
    assert bad_login.status_code == 401

    assert "alice" in fake_db._users


@pytest.mark.integration
def test_admin_prompt_routes_persist_and_activate_prompt(web_api_client) -> None:
    client, _fake_db, _fake_agent = web_api_client
    admin_headers = {"Authorization": "Bearer token-for-admin"}

    create_response = client.post(
        "/admin/prompts",
        json={"role_name": "system", "prompt_text": "Be concise", "activate": True},
        headers=admin_headers,
    )
    assert create_response.status_code == 200
    created_prompt = create_response.json()
    assert created_prompt["role_name"] == "system"
    assert created_prompt["is_active"] is True

    list_response = client.get("/admin/prompts", params={"role_name": "system"}, headers=admin_headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["prompt_text"] == "Be concise"

    activate_response = client.post(
        "/admin/prompts/activate",
        json={"prompt_id": created_prompt["id"]},
        headers=admin_headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["id"] == created_prompt["id"]

    missing_prompt = client.post(
        "/admin/prompts/activate",
        json={"prompt_id": 9999},
        headers=admin_headers,
    )
    assert missing_prompt.status_code == 404


@pytest.mark.integration
def test_admin_routes_reject_non_admin_users(web_api_client) -> None:
    client, _, _fake_agent = web_api_client

    original_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides.pop(web_server._require_admin_user, None)
        create_response = client.post(
            "/admin/prompts",
            json={"role_name": "system", "prompt_text": "Hacked", "activate": True},
            headers={"Authorization": "Bearer token-for-user"},
        )

        assert create_response.status_code == 403
    finally:
        app.dependency_overrides = original_overrides


@pytest.mark.integration
def test_chat_websocket_streams_agent_chunks(web_api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _fake_db, fake_agent = web_api_client

    async def mock_respond(prompt, **kwargs):
        assert prompt == "Selam"
        yield "Merhaba, "
        yield "size nasıl yardımcı olabilirim?"

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    fake_agent.respond = mock_respond
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

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
