from pathlib import Path
import re
import json
import os
import subprocess
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock

import pytest
import pytest_asyncio

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException, Request

from core.db import Database
import web_server
from web_server import app


_DECORATOR_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"')


class _DummyWebSocket:
    def __init__(self, fail: bool = False):
        self.messages = []
        self.fail = fail
        self.headers = {}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("send failure")
        self.messages.append(payload)

    async def accept(self, subprotocol=None):
        pass

    async def close(self, code=1000, reason=""):
        pass

def _collect_app_routes() -> set[tuple[str, str]]:
    source = Path("web_server.py").read_text(encoding="utf-8")
    return {(method.upper(), path) for method, path in _DECORATOR_RE.findall(source)}


def test_auth_and_admin_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("GET", "/auth/me"),
        ("GET", "/admin/stats"),
        ("GET", "/admin/prompts"),
        ("POST", "/admin/prompts"),
        ("POST", "/admin/prompts/activate"),
    }
    assert expected.issubset(routes)


def test_agent_plugin_swarm_and_hitl_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("POST", "/api/agents/register"),
        ("POST", "/api/agents/register-file"),
        ("GET", "/api/plugin-marketplace/catalog"),
        ("POST", "/api/plugin-marketplace/install"),
        ("DELETE", "/api/plugin-marketplace/install/{plugin_id}"),
        ("POST", "/api/swarm/execute"),
        ("GET", "/api/hitl/pending"),
        ("POST", "/api/hitl/request"),
        ("POST", "/api/hitl/respond/{request_id}"),
    }
    assert expected.issubset(routes)


def test_observability_and_health_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/metrics"),
        ("GET", "/metrics/llm/prometheus"),
        ("GET", "/metrics/llm"),
        ("GET", "/api/budget"),
    }
    assert expected.issubset(routes)


def test_session_file_git_and_rag_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("GET", "/sessions/{session_id}"),
        ("POST", "/sessions/new"),
        ("DELETE", "/sessions/{session_id}"),
        ("GET", "/files"),
        ("GET", "/file-content"),
        ("GET", "/git-info"),
        ("GET", "/git-branches"),
        ("POST", "/set-branch"),
        ("GET", "/github-repos"),
        ("POST", "/set-repo"),
        ("GET", "/rag/docs"),
        ("POST", "/rag/add-url"),
        ("DELETE", "/rag/docs/{doc_id}"),
        ("POST", "/api/rag/upload"),
    }
    assert expected.issubset(routes)


def test_web_server_route_table_has_no_duplicate_method_path_pairs():
    source = Path("web_server.py").read_text(encoding="utf-8")
    matches = [(method.upper(), path) for method, path in _DECORATOR_RE.findall(source)]
    assert len(matches) == len(set(matches))


@pytest.fixture(autouse=True)
def _reset_collaboration_state(monkeypatch, tmp_path):
    web_server._collaboration_rooms.clear()
    web_server._hitl_ws_clients.clear()
    web_server._local_rate_limits.clear()
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))
    yield
    web_server._collaboration_rooms.clear()
    web_server._hitl_ws_clients.clear()
    web_server._local_rate_limits.clear()


class _DbBackedMemory:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.active_session_id = "test-session"

    def __len__(self) -> int:
        return 0

    async def set_active_user(self, _user_id: str, _username: str) -> None:
        return None

    async def aupdate_title(self, _title: str) -> None:
        return None

    async def update_title(self, _title: str) -> None:
        return None

    async def clear(self):
        pass


@pytest_asyncio.fixture
async def web_api_client(monkeypatch: pytest.MonkeyPatch, sqlite_db: Database):
    fake_health = MagicMock()
    fake_health.get_health_summary.return_value = {"status": "healthy", "ollama_online": True}
    fake_health.get_gpu_info.return_value = {"devices": []}
    
    fake_docs = MagicMock()
    fake_docs.status.return_value = "ok"
    fake_docs.doc_count = 0
    fake_docs.get_index_info.return_value = []
    
    fake_github = MagicMock()
    fake_github.is_available.return_value = False
    
    fake_web = MagicMock()
    fake_web.is_available.return_value = False
    
    fake_pkg = MagicMock()
    fake_pkg.status.return_value = "ok"
    
    fake_cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="test-model",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="None",
        GPU_COUNT=0,
        CUDA_VERSION="N/A",
        MEMORY_ENCRYPTION_KEY="",
    )

    fake_agent = SimpleNamespace(
        VERSION="3.0.0",
        memory=_DbBackedMemory(sqlite_db), 
        system_prompt="",
        health=fake_health,
        docs=fake_docs,
        github=fake_github,
        web=fake_web,
        pkg=fake_pkg,
        cfg=fake_cfg
    )
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

# ==========================================
# Core, Parsing & Lifecycle Logic Tests
# ==========================================

def test_fallback_ci_failure_context():
    # Test valid workflow_run failure
    payload = {
        "repository": {"full_name": "test/repo"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "CI",
            "id": 123,
            "head_branch": "feature"
        }
    }
    ctx = web_server._fallback_ci_failure_context("workflow_run", payload)
    assert ctx["kind"] == "workflow_run"
    assert ctx["repo"] == "test/repo"
    assert ctx["workflow_name"] == "CI"
    assert ctx["conclusion"] == "failure"
    
    # Test valid check_run failure
    payload_check = {
        "repository": {"full_name": "test/repo2"},
        "check_run": {
            "name": "Linter",
            "conclusion": "failure",
            "id": 456
        }
    }
    ctx2 = web_server._fallback_ci_failure_context("check_run", payload_check)
    assert ctx2["kind"] == "check_run"
    assert ctx2["workflow_name"] == "Linter"

    # Test non-failure
    payload_success = {
        "workflow_run": {
            "status": "completed",
            "conclusion": "success"
        }
    }
    ctx3 = web_server._fallback_ci_failure_context("workflow_run", payload_success)
    assert ctx3 == {}

def test_build_event_driven_federation_spec():
    # Jira spec
    jira_payload = {
        "issue": {
            "key": "SIDAR-123",
            "title": "Bug fix",
            "fields": {"project": {"key": "SIDAR"}}
        }
    }
    spec_jira = web_server._build_event_driven_federation_spec("jira", "issue_created", jira_payload)
    assert spec_jira is not None
    assert spec_jira["workflow_type"] == "jira_issue"
    assert spec_jira["task_id"] == "jira-sidar-123"

    # Github PR spec
    gh_payload = {
        "pull_request": {
            "number": 42,
            "title": "Fix bug",
            "base": {"ref": "main"},
            "head": {"ref": "patch"}
        },
        "repository": {"full_name": "owner/repo"}
    }
    spec_gh = web_server._build_event_driven_federation_spec("github", "opened", gh_payload)
    assert spec_gh is not None
    assert spec_gh["workflow_type"] == "github_pull_request"
    assert spec_gh["task_id"] == "github-pr-42"
    
    # System monitor spec
    sys_payload = {
        "severity": "critical",
        "alert_name": "High CPU"
    }
    spec_sys = web_server._build_event_driven_federation_spec("monitor", "alert", sys_payload)
    assert spec_sys is not None
    assert spec_sys["workflow_type"] == "system_error"

def test_plugin_source_filename_and_validation():
    assert web_server._validate_plugin_role_name("my_role") == "my_role"
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("invalid role!")
        
    assert web_server._plugin_source_filename("test_module") == "<sidar-plugin:test_module>"

def test_load_plugin_agent_class():
    valid_code = """
from agent.base_agent import BaseAgent
class MyCustomAgent(BaseAgent):
    pass
"""
    cls = web_server._load_plugin_agent_class(valid_code, None, "test_mod")
    assert cls.__name__ == "MyCustomAgent"

    invalid_code = """
class NotAnAgent:
    pass
"""
    with pytest.raises(HTTPException) as exc:
        web_server._load_plugin_agent_class(invalid_code, None, "test_mod")
    assert "BaseAgent türevi" in str(exc.value.detail)

def test_resolve_policy_from_request():
    req1 = MagicMock(spec=Request)
    req1.url.path = "/rag/search"
    req1.method = "GET"
    assert web_server._resolve_policy_from_request(req1) == ("rag", "read", "*")

    req2 = MagicMock(spec=Request)
    req2.url.path = "/admin/stats"
    req2.method = "GET"
    assert web_server._resolve_policy_from_request(req2) == ("admin", "manage", "*")

    req3 = MagicMock(spec=Request)
    req3.url.path = "/api/swarm/execute"
    req3.method = "POST"
    assert web_server._resolve_policy_from_request(req3) == ("swarm", "execute", "*")

def test_build_audit_resource():
    assert web_server._build_audit_resource("rag", "123") == "rag:123"
    assert web_server._build_audit_resource("", "123") == ""
    assert web_server._build_audit_resource("github", "") == "github:*"

@pytest.mark.asyncio
async def test_local_rate_limits():
    # Allow 2 requests per 60s
    assert await web_server._local_is_rate_limited("test_key", 2, 60) is False
    assert await web_server._local_is_rate_limited("test_key", 2, 60) is False
    assert await web_server._local_is_rate_limited("test_key", 2, 60) is True

def test_get_client_ip():
    req = MagicMock()
    req.client.host = "192.168.1.1"
    
    web_server.Config.TRUSTED_PROXIES = ["192.168.1.1"]
    req.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
    assert web_server._get_client_ip(req) == "10.0.0.1"

    web_server.Config.TRUSTED_PROXIES = []
    assert web_server._get_client_ip(req) == "192.168.1.1"

@patch("subprocess.check_output")
@patch("os.name", "posix")
def test_list_child_ollama_pids(mock_check_output, monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 100)
    mock_check_output.return_value = b"200 100 ollama serve\n300 100 other_proc\n"
    
    # psutil is not available fallback path
    import sys
    monkeypatch.setitem(sys.modules, "psutil", None)
    
    pids = web_server._list_child_ollama_pids()
    assert pids == [200]

# ==========================================
# Original API Tests & New API Endpoint Tests
# ==========================================

def test_room_id_normalization_and_validation():
    assert web_server._normalize_room_id("  team:alpha  ") == "team:alpha"
    assert web_server._normalize_room_id("") == "workspace:default"
    with pytest.raises(HTTPException):
        web_server._normalize_room_id("<bad>")

def test_collaboration_role_and_write_scope_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))

    assert web_server._normalize_collaboration_role("ADMIN") == "admin"
    assert web_server._normalize_collaboration_role("unknown") == "user"

    admin_scopes = web_server._collaboration_write_scopes_for_role("admin", "room:one")
    assert admin_scopes == [str(tmp_path.resolve())]

    dev_scopes = web_server._collaboration_write_scopes_for_role("developer", "room:one")
    assert dev_scopes == [str((tmp_path / "workspaces" / "room/one").resolve())]

    assert web_server._collaboration_write_scopes_for_role("user", "room:one") == []


def test_command_detection_message_build_and_chunking(monkeypatch):
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: f"masked:{text}")

    assert web_server._collaboration_command_requires_write("please edit file")
    assert web_server._collaboration_command_requires_write("dosya oluştur")
    assert not web_server._collaboration_command_requires_write("sadece oku")

    payload = web_server._build_room_message(
        room_id="room:a",
        role="user",
        content="secret",
        author_name="Ada",
        author_id="u1",
    )
    assert payload["content"] == "masked:secret"
    assert payload["ts"] == "2026-01-01T00:00:00+00:00"

    assert web_server._iter_stream_chunks("", size=2) == []
    assert web_server._iter_stream_chunks("abcdef", size=2) == ["ab", "cd", "ef"]


def test_append_and_serialize_room_data(monkeypatch):
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: text.replace("123", "***"))

    ws_b = _DummyWebSocket()
    ws_a = _DummyWebSocket()
    participant_b = web_server._CollaborationParticipant(ws_b, "u2", "beta", "Beta", "maintainer")
    participant_a = web_server._CollaborationParticipant(ws_a, "u1", "alpha", "Alpha", "user")
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={2: participant_b, 1: participant_a},
    )

    web_server._append_room_message(room, {"content": "m1"}, limit=2)
    web_server._append_room_message(room, {"content": "m2"}, limit=2)
    web_server._append_room_message(room, {"content": "m3"}, limit=2)
    assert [m["content"] for m in room.messages] == ["m2", "m3"]

    web_server._append_room_telemetry(room, {"content": "pii123", "error": "boom123"}, limit=1)
    assert room.telemetry[0]["content"] == "pii***"
    assert room.telemetry[0]["error"] == "boom***"

    serialized = web_server._serialize_collaboration_room(room)
    assert serialized["participants"][0]["display_name"] == "Alpha"
    assert serialized["participants"][1]["display_name"] == "Beta"


@pytest.mark.asyncio
async def test_join_leave_and_broadcast_room_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "now")

    ws_ok = _DummyWebSocket()
    ws_fail = _DummyWebSocket(fail=True)

    room = await web_server._join_collaboration_room(
        ws_ok,
        room_id="team:room",
        user_id="u1",
        username="ada",
        display_name="Ada",
        user_role="developer",
    )
    assert room.room_id == "team:room"
    assert getattr(ws_ok, "_sidar_room_id") == "team:room"
    assert ws_ok.messages[0]["type"] == "room_state"

    room.participants[999] = web_server._CollaborationParticipant(ws_fail, "u2", "lin", "Lin")
    await web_server._broadcast_room_payload(room, {"type": "presence"})
    assert 999 not in room.participants

    await web_server._join_collaboration_room(
        ws_ok,
        room_id="team:other",
        user_id="u1",
        username="ada",
        display_name="Ada",
        user_role="user",
    )
    assert "team:room" not in web_server._collaboration_rooms
    assert getattr(ws_ok, "_sidar_room_id") == "team:other"

    await web_server._leave_collaboration_room(ws_ok)
    assert getattr(ws_ok, "_sidar_room_id") == ""
    assert "team:other" not in web_server._collaboration_rooms


@pytest.mark.asyncio
async def test_hitl_broadcast_and_prompt_helpers():
    ws_ok = _DummyWebSocket()
    ws_fail = _DummyWebSocket(fail=True)
    web_server._hitl_ws_clients.update({ws_ok, ws_fail})

    await web_server._hitl_broadcast({"event": "x"})
    assert ws_ok.messages == [{"event": "x"}]
    assert ws_fail not in web_server._hitl_ws_clients

    assert web_server._is_sidar_mention("Merhaba @sidar nasılsın")
    assert not web_server._is_sidar_mention("Merhaba sidar")
    assert web_server._strip_sidar_mention("  @SIDAR   test komutu  ") == "test komutu"

    ws_actor = _DummyWebSocket()
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={
            1: web_server._CollaborationParticipant(
                ws_actor,
                "u1",
                "ada",
                "Ada",
                role="editor",
                can_write=True,
                write_scopes=["/tmp/workspaces/a"],
            )
        },
        messages=[
            {"role": "user", "author_name": "Ada", "content": "İlk mesaj"},
            {"role": "assistant", "author_name": "Sidar", "content": "Yanıt"},
        ],
    )
    prompt = web_server._build_collaboration_prompt(room, actor_name="Ada", command="README güncelle")
    assert "room_id=workspace:default" in prompt
    assert "requesting_write_scopes=/tmp/workspaces/a" in prompt
    assert "Current command:\nREADME güncelle" in prompt

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
@pytest.mark.asyncio
async def test_files_and_status_endpoints(web_api_client) -> None:
    client, _, _ = web_api_client

    # Test /status
    status_resp = await client.get("/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["version"] == "3.0.0"
    assert status_data["provider"] == "ollama"

    # Test /health
    health_resp = await client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"

    # Test /files (root path)
    files_resp = await client.get("/files")
    assert files_resp.status_code == 200
    assert "items" in files_resp.json()
    
    # Test directory traversal vulnerability protection
    files_hack = await client.get("/files?path=../../etc")
    assert files_hack.status_code == 403
    
    # Test clear memory
    clear_resp = await client.post("/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["result"] is True

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