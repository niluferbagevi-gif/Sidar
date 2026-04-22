from pathlib import Path
import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
from starlette.requests import Request

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


def test_trim_autonomy_text_truncates_with_suffix():
    short = web_server._trim_autonomy_text(" kısa ", limit=10)
    assert short == "kısa"

    truncated = web_server._trim_autonomy_text("abcdefghijk", limit=5)
    assert truncated == "abcde …[truncated]"


def test_build_event_driven_federation_spec_for_jira_issue_created():
    payload = {
        "action": "created",
        "issue": {
            "key": "PROJ-42",
            "summary": "Prod hatası",
            "fields": {
                "project": {"key": "PROJ"},
                "status": {"name": "Open"},
                "issuetype": {"name": "Bug"},
                "description": "Ayrıntılı açıklama",
            },
        },
    }

    spec = web_server._build_event_driven_federation_spec("jira", "issue_created", payload)

    assert spec is not None
    assert spec["workflow_type"] == "jira_issue"
    assert spec["task_id"] == "jira-proj-42"
    assert spec["context"]["project_key"] == "PROJ"
    assert any(item.startswith("description=") for item in spec["inputs"])


def test_build_event_driven_federation_spec_for_github_pr_opened():
    payload = {
        "action": "opened",
        "repository": {"full_name": "org/repo"},
        "pull_request": {
            "number": 17,
            "title": "Fix flaky test",
            "body": "Detaylı PR açıklaması",
            "node_id": "PR_node_17",
            "base": {"ref": "main"},
            "head": {"ref": "feature/flaky"},
            "user": {"login": "ada"},
        },
    }

    spec = web_server._build_event_driven_federation_spec("github", "pull_request", payload)

    assert spec is not None
    assert spec["workflow_type"] == "github_pull_request"
    assert spec["task_id"] == "github-pr-17"
    assert spec["context"]["repo"] == "org/repo"
    assert spec["context"]["author"] == "ada"


def test_build_event_driven_federation_spec_for_system_alert(monkeypatch):
    monkeypatch.setattr(web_server.secrets, "token_hex", lambda _: "a1b2c3d4")

    spec = web_server._build_event_driven_federation_spec(
        "system_monitor",
        "incident",
        {"severity": "critical", "alert_name": "db-latency", "message": "timeout"},
    )

    assert spec is not None
    assert spec["workflow_type"] == "system_error"
    assert spec["task_id"] == "system-a1b2c3d4"
    assert spec["context"]["alert_name"] == "db-latency"


def test_build_event_driven_federation_spec_returns_none_for_unknown_source():
    assert web_server._build_event_driven_federation_spec("slack", "message", {"text": "x"}) is None


def test_build_swarm_goal_for_role_includes_context_and_role_marker():
    spec = {"context": {"repo": "org/repo"}, "inputs": ["a=1"]}
    coder_goal = web_server._build_swarm_goal_for_role("Temel hedef", "coder", spec)
    reviewer_goal = web_server._build_swarm_goal_for_role("Temel hedef", "reviewer", spec)

    assert "[EVENT_DRIVEN_SWARM:CODER]" in coder_goal
    assert "[EVENT_DRIVEN_SWARM:REVIEWER]" in reviewer_goal
    assert '"repo": "org/repo"' in coder_goal
    assert '["a=1"]' in reviewer_goal


def test_embed_event_driven_federation_payload_projects_core_fields():
    workflow = {
        "correlation_id": "corr-1",
        "federation_prompt": "prompt",
        "federation_task": {
            "task_id": "task-1",
            "source_system": "github",
            "source_agent": "pull_request_webhook",
            "target_agent": "supervisor",
        },
    }
    out = web_server._embed_event_driven_federation_payload({"hello": "world"}, workflow)

    assert out["kind"] == "federation_task"
    assert out["task_id"] == "task-1"
    assert out["source_system"] == "github"
    assert out["target_agent"] == "supervisor"
    assert out["event_payload"] == {"hello": "world"}


def test_resolve_ci_failure_context_prefers_core_builder(monkeypatch):
    monkeypatch.setattr(web_server, "build_ci_failure_context", lambda *_: {"kind": "from-core", "run_id": "1"})

    result = web_server._resolve_ci_failure_context("workflow_run", {"x": 1})
    assert result == {"kind": "from-core", "run_id": "1"}


def test_resolve_ci_failure_context_falls_back_when_core_empty(monkeypatch):
    monkeypatch.setattr(web_server, "build_ci_failure_context", lambda *_: {})
    monkeypatch.setattr(web_server, "_fallback_ci_failure_context", lambda *_: {"kind": "fallback"})

    result = web_server._resolve_ci_failure_context("workflow_run", {"x": 1})
    assert result == {"kind": "fallback"}


def test_plugin_role_validation_and_sanitizers():
    assert web_server._validate_plugin_role_name("  My-Role_1 ") == "my-role_1"
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("x")
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("invalid role")

    assert web_server._sanitize_capabilities(None) == []
    assert web_server._sanitize_capabilities([" a ", "", "b"]) == ["a", "b"]
    assert web_server._plugin_source_filename("mod / name.py") == "<sidar-plugin:mod_name.py>"


def test_load_plugin_agent_class_discovers_and_validates():
    source = """
from agent.base_agent import BaseAgent
class DemoAgent(BaseAgent):
    ROLE_NAME = "demo"
"""
    cls = web_server._load_plugin_agent_class(source, None, "mod1")
    assert cls.__name__ == "DemoAgent"
    assert web_server._load_plugin_agent_class(source, "DemoAgent", "mod2").__name__ == "DemoAgent"

    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("x = (", None, "bad_syntax")
    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("class NotAgent: pass", None, "no_agent")
    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class(source, "MissingClass", "missing_cls")


def test_persist_and_read_write_plugin_marketplace_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    plugin_path = web_server._persist_and_import_plugin_file("my_plugin", b"x = 1\n", "test_plugin_module")
    assert plugin_path.exists()
    assert plugin_path.name == "my_plugin.py"

    web_server._write_plugin_marketplace_state({"aws_management": {"installed_at": "now"}})
    assert web_server._read_plugin_marketplace_state()["aws_management"]["installed_at"] == "now"

    state_path = web_server._plugin_marketplace_state_path()
    state_path.write_text("{not-json", encoding="utf-8")
    assert web_server._read_plugin_marketplace_state() == {}


def test_get_and_serialize_marketplace_plugin(monkeypatch, tmp_path):
    entrypoint = tmp_path / "demo.py"
    entrypoint.write_text("x=1", encoding="utf-8")
    monkeypatch.setattr(
        web_server,
        "PLUGIN_MARKETPLACE_CATALOG",
        {
            "demo": {
                "plugin_id": "demo",
                "name": "Demo Plugin",
                "summary": "s",
                "description": "d",
                "category": "c",
                "role_name": "demo_role",
                "class_name": "DemoAgent",
                "capabilities": ["x"],
                "version": "1.2.3",
                "entrypoint": entrypoint,
            }
        },
    )
    monkeypatch.setattr(
        web_server.AgentRegistry,
        "get",
        lambda role: SimpleNamespace(
            role_name=role, description="desc", capabilities=["x", "y"], version="9.9.9", is_builtin=False
        ),
    )

    payload = web_server._serialize_marketplace_plugin("demo", installed_state={"installed_at": "t1"})
    assert payload["installed"] is True
    assert payload["entrypoint_exists"] is True
    assert payload["agent"]["role_name"] == "demo_role"

    with pytest.raises(HTTPException):
        web_server._get_plugin_marketplace_entry("missing")


def test_install_uninstall_and_reload_marketplace_plugins(monkeypatch, tmp_path):
    entrypoint = tmp_path / "demo_plugin.py"
    entrypoint.write_text("print('ok')", encoding="utf-8")
    monkeypatch.setattr(
        web_server,
        "PLUGIN_MARKETPLACE_CATALOG",
        {
            "demo": {
                "plugin_id": "demo",
                "name": "Demo Plugin",
                "summary": "s",
                "description": "d",
                "category": "c",
                "role_name": "demo_role",
                "class_name": "DemoAgent",
                "capabilities": ["x"],
                "version": "1.0.0",
                "entrypoint": entrypoint,
            }
        },
    )
    monkeypatch.setattr(web_server, "_serialize_marketplace_plugin", lambda plugin_id: {"plugin_id": plugin_id})
    monkeypatch.setattr(
        web_server,
        "_register_plugin_agent",
        lambda **_: {"role_name": "demo_role", "version": "1.0.0", "description": "d"},
    )
    monkeypatch.setattr(web_server.AgentRegistry, "unregister", lambda *_: True)
    state = {}
    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: dict(state))
    def _write_state(new_state):
        state.clear()
        state.update(new_state)

    monkeypatch.setattr(web_server, "_write_plugin_marketplace_state", _write_state)

    installed = web_server._install_marketplace_plugin("demo", persist=True)
    assert installed["success"] is True
    assert "demo" in state

    removed = web_server._uninstall_marketplace_plugin("demo")
    assert removed["success"] is True
    assert "demo" not in state

    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: {"demo": {}, "unknown": {}})
    monkeypatch.setattr(web_server, "_install_marketplace_plugin", lambda plugin_id: {"plugin_id": plugin_id})
    assert web_server._reload_persisted_marketplace_plugins() == [{"plugin_id": "demo"}]


def _make_request(path: str, method: str = "GET", headers: dict | None = None, client_ip: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (client_ip, 12345),
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


def test_policy_resolution_helpers_and_metrics_access(monkeypatch):
    assert web_server._resolve_policy_from_request(_make_request("/rag/docs", "GET")) == ("rag", "read", "*")
    assert web_server._resolve_policy_from_request(_make_request("/rag/docs/1", "DELETE")) == ("rag", "write", "1")
    assert web_server._resolve_policy_from_request(_make_request("/github-prs", "POST")) == ("github", "write", "*")
    assert web_server._resolve_policy_from_request(_make_request("/api/agents/register", "POST")) == ("agents", "register", "*")
    assert web_server._resolve_policy_from_request(_make_request("/unknown", "GET")) == ("", "", "")
    assert web_server._build_audit_resource("rag", "") == "rag:*"
    assert web_server._build_audit_resource("", "1") == ""

    user = SimpleNamespace(role="admin", username="ada", tenant_id="team-1")
    assert web_server._get_user_tenant(user) == "team-1"
    assert web_server._is_admin_user(user) is True
    monkeypatch.setattr(web_server.cfg, "METRICS_TOKEN", "tok")
    req = _make_request("/metrics", headers={"Authorization": "Bearer tok"})
    assert web_server._require_metrics_access(req, user) is user
    with pytest.raises(HTTPException):
        web_server._require_metrics_access(_make_request("/metrics"), SimpleNamespace(role="user", username="lin"))


@pytest.mark.asyncio
async def test_schedule_access_audit_log_and_rate_limit_helpers(monkeypatch):
    user = SimpleNamespace(id="u1", tenant_id="t1")
    called = {"audit": None}

    async def _record_audit_log(**kwargs):
        called["audit"] = kwargs

    async def _get_agent():
        return SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_audit_log=_record_audit_log)))

    monkeypatch.setattr(web_server, "get_agent", _get_agent)
    web_server._schedule_access_audit_log(
        user=user, resource_type="rag", action="read", resource_id="doc-1", ip_address="1.1.1.1", allowed=True
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert called["audit"]["resource"] == "rag:doc-1"

    web_server._local_rate_limits.clear()
    assert await web_server._local_is_rate_limited("k1", limit=2, window_sec=60) is False
    assert await web_server._local_is_rate_limited("k1", limit=2, window_sec=60) is False
    assert await web_server._local_is_rate_limited("k1", limit=2, window_sec=60) is True

    monkeypatch.setattr(web_server.Config, "TRUSTED_PROXIES", {"127.0.0.1"})
    trusted = "127.0.0.1"
    req = _make_request("/x", headers={"X-Forwarded-For": "9.9.9.9"}, client_ip=trusted)
    assert web_server._get_client_ip(req) == "9.9.9.9"


@pytest.mark.asyncio
async def test_redis_rate_limit_fallback_and_redis_paths(monkeypatch):
    class _RedisOk:
        def __init__(self):
            self.count = 0

        async def incr(self, *_):
            self.count += 1
            return self.count

        async def expire(self, *_):
            return True

    async def _get_redis_ok():
        return _RedisOk()

    monkeypatch.setattr(web_server, "_get_redis", _get_redis_ok)
    assert await web_server._redis_is_rate_limited("chat", "1.1.1.1", 2, 60) is False

    class _RedisErr:
        async def incr(self, *_):
            raise RuntimeError("redis down")

    async def _get_redis_err():
        return _RedisErr()

    monkeypatch.setattr(web_server, "_get_redis", _get_redis_err)
    web_server._local_rate_limits.clear()
    assert await web_server._redis_is_rate_limited("chat", "1.1.1.1", 1, 60) is False
    assert await web_server._redis_is_rate_limited("chat", "1.1.1.1", 1, 60) is True
