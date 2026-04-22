from pathlib import Path
import re
from types import SimpleNamespace
import io

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import UploadFile

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


def _make_request(path: str, method: str = "GET", headers: dict | None = None, host: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()],
        "client": (host, 12345),
        "query_string": b"",
    }
    return Request(scope)


def test_process_helpers_and_shutdown_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(web_server.os, "waitpid", lambda *_args: (0, 0))
    assert web_server._reap_child_processes_nonblocking() == 0

    monkeypatch.setattr(web_server.os, "waitpid", lambda *_args: (_args and (_ for _ in ()).throw(ChildProcessError())))
    assert web_server._reap_child_processes_nonblocking() == 0

    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(web_server.time, "sleep", lambda _s: None)
    web_server._terminate_ollama_child_pids([10, 11], grace_seconds=0.1)
    assert calls.count((10, web_server.signal.SIGTERM)) == 1
    assert calls.count((10, web_server.signal.SIGKILL)) == 1

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    reaped = []
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.append(True) or 1)
    web_server._force_shutdown_local_llm_processes()
    assert reaped


@pytest.mark.asyncio
async def test_async_shutdown_and_ci_context_resolution(monkeypatch):
    killed = []
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [1])
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr(web_server.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 1)
    await web_server._async_force_shutdown_local_llm_processes()
    assert (1, web_server.signal.SIGTERM) in killed
    assert (1, web_server.signal.SIGKILL) in killed

    workflow_payload = {
        "repository": {"full_name": "acme/repo", "default_branch": "main"},
        "workflow_run": {"status": "completed", "conclusion": "failure", "id": 55, "name": "CI"},
    }
    context = web_server._fallback_ci_failure_context("workflow_run", workflow_payload)
    assert context["kind"] == "workflow_run"

    monkeypatch.setattr(web_server, "build_ci_failure_context", lambda *_args, **_kwargs: {})
    resolved = web_server._resolve_ci_failure_context("check_suite", {"check_suite": {"conclusion": "failure"}})
    assert resolved["kind"] == "check_suite"


def test_plugin_loading_and_persistence(tmp_path, monkeypatch):
    valid_code = (
        "from agent.base_agent import BaseAgent\n"
        "class DemoAgent(BaseAgent):\n"
        "    async def run(self, prompt: str):\n"
        "        return prompt\n"
    )
    cls = web_server._load_plugin_agent_class(valid_code, "DemoAgent", "mod.demo")
    assert cls.__name__ == "DemoAgent"
    assert web_server._validate_plugin_role_name("Demo_Role-1") == "demo_role-1"
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("bad role!")

    monkeypatch.chdir(tmp_path)
    path = web_server._persist_and_import_plugin_file("sample", valid_code.encode("utf-8"), "mod.persisted")
    assert path.exists()
    assert path.suffix == ".py"


def test_policy_and_rbac_helpers():
    request = _make_request("/rag/docs/abc", method="DELETE")
    assert web_server._resolve_policy_from_request(request) == ("rag", "write", "abc")
    assert web_server._build_audit_resource("rag", "x") == "rag:x"
    assert web_server._is_admin_user(SimpleNamespace(role="admin", username="u"))
    with pytest.raises(HTTPException):
        web_server._require_admin_user(SimpleNamespace(role="user", username="normal"))


@pytest.mark.asyncio
async def test_rate_limiting_helpers_and_middlewares(monkeypatch):
    web_server._local_rate_limits.clear()
    monkeypatch.setattr(web_server.time, "time", lambda: 100.0)
    assert not await web_server._local_is_rate_limited("k", 1, 60)
    assert await web_server._local_is_rate_limited("k", 1, 60)

    class _RedisOK:
        def __init__(self):
            self.calls = 0

        async def incr(self, _key):
            self.calls += 1
            return self.calls

        async def expire(self, *_args):
            return True

    async def _fake_get_redis():
        return _RedisOK()

    monkeypatch.setattr(web_server, "_get_redis", _fake_get_redis)
    assert not await web_server._redis_is_rate_limited("ns", "ip", 2, 60)

    async def _call_next(_request):
        return web_server.JSONResponse({"ok": True})

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", lambda *_a, **_k: web_server.asyncio.sleep(0, result=True))
    blocked = await web_server.ddos_rate_limit_middleware(_make_request("/api/x"), _call_next)
    assert blocked.status_code == 429

    blocked_chat = await web_server.rate_limit_middleware(_make_request("/ws/chat"), _call_next)
    assert blocked_chat.status_code == 429


@pytest.mark.asyncio
async def test_files_rag_and_upload_endpoints(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    (root / "bin.exe").write_text("x", encoding="utf-8")

    monkeypatch.setattr(web_server, "__file__", str(root / "web_server.py"))
    listed = await web_server.list_project_files("")
    assert listed.status_code == 200

    ok_file = await web_server.file_content("a.txt")
    assert ok_file.status_code == 200
    unsupported = await web_server.file_content("bin.exe")
    assert unsupported.status_code == 415

    docs = SimpleNamespace(
        get_index_info=lambda session_id: [{"id": "1", "session_id": session_id}],
        add_document_from_url=lambda url, title, session_id: web_server.asyncio.sleep(0, result=(True, f"ok:{url}:{title}:{session_id}")),
        delete_document=lambda doc_id, session_id: f"✓ silindi:{doc_id}:{session_id}",
        add_document_from_file=lambda path, title, _meta, session_id: (True, f"eklendi:{Path(path).name}:{title}:{session_id}"),
    )
    fake_agent = SimpleNamespace(memory=SimpleNamespace(active_session_id="s1"), docs=docs)
    async def _fake_get_agent():
        return fake_agent
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    rag_docs = await web_server.rag_list_docs()
    assert rag_docs.status_code == 200

    class _Req:
        async def json(self):
            return {"url": "https://example.com", "title": "t"}

    rag_url = await web_server.rag_add_url(_Req())
    assert rag_url.status_code == 200
    rag_del = await web_server.rag_delete_doc("doc-1")
    assert rag_del.status_code == 200

    monkeypatch.setattr(web_server.Config, "MAX_RAG_UPLOAD_BYTES", 8)
    upload = UploadFile(file=io.BytesIO(b"abc"), filename="demo.txt")
    up_ok = await web_server.upload_rag_file(upload)
    assert up_ok.status_code == 200

    upload_big = UploadFile(file=io.BytesIO(b"0123456789"), filename="big.txt")
    with pytest.raises(HTTPException):
        await web_server.upload_rag_file(upload_big)
