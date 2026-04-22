from pathlib import Path
import re

import pytest
from fastapi import HTTPException

import web_server


_DECORATOR_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"')


class _DummyWebSocket:
    def __init__(self, fail: bool = False):
        self.messages = []
        self.fail = fail

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("send failure")
        self.messages.append(payload)


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
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))
    yield
    web_server._collaboration_rooms.clear()
    web_server._hitl_ws_clients.clear()


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

    # failing participant is pruned during broadcast
    room.participants[999] = web_server._CollaborationParticipant(ws_fail, "u2", "lin", "Lin")
    await web_server._broadcast_room_payload(room, {"type": "presence"})
    assert 999 not in room.participants

    # moving to another room should leave old room
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



def test_collaboration_participant_backward_compat_and_serialization(monkeypatch):
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "fallback-now")
    ws = _DummyWebSocket()

    participant = web_server._CollaborationParticipant(
        ws,
        "u42",
        "neo",
        "Neo",
        "2026-01-01T00:00:00+00:00",
    )
    assert participant.role == "user"
    assert participant.joined_at == "2026-01-01T00:00:00+00:00"
    assert web_server._socket_key(ws) == id(ws)

    serialized = web_server._serialize_collaboration_participant(
        web_server._CollaborationParticipant(
            ws,
            "u1",
            "ada",
            "Ada",
            role="editor",
            can_write=True,
            write_scopes=["/tmp/workspace"],
            joined_at="2026-01-02T00:00:00+00:00",
        )
    )
    assert serialized["can_write"] == "true"
    assert serialized["write_scopes"] == ["/tmp/workspace"]


def test_mask_collaboration_text_fallback(monkeypatch):
    real_import = __import__

    def _boom_import(name, *args, **kwargs):
        if name == "core.dlp":
            raise ImportError("forced")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _boom_import)
    assert web_server._mask_collaboration_text("secret") == "secret"


def test_access_policy_helpers_and_metrics_access(monkeypatch):
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/rag/docs/123",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
            "http_version": "1.1",
        }
    )
    assert web_server._resolve_policy_from_request(request) == ("rag", "write", "*")
    assert web_server._build_audit_resource("rag", "42") == "rag:42"
    assert web_server._build_audit_resource("", "42") == ""

    admin = type("U", (), {"role": "admin", "username": "root", "tenant_id": "t1"})()
    regular = type("U", (), {"role": "user", "username": "neo", "tenant_id": "t2"})()
    assert web_server._is_admin_user(admin)
    assert not web_server._is_admin_user(regular)
    assert web_server._get_user_tenant(type("U", (), {"tenant_id": ""})()) == "default"

    token = "metrics-secret"
    monkeypatch.setattr(web_server.cfg, "METRICS_TOKEN", token)
    request_with_token = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/metrics",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "query_string": b"",
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
            "http_version": "1.1",
        }
    )
    assert web_server._require_metrics_access(request_with_token, regular) is regular

    with pytest.raises(HTTPException):
        web_server._require_metrics_access(
            Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/metrics",
                    "headers": [],
                    "query_string": b"",
                    "client": ("127.0.0.1", 1),
                    "server": ("test", 80),
                    "scheme": "http",
                    "http_version": "1.1",
                }
            ),
            regular,
        )


def test_plugin_validation_loading_and_marketplace_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert web_server._validate_plugin_role_name("  My_Role-1  ") == "my_role-1"
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("bad role!")

    assert web_server._sanitize_capabilities([" read ", "", "write"]) == ["read", "write"]
    assert web_server._plugin_source_filename("hello world") == "<sidar-plugin:hello_world>"

    source = """
from agent.base_agent import BaseAgent
class DemoAgent(BaseAgent):
    ROLE_NAME = "demo"
    async def run(self, prompt: str, context=None) -> str:
        return "ok"
"""
    cls = web_server._load_plugin_agent_class(source, "DemoAgent", "demo_module")
    assert cls.__name__ == "DemoAgent"
    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("class X: pass", None, "bad")

    state = {"aws_management": {"installed_at": "now"}}
    web_server._write_plugin_marketplace_state(state)
    assert web_server._read_plugin_marketplace_state() == state

    broken = web_server._plugin_marketplace_state_path()
    broken.write_text("[]", encoding="utf-8")
    assert web_server._read_plugin_marketplace_state() == {}


@pytest.mark.asyncio
async def test_schedule_access_audit_log_handles_missing_loop(monkeypatch):
    user = type("U", (), {"id": "u1", "tenant_id": "t1"})()

    def _no_loop():
        raise RuntimeError("no loop")

    monkeypatch.setattr(web_server.asyncio, "get_running_loop", _no_loop)
    web_server._schedule_access_audit_log(
        user=user,
        resource_type="rag",
        action="read",
        resource_id="*",
        ip_address="127.0.0.1",
        allowed=True,
    )
