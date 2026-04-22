from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt

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


def test_collaboration_participant_legacy_joined_at_mode(monkeypatch):
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "fallback-now")
    ws = _DummyWebSocket()

    participant = web_server._CollaborationParticipant(
        ws,
        "u1",
        "ada",
        "Ada",
        "2026-01-01T00:00:00+00:00",
    )

    assert participant.role == "user"
    assert participant.joined_at == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_leave_collaboration_room_cancels_active_task(monkeypatch):
    websocket = _DummyWebSocket()
    setattr(websocket, "_sidar_room_id", "team:cleanup")
    cancelled = {"value": False}

    class _FakeTask:
        def done(self):
            return False

        def cancel(self):
            cancelled["value"] = True

    web_server._collaboration_rooms["team:cleanup"] = web_server._CollaborationRoom(
        room_id="team:cleanup",
        participants={},
        active_task=_FakeTask(),
    )

    await web_server._leave_collaboration_room(websocket)

    assert cancelled["value"] is True
    assert "team:cleanup" not in web_server._collaboration_rooms


def test_list_child_ollama_pids_parses_ps_output_without_psutil(monkeypatch):
    monkeypatch.setattr(web_server, "os", SimpleNamespace(name="posix", getpid=lambda: 777))
    monkeypatch.setattr(web_server, "subprocess", SimpleNamespace(
        DEVNULL=object(),
        check_output=lambda *args, **kwargs: (
            b" 10 777 ollama ollama serve\n"
            b" 11 777 python python -m app\n"
            b" 12 999 ollama ollama serve\n"
        ),
    ))
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    assert web_server._list_child_ollama_pids() == [10]


def test_reap_child_processes_nonblocking_reaps_until_zero(monkeypatch):
    waitpid_results = iter([(101, 0), (102, 0), (0, 0)])
    monkeypatch.setattr(web_server.os, "waitpid", lambda *args: next(waitpid_results))

    assert web_server._reap_child_processes_nonblocking() == 2


def test_force_shutdown_local_llm_processes_ollama_enabled(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [21, 22])
    calls = {"term": None, "reap": 0}
    monkeypatch.setattr(web_server, "_terminate_ollama_child_pids", lambda pids: calls.update({"term": list(pids)}))
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 3)

    web_server._force_shutdown_local_llm_processes()

    assert calls["term"] == [21, 22]
    assert web_server._shutdown_cleanup_done is True


@pytest.mark.asyncio
async def test_collect_agent_response_joins_chunks():
    class _Agent:
        async def respond(self, _prompt):
            for chunk in [" Mer", "haba ", "dünya "]:
                yield chunk

    text = await web_server._collect_agent_response(_Agent(), "x")
    assert text == "Merhaba dünya"


def test_bind_llm_usage_sink_sets_sink_once(monkeypatch):
    sink_holder = {}

    class _Collector:
        _sidar_usage_sink_bound = False

        def set_usage_sink(self, sink):
            sink_holder["sink"] = sink

    collector = _Collector()
    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: collector)
    agent = SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_provider_usage_daily=lambda **_: None)))

    web_server._bind_llm_usage_sink(agent)
    first_sink = sink_holder.get("sink")
    web_server._bind_llm_usage_sink(agent)

    assert callable(first_sink)
    assert sink_holder.get("sink") is first_sink
    assert collector._sidar_usage_sink_bound is True


@pytest.mark.asyncio
async def test_dispatch_autonomy_trigger_with_handler(monkeypatch):
    class _Agent:
        async def handle_external_trigger(self, trigger):
            return {
                "trigger_id": trigger.trigger_id,
                "source": trigger.source,
                "event_name": trigger.event_name,
                "summary": "ok",
                "status": "success",
                "meta": {"x": "1"},
                "created_at": 1.0,
                "completed_at": 2.0,
                "remediation": {"action": "none"},
            }

    async def _get_agent():
        return _Agent()

    monkeypatch.setattr(web_server, "get_agent", _get_agent)
    result = await web_server._dispatch_autonomy_trigger(
        trigger_source="github",
        event_name="opened",
        payload={"x": 1},
        meta={"a": "b"},
    )

    assert result["status"] == "success"
    assert result["summary"] == "ok"
    assert result["meta"] == {"x": "1"}


def test_fallback_ci_failure_context_for_workflow_run():
    payload = {
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "CI",
            "id": 99,
            "run_number": 18,
            "head_branch": "feature-x",
            "head_sha": "abc",
            "html_url": "http://example/run/99",
            "jobs_url": "http://example/jobs/99",
            "pull_requests": [{"base": {"ref": "main"}}],
        },
    }

    context = web_server._fallback_ci_failure_context("workflow_run", payload)

    assert context["kind"] == "workflow_run"
    assert context["repo"] == "org/repo"
    assert context["run_id"] == "99"
    assert context["base_branch"] == "main"


def test_socket_key_and_participant_serialization():
    websocket = _DummyWebSocket()
    participant = web_server._CollaborationParticipant(
        websocket,
        "u-1",
        "ada",
        "Ada",
        role="developer",
        can_write=True,
        write_scopes=["/tmp/a", "/tmp/b"],
    )

    assert web_server._socket_key(websocket) == id(websocket)
    assert web_server._serialize_collaboration_participant(participant) == {
        "user_id": "u-1",
        "username": "ada",
        "display_name": "Ada",
        "role": "developer",
        "can_write": "true",
        "write_scopes": ["/tmp/a", "/tmp/b"],
        "joined_at": participant.joined_at,
    }


def test_build_user_from_jwt_payload_defaults_and_missing_values():
    assert web_server._build_user_from_jwt_payload({"sub": "1", "username": "ada"}).tenant_id == "default"
    assert web_server._build_user_from_jwt_payload({"sub": "", "username": "ada"}) is None
    assert web_server._build_user_from_jwt_payload({"sub": "1", "username": ""}) is None


def test_get_jwt_secret_fallback_logs_critical(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "JWT_SECRET_KEY", "")
    critical_messages = []
    monkeypatch.setattr(web_server.logger, "critical", lambda msg: critical_messages.append(msg))

    assert web_server._get_jwt_secret() == "sidar-dev-secret"
    assert critical_messages


@pytest.mark.asyncio
async def test_resolve_user_from_token_jwt_success_and_db_fallback(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "JWT_SECRET_KEY", "s3cr3t")
    monkeypatch.setattr(web_server.cfg, "JWT_ALGORITHM", "HS256")

    encoded = jwt.encode({"sub": "42", "username": "lin", "role": "admin", "tenant_id": "t1"}, "s3cr3t", algorithm="HS256")
    user = await web_server._resolve_user_from_token(None, encoded)
    assert user.id == "42"
    assert user.username == "lin"

    class _DB:
        async def get_user_by_token(self, token):
            return SimpleNamespace(id="db-user", username="dbu", role="user", tenant_id="default") if token == "opaque" else None

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))
    fallback_user = await web_server._resolve_user_from_token(agent, "opaque")
    assert fallback_user.id == "db-user"
    assert await web_server._resolve_user_from_token(agent, "missing") is None


@pytest.mark.asyncio
async def test_issue_auth_token_embeds_claims_and_ttl(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "JWT_SECRET_KEY", "token-secret")
    monkeypatch.setattr(web_server.cfg, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(web_server.cfg, "JWT_TTL_DAYS", 3)
    user = SimpleNamespace(id="7", username="ada", role="editor", tenant_id="team-1")

    token = await web_server._issue_auth_token(None, user)
    payload = jwt.decode(token, "token-secret", algorithms=["HS256"])

    assert payload["sub"] == "7"
    assert payload["username"] == "ada"
    assert payload["role"] == "editor"
    assert payload["tenant_id"] == "team-1"
    assert payload["exp"] > payload["iat"]


def test_register_exception_handlers_http_and_unhandled():
    app = web_server.FastAPI()
    web_server._register_exception_handlers(app)

    @app.get("/boom-http")
    async def _boom_http():
        raise HTTPException(status_code=418, detail={"error": "teapot", "code": "E_TEA"})

    @app.get("/boom-exception")
    async def _boom_exception():
        raise RuntimeError("unexpected")

    client = TestClient(app, raise_server_exceptions=False)

    http_res = client.get("/boom-http")
    assert http_res.status_code == 418
    assert http_res.json()["success"] is False
    assert http_res.json()["code"] == "E_TEA"

    err_res = client.get("/boom-exception")
    assert err_res.status_code == 500
    assert err_res.json()["success"] is False
    assert err_res.json()["error"] == "İç sunucu hatası"
