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


def _load_web_server_with_import_failures(monkeypatch, module_name: str, fail_rules: set[str]):
    """web_server modülünü seçili import hatalarıyla izole şekilde yükler."""
    import builtins
    import importlib.util
    import sys

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if "anyio" in fail_rules and name == "anyio":
            raise ImportError("forced anyio failure")
        if "opentelemetry" in fail_rules and name.startswith("opentelemetry"):
            raise ImportError("forced otel failure")
        if "llm_metrics_reset" in fail_rules and name == "core.llm_metrics" and fromlist:
            if "reset_current_metrics_user_id" in fromlist or "set_current_metrics_user_id" in fromlist:
                raise ImportError("forced llm metrics reset import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    spec = importlib.util.spec_from_file_location(module_name, Path("web_server.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_optional_import_fallbacks_on_module_load(monkeypatch):
    mod = _load_web_server_with_import_failures(
        monkeypatch,
        module_name="web_server_fallback_case",
        fail_rules={"anyio", "opentelemetry", "llm_metrics_reset"},
    )

    assert mod._ANYIO_CLOSED is None
    assert mod.trace is None
    assert mod.FastAPIInstrumentor is None
    assert mod.set_current_metrics_user_id("u1") is None
    assert mod.reset_current_metrics_user_id(None) is None


@pytest.mark.asyncio
async def test_async_force_shutdown_paths(monkeypatch):
    events: list[tuple[str, int]] = []

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 1)
    await web_server._async_force_shutdown_local_llm_processes()
    assert web_server._shutdown_cleanup_done is True

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [201, 202])
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: events.append(("kill", pid)))

    async def _fake_sleep(_):
        events.append(("sleep", 0))

    monkeypatch.setattr(web_server.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 2)
    await web_server._async_force_shutdown_local_llm_processes()

    killed_pids = [pid for action, pid in events if action == "kill"]
    assert killed_pids.count(201) == 2
    assert killed_pids.count(202) == 2
    assert ("sleep", 0) in events


@pytest.mark.asyncio
async def test_prewarm_rag_embeddings_branches(monkeypatch):
    logs = {"info": [], "warn": []}
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: logs["info"].append(msg % args if args else msg))
    monkeypatch.setattr(web_server.logger, "warning", lambda msg, *args: logs["warn"].append(msg % args if args else msg))

    async def _agent_without_rag():
        return SimpleNamespace(rag=None)

    monkeypatch.setattr(web_server, "get_agent", _agent_without_rag)
    await web_server._prewarm_rag_embeddings()
    assert any("rag motoru bulunamadı" in m for m in logs["info"])

    async def _agent_without_chroma():
        return SimpleNamespace(rag=SimpleNamespace(_chroma_available=False))

    monkeypatch.setattr(web_server, "get_agent", _agent_without_chroma)
    await web_server._prewarm_rag_embeddings()
    assert any("ChromaDB kullanılamıyor" in m for m in logs["info"])

    init_calls = {"count": 0}

    class _RagOk:
        _chroma_available = True

        def _init_chroma(self):
            init_calls["count"] += 1

    async def _agent_ok():
        return SimpleNamespace(rag=_RagOk())

    monkeypatch.setattr(web_server, "get_agent", _agent_ok)
    await web_server._prewarm_rag_embeddings()
    assert init_calls["count"] == 1

    async def _agent_fail():
        raise RuntimeError("boom")

    monkeypatch.setattr(web_server, "get_agent", _agent_fail)
    await web_server._prewarm_rag_embeddings()
    assert any("prewarm başarısız" in m for m in logs["warn"])


@pytest.mark.asyncio
async def test_await_if_needed_and_health_response_branches(monkeypatch):
    async def _sample():
        return "awaited"

    assert await web_server._await_if_needed(_sample()) == "awaited"
    assert await web_server._await_if_needed("raw") == "raw"

    monkeypatch.setattr(web_server.time, "monotonic", lambda: 200.0)
    monkeypatch.setattr(web_server, "_start_time", 100.0)

    class _HealthOk:
        def get_health_summary(self):
            return {"status": "ok", "ollama_online": True}

        def get_dependency_health(self):
            return {"redis": {"healthy": True}}

    class _AgentOk:
        cfg = SimpleNamespace(AI_PROVIDER="openai")
        health = _HealthOk()

    async def _get_agent_ok():
        return _AgentOk()

    monkeypatch.setattr(web_server, "get_agent", _get_agent_ok)
    ok_res = await web_server._health_response(require_dependencies=True)
    assert ok_res.status_code == 200
    assert b'"uptime_seconds":100' in ok_res.body

    class _HealthDepsBad(_HealthOk):
        def get_dependency_health(self):
            return {"redis": {"healthy": False}}

    class _AgentDepsBad(_AgentOk):
        health = _HealthDepsBad()

    async def _get_agent_deps_bad():
        return _AgentDepsBad()

    monkeypatch.setattr(web_server, "get_agent", _get_agent_deps_bad)
    bad_dep_res = await web_server._health_response(require_dependencies=True)
    assert bad_dep_res.status_code == 503
    assert b'"status":"degraded"' in bad_dep_res.body

    class _AgentOllamaDown:
        cfg = SimpleNamespace(AI_PROVIDER="ollama")
        health = SimpleNamespace(get_health_summary=lambda: {"status": "ok", "ollama_online": False})

    async def _get_agent_ollama_down():
        return _AgentOllamaDown()

    monkeypatch.setattr(web_server, "get_agent", _get_agent_ollama_down)
    ollama_down = await web_server._health_response(require_dependencies=False)
    assert ollama_down.status_code == 503

    async def _boom_agent():
        raise RuntimeError("health-boom")

    monkeypatch.setattr(web_server, "get_agent", _boom_agent)
    degraded = await web_server._health_response(require_dependencies=False)
    assert degraded.status_code == 503
    assert b'"health_check_failed"' in degraded.body


def test_serialize_record_helpers_cover_defaults_and_values():
    prompt_payload = web_server._serialize_prompt(
        SimpleNamespace(
            id="11",
            role_name="reviewer",
            prompt_text="detay",
            version="2",
            is_active=1,
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
    )
    assert prompt_payload["id"] == 11
    assert prompt_payload["is_active"] is True

    swarm_payload = web_server._serialize_swarm_result(SimpleNamespace(task_id=None, elapsed_ms=None, graph=None))
    assert swarm_payload["task_id"] == ""
    assert swarm_payload["elapsed_ms"] == 0
    assert swarm_payload["graph"] == {}

    campaign_payload = web_server._serialize_campaign(SimpleNamespace(id="9", metadata_json=None, budget="1.5"))
    assert campaign_payload["id"] == 9
    assert campaign_payload["budget"] == 1.5
    assert campaign_payload["metadata_json"] == "{}"

    asset_payload = web_server._serialize_content_asset(SimpleNamespace(id="7", campaign_id="3", content=123))
    assert asset_payload["campaign_id"] == 3
    assert asset_payload["content"] == "123"

    checklist_payload = web_server._serialize_operation_checklist(SimpleNamespace(id="4", campaign_id=None, items_json=None))
    assert checklist_payload["campaign_id"] is None
    assert checklist_payload["items_json"] == "[]"


def test_verify_hmac_signature_and_git_run_paths(monkeypatch):
    web_server._verify_hmac_signature(b"{}", "", "", label="sig")

    with pytest.raises(HTTPException):
        web_server._verify_hmac_signature(b"{}", "secret", "", label="sig")

    with pytest.raises(HTTPException):
        web_server._verify_hmac_signature(b"{}", "secret", "sha256=wrong", label="sig")

    valid = "sha256=" + __import__("hmac").new(b"secret", b"{}", __import__("hashlib").sha256).hexdigest()
    web_server._verify_hmac_signature(b"{}", "secret", valid, label="sig")

    monkeypatch.setattr(web_server.subprocess, "check_output", lambda *a, **k: b"main\n")
    assert web_server._git_run(["git"], ".") == "main"

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_server.subprocess, "check_output", _raise)
    assert web_server._git_run(["git"], ".") == ""


@pytest.mark.asyncio
async def test_autonomy_webhook_ci_and_federation_paths(monkeypatch):
    class _Req:
        def __init__(self, payload: bytes):
            self._payload = payload

        async def body(self):
            return self._payload

    monkeypatch.setattr(web_server.cfg, "ENABLE_EVENT_WEBHOOKS", False)
    with pytest.raises(HTTPException):
        await web_server.autonomy_webhook("github", _Req(b"{}"), x_sidar_signature="")

    monkeypatch.setattr(web_server.cfg, "ENABLE_EVENT_WEBHOOKS", True)
    monkeypatch.setattr(web_server, "_verify_hmac_signature", lambda *a, **k: None)
    bad_json_res = await web_server.autonomy_webhook("github", _Req(b"{"), x_sidar_signature="")
    assert bad_json_res.status_code == 400

    async def _dispatch(**kwargs):
        return {"ok": True, "trigger_source": kwargs["trigger_source"], "payload": kwargs["payload"]}

    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", _dispatch)
    monkeypatch.setattr(web_server, "_resolve_ci_failure_context", lambda *_: {"kind": "workflow_run", "run_id": "42"})
    ci_res = await web_server.autonomy_webhook("github", _Req(b'{"event_name":"workflow_run"}'), x_sidar_signature="")
    ci_body = ci_res.body.decode("utf-8")
    assert ci_res.status_code == 200
    assert "webhook:github:ci_failure" in ci_body
    assert "event_driven_federation\":null" in ci_body

    monkeypatch.setattr(web_server, "_resolve_ci_failure_context", lambda *_: {})
    async def _run_workflow(**_):
        return {"workflow_type": "github_pull_request", "correlation_id": "corr-1"}

    monkeypatch.setattr(web_server, "_run_event_driven_federation_workflow", _run_workflow)
    monkeypatch.setattr(
        web_server,
        "_embed_event_driven_federation_payload",
        lambda payload, workflow: {"embedded": True, "event_payload": payload, "workflow": workflow},
    )
    fed_res = await web_server.autonomy_webhook("github", _Req(b'{"event_name":"pull_request"}'), x_sidar_signature="")
    fed_body = fed_res.body.decode("utf-8")
    assert fed_res.status_code == 200
    assert "event_driven_federation" in fed_body
    assert "github_pull_request" in fed_body


class _JsonRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_sessions_endpoints_cover_success_and_not_found(monkeypatch):
    class _DB:
        async def list_sessions(self, _user_id):
            return [SimpleNamespace(id="s1", title="ilk", updated_at="ts")]

        async def get_session_messages(self, session_id):
            if session_id == "s1":
                return [SimpleNamespace(role="user", content="merhaba", created_at="ts", tokens_used=3)]
            return []

        async def load_session(self, session_id, _user_id):
            return SimpleNamespace(id=session_id) if session_id == "s1" else None

        async def create_session(self, _user_id, _title):
            return SimpleNamespace(id="new-session")

        async def delete_session(self, session_id, _user_id):
            return session_id == "s1"

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB(), _safe_ts=lambda ts: f"safe-{ts}"))
    monkeypatch.setattr(web_server, "get_agent", lambda: agent)
    user = SimpleNamespace(id="u1")
    req = _make_request("/sessions")

    sessions_res = await web_server.get_sessions(req, user=user)
    assert sessions_res.status_code == 200
    assert b'"id":"s1"' in sessions_res.body

    missing_res = await web_server.load_session("missing", req, user=user)
    assert missing_res.status_code == 404

    load_res = await web_server.load_session("s1", req, user=user)
    assert load_res.status_code == 200
    assert b'"success":true' in load_res.body

    new_res = await web_server.new_session(req, user=user)
    assert b'"session_id":"new-session"' in new_res.body

    delete_ok = await web_server.delete_session("s1", req, user=user)
    delete_fail = await web_server.delete_session("s2", req, user=user)
    assert delete_ok.status_code == 200
    assert delete_fail.status_code == 500


@pytest.mark.asyncio
async def test_file_listing_and_content_endpoints_cover_guards(tmp_path, monkeypatch):
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / "visible.txt").write_text("hello", encoding="utf-8")
    (fake_root / "bad.bin").write_bytes(b"\x00\x01")
    (fake_root / ".hidden").mkdir()
    monkeypatch.setattr(web_server, "__file__", str(fake_root / "web_server.py"))

    list_ok = await web_server.list_project_files("")
    assert list_ok.status_code == 200
    assert b"visible.txt" in list_ok.body
    assert b".hidden" not in list_ok.body

    outside = await web_server.list_project_files("../")
    assert outside.status_code == 403

    file_ok = await web_server.file_content("visible.txt")
    assert file_ok.status_code == 200
    assert b'"content":"hello"' in file_ok.body

    file_type = await web_server.file_content("bad.bin")
    assert file_type.status_code == 415

    missing = await web_server.file_content("missing.txt")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_git_and_branch_endpoints(monkeypatch):
    async def _inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(web_server.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(web_server, "_git_run", lambda cmd, *_: {
        "rev-parse": "feature/x",
        "remote": "git@github.com:org/repo.git",
        "symbolic-ref": "origin/main",
        "branch": "main\nfeature/x",
    }[[k for k in ("rev-parse", "remote", "symbolic-ref", "branch") if k in " ".join(cmd)][0]])

    info = await web_server.git_info()
    branches = await web_server.git_branches()
    assert b'"repo":"org/repo"' in info.body
    assert b'"current":"feature/x"' in branches.body

    invalid = await web_server.set_branch(_JsonRequest({"branch": "bad name"}))
    assert invalid.status_code == 400

    monkeypatch.setattr(web_server.subprocess, "check_output", lambda *a, **k: b"")
    ok = await web_server.set_branch(_JsonRequest({"branch": "feature/x"}))
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_github_rag_todo_clear_and_level_endpoints(monkeypatch, tmp_path):
    class _Github:
        repo_name = "org/active"

        def list_repos(self, owner="", limit=200):
            return True, [{"full_name": "org/a"}, {"full_name": "org/z"}]

        def is_available(self):
            return True

        def get_pull_requests_detailed(self, **_):
            return True, [{"number": 1}], None

        def get_pull_request(self, number):
            return (number == 1, {"number": number} if number == 1 else "missing")

        def set_repo(self, repo_name):
            return True, f"set:{repo_name}"

    class _Docs:
        def get_index_info(self, session_id):
            return [{"id": "d1", "session_id": session_id}]

        def add_document_from_file(self, *_):
            return True, "ok-file"

        async def add_document_from_url(self, *_args, **_kwargs):
            return True, "ok-url"

        def delete_document(self, *_):
            return "✓ silindi"

        async def search(self, *_):
            return True, [{"chunk": "x"}]

    clear_calls = {"n": 0}

    async def _clear():
        clear_calls["n"] += 1

    agent = SimpleNamespace(
        github=_Github(),
        docs=_Docs(),
        memory=SimpleNamespace(active_session_id=None, clear=_clear),
        todo=SimpleNamespace(get_tasks=lambda: [{"status": "new"}, {"status": "completed"}]),
        security=SimpleNamespace(level_name="sandbox"),
        set_access_level=lambda lvl: f"ok:{lvl}",
    )
    monkeypatch.setattr(web_server, "get_agent", lambda: agent)

    async def _inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(web_server.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(web_server, "__file__", str(tmp_path / "web_server.py"))
    sample = tmp_path / "note.txt"
    sample.write_text("x", encoding="utf-8")

    repos = await web_server.github_repos(owner="org", q="z")
    prs = await web_server.github_prs()
    pr_detail = await web_server.github_pr_detail(1)
    set_repo = await web_server.set_repo(_JsonRequest({"repo": "org/new"}))
    docs = await web_server.rag_list_docs()
    rag_file = await web_server.rag_add_file(_JsonRequest({"path": "note.txt"}))
    rag_url = await web_server.rag_add_url(_JsonRequest({"url": "https://example.com"}))
    rag_delete = await web_server.rag_delete_doc("d1")
    rag_search_empty = await web_server.rag_search("")
    rag_search_ok = await web_server.rag_search("query", top_k=15)
    todo = await web_server.get_todo()
    clear = await web_server.clear()
    level = await web_server.set_level_endpoint(_JsonRequest({"level": "sandbox"}))

    assert b'"repos"' in repos.body
    assert b'"prs"' in prs.body
    assert b'"success":true' in pr_detail.body
    assert b'"success":true' in set_repo.body
    assert b'"count":1' in docs.body
    assert rag_file.status_code == 200
    assert rag_url.status_code == 200
    assert b'"success":true' in rag_delete.body
    assert rag_search_empty.status_code == 400
    assert rag_search_ok.status_code == 200
    assert b'"active":1' in todo.body
    assert b'"result":true' in clear.body
    assert clear_calls["n"] == 1
    assert b'"current_level":"sandbox"' in level.body


@pytest.mark.asyncio
async def test_vision_endpoints_cover_success_and_import_error(monkeypatch):
    import sys
    import types

    class _Pipeline:
        def __init__(self, llm, _cfg):
            self.llm = llm

        async def analyze(self, **kwargs):
            return {"mode": "analyze", **kwargs}

        async def mockup_to_code(self, **kwargs):
            return f"code:{kwargs['framework']}"

    fake_mod = types.ModuleType("core.vision")
    fake_mod.VisionPipeline = _Pipeline
    fake_mod.build_analyze_prompt = lambda analysis_type: f"prompt:{analysis_type}"
    monkeypatch.setitem(sys.modules, "core.vision", fake_mod)
    monkeypatch.setattr(web_server, "_get_agent_instance", lambda: SimpleNamespace(llm="fake-llm"))

    analyze_req = web_server._VisionAnalyzeRequest(image_base64="abc", analysis_type="ui")
    analyze_res = await web_server.api_vision_analyze(analyze_req)
    assert analyze_res.status_code == 200
    assert b'"mode":"analyze"' in analyze_res.body
    assert b'"prompt":"prompt:ui"' in analyze_res.body

    mockup_req = web_server._VisionMockupRequest(image_base64="abc", framework="react")
    mockup_res = await web_server.api_vision_mockup(mockup_req)
    assert mockup_res.status_code == 200
    assert b'"code":"code:react"' in mockup_res.body

    monkeypatch.delitem(sys.modules, "core.vision", raising=False)
    with pytest.raises(HTTPException):
        await web_server.api_vision_analyze(analyze_req)


@pytest.mark.asyncio
async def test_entity_and_feedback_store_endpoints(monkeypatch):
    class _EntityMem:
        async def initialize(self):
            return None

        async def upsert(self, **_):
            return None

        async def get_profile(self, **_):
            return {"name": "Ada"}

        async def delete(self, **_):
            return True

    class _Feedback:
        async def initialize(self):
            return None

        async def record(self, **_):
            return None

        async def stats(self):
            return {"count": 1}

    web_server._entity_memory_instance = _EntityMem()
    upsert = await web_server.api_entity_upsert(
        web_server._EntityUpsertRequest(user_id="u1", key="skill", value="python", ttl_days=7)
    )
    get_profile = await web_server.api_entity_get_profile("u1")
    delete = await web_server.api_entity_delete("u1", "skill")
    assert upsert.status_code == 200
    assert b'"success":true' in get_profile.body
    assert b'"name":"Ada"' in get_profile.body
    assert b'"success":true' in delete.body

    web_server._feedback_store_instance = _Feedback()
    record = await web_server.api_feedback_record(
        web_server._FeedbackRecordRequest(user_id="u1", prompt="p", response="r", rating=5)
    )
    stats = await web_server.api_feedback_stats()
    assert record.status_code == 200
    assert b'"count":1' in stats.body


@pytest.mark.asyncio
async def test_slack_jira_and_teams_endpoints_error_and_success(monkeypatch):
    class _Slack:
        def __init__(self, available=True):
            self.available = available

        def is_available(self):
            return self.available

        async def send_message(self, **_):
            return True, None

        async def list_channels(self):
            return True, ["general"], None

    web_server._slack_mgr_instance = _Slack(available=False)
    with pytest.raises(HTTPException):
        await web_server.api_slack_send(web_server._SlackSendRequest(text="x"))
    web_server._slack_mgr_instance = _Slack(available=True)
    slack_send = await web_server.api_slack_send(web_server._SlackSendRequest(text="x", channel="#g"))
    slack_channels = await web_server.api_slack_channels()
    assert slack_send.status_code == 200
    assert b'"general"' in slack_channels.body

    class _Jira:
        def is_available(self):
            return True

        async def create_issue(self, **kwargs):
            return True, {"key": f"{kwargs['project_key']}-1"}, None

        async def search_issues(self, **_):
            return True, [{"key": "SIDAR-1"}], None

    monkeypatch.setattr(web_server, "_get_jira_manager", lambda: _Jira())
    jira_create = await web_server.api_jira_create_issue(
        web_server._JiraCreateRequest(project_key="SIDAR", summary="s")
    )
    jira_search = await web_server.api_jira_search_issues("project=SIDAR", max_results=5)
    assert b'"SIDAR-1"' in jira_create.body
    assert b'"total":1' in jira_search.body

    class _Teams:
        def is_available(self):
            return True

        async def send_message(self, **_):
            return True, None

    monkeypatch.setattr(web_server, "_get_teams_manager", lambda: _Teams())
    teams = await web_server.api_teams_send(web_server._TeamsSendRequest(text="hello", title="t"))
    assert teams.status_code == 200


@pytest.mark.asyncio
async def test_operations_autonomy_and_spa_fallback_paths(monkeypatch):
    class _DB:
        async def list_marketing_campaigns(self, **_):
            return [SimpleNamespace(id="1", metadata_json="{}", budget=2.5)]

        async def upsert_marketing_campaign(self, **_):
            return SimpleNamespace(id="1", metadata_json="{}", budget=2.5)

        async def add_content_asset(self, **_):
            return SimpleNamespace(id="2", campaign_id="1", content="asset")

        async def add_operation_checklist(self, **_):
            return SimpleNamespace(id="3", campaign_id="1", items_json='["a"]')

        async def list_content_assets(self, **_):
            return [SimpleNamespace(id="2", campaign_id="1", content="asset")]

        async def list_operation_checklists(self, **_):
            return [SimpleNamespace(id="3", campaign_id="1", items_json='["a"]')]

    agent = SimpleNamespace(
        memory=SimpleNamespace(db=_DB()),
        get_autonomy_activity=lambda limit=20: [{"id": "a1", "limit": limit}],
    )
    monkeypatch.setattr(web_server, "_get_agent_instance", lambda: agent)
    user = SimpleNamespace(id="u1", tenant_id="t1")

    list_campaigns = await web_server.api_operations_list_campaigns(_user=user)
    create_campaign = await web_server.api_operations_create_campaign(
        web_server._CampaignCreateRequest(
            name="Launch",
            initial_assets=[web_server._ContentAssetCreateRequest(asset_type="post", title="t", content="c")],
            initial_checklists=[web_server._OperationChecklistCreateRequest(title="todo", items=["a"])],
        ),
        _user=user,
    )
    assets = await web_server.api_operations_list_assets(1, _user=user)
    add_asset = await web_server.api_operations_add_asset(
        1, web_server._ContentAssetCreateRequest(asset_type="post", title="t", content="c"), _user=user
    )
    checklists = await web_server.api_operations_list_checklists(1, _user=user)
    add_checklist = await web_server.api_operations_add_checklist(
        1, web_server._OperationChecklistCreateRequest(title="todo", items=["a"]), _user=user
    )
    assert b'"campaigns"' in list_campaigns.body
    assert b'"assets"' in create_campaign.body
    assert assets.status_code == 200
    assert add_asset.status_code == 200
    assert checklists.status_code == 200
    assert add_checklist.status_code == 200

    monkeypatch.setattr(
        web_server,
        "_dispatch_autonomy_trigger",
        lambda **kwargs: {"trigger_source": kwargs["trigger_source"], "event_name": kwargs["event_name"]},
    )
    wake = await web_server.autonomy_wake(web_server._AutonomyWakeRequest(prompt=" çalış ", source="user"))
    activity = await web_server.autonomy_activity(limit=7)
    assert b'"trigger_source":"manual:user"' in wake.body
    assert b'"limit":7' in activity.body

    monkeypatch.setattr(web_server, "index", lambda: web_server.Response(status_code=500))
    fallback = await web_server.spa_fallback("deep/link")
    assert fallback.status_code == 200
    assert b"fallback" in fallback.body


@pytest.mark.asyncio
async def test_basic_auth_middleware_branches(monkeypatch):
    async def _call_next(_request):
        return web_server.JSONResponse({"ok": True}, status_code=200)

    open_req = _make_request("/healthz")
    open_res = await web_server.basic_auth_middleware(open_req, _call_next)
    assert open_res.status_code == 200

    unauthorized = await web_server.basic_auth_middleware(_make_request("/admin/stats"), _call_next)
    assert unauthorized.status_code == 401
    assert b"Yetkisiz" in unauthorized.body

    empty_token = await web_server.basic_auth_middleware(
        _make_request("/admin/stats", headers={"Authorization": "Bearer   "}),
        _call_next,
    )
    assert empty_token.status_code == 401
    assert b"Gecersiz token" in empty_token.body or b"Ge\xc3\xa7ersiz token" in empty_token.body

    async def _resolve_none(_agent, _token):
        return None

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_none)
    invalid_session = await web_server.basic_auth_middleware(
        _make_request("/admin/stats", headers={"Authorization": "Bearer token-x"}),
        _call_next,
    )
    assert invalid_session.status_code == 401

    calls = {"active_user": None, "set_token": None, "reset_token": None}

    class _Memory:
        async def set_active_user(self, user_id, username):
            calls["active_user"] = (user_id, username)

    async def _resolve_user(_agent, _token):
        return SimpleNamespace(id="u-1", username="ada", role="user")

    async def _resolve_agent():
        return SimpleNamespace(memory=_Memory())

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "set_current_metrics_user_id", lambda uid: calls.update({"set_token": uid}) or "tok-1")
    monkeypatch.setattr(web_server, "reset_current_metrics_user_id", lambda tok: calls.update({"reset_token": tok}))

    ok = await web_server.basic_auth_middleware(
        _make_request("/admin/stats", headers={"Authorization": "Bearer good-token"}),
        _call_next,
    )
    assert ok.status_code == 200
    assert calls["active_user"] == ("u-1", "ada")
    assert calls["set_token"] == "u-1"
    assert calls["reset_token"] == "tok-1"


@pytest.mark.asyncio
async def test_access_policy_and_rate_limit_middlewares(monkeypatch):
    async def _call_next(_request):
        return web_server.JSONResponse({"ok": True}, status_code=200)

    request_no_user = _make_request("/rag/docs", "GET")
    assert (await web_server.access_policy_middleware(request_no_user, _call_next)).status_code == 200

    logs = []
    monkeypatch.setattr(web_server, "_schedule_access_audit_log", lambda **kwargs: logs.append(kwargs))
    monkeypatch.setattr(web_server, "_get_client_ip", lambda _request: "9.9.9.9")

    admin_req = _make_request("/rag/docs", "GET")
    admin_req.state.user = SimpleNamespace(id="admin", role="admin", username="a", tenant_id="t1")
    admin_res = await web_server.access_policy_middleware(admin_req, _call_next)
    assert admin_res.status_code == 200
    assert logs[-1]["allowed"] is True

    class _DB:
        async def check_access_policy(self, **_):
            return False

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    denied_req = _make_request("/rag/docs/1", "DELETE")
    denied_req.state.user = SimpleNamespace(id="u1", role="user", username="lin", tenant_id="t1")
    denied_res = await web_server.access_policy_middleware(denied_req, _call_next)
    assert denied_res.status_code == 403
    assert logs[-1]["allowed"] is False

    async def _raise_policy(**_):
        raise RuntimeError("db down")

    async def _resolve_agent_fail():
        return SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(check_access_policy=_raise_policy)))

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent_fail)
    denied_on_error = await web_server.access_policy_middleware(denied_req, _call_next)
    assert denied_on_error.status_code == 403

    assert (await web_server.ddos_rate_limit_middleware(_make_request("/healthz"), _call_next)).status_code == 200
    async def _rate_limited(*_args, **_kwargs):
        return True

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _rate_limited)
    ddos_block = await web_server.ddos_rate_limit_middleware(_make_request("/api/x"), _call_next)
    assert ddos_block.status_code == 429

    ws_block = await web_server.rate_limit_middleware(_make_request("/ws/chat", "GET"), _call_next)
    post_block = await web_server.rate_limit_middleware(_make_request("/set-repo", "POST"), _call_next)
    get_block = await web_server.rate_limit_middleware(_make_request("/files", "GET"), _call_next)
    assert ws_block.status_code == 429
    assert post_block.status_code == 429
    assert get_block.status_code == 429

    async def _rate_open(*_args, **_kwargs):
        return False

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _rate_open)
    assert (await web_server.rate_limit_middleware(_make_request("/files", "GET"), _call_next)).status_code == 200


@pytest.mark.asyncio
async def test_federation_and_github_webhook_paths(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "ENABLE_SWARM_FEDERATION", True)
    monkeypatch.setattr(web_server, "_verify_hmac_signature", lambda *args, **kwargs: None)
    async def _dispatch_ok(**kwargs):
        return {
            "summary": "done",
            "trigger_id": "tr-1",
            "trigger_source": kwargs["trigger_source"],
        }

    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", _dispatch_ok)

    fed_res = await web_server.swarm_federation_execute(
        web_server._FederationTaskRequest(
            task_id="task-1",
            source_system="crewai",
            source_agent="planner",
            target_agent="supervisor",
            goal="review code",
            protocol="federation.v1",
            intent="mixed",
            context={"repo": "org/repo"},
            inputs=["a=1"],
            meta={"x": "1"},
            correlation_id="corr-1",
        ),
        x_sidar_signature="sig",
    )
    assert fed_res.status_code == 200
    assert b'"status":"success"' in fed_res.body

    feedback_res = await web_server.swarm_federation_feedback(
        web_server._FederationFeedbackRequest(
            feedback_id="fb-1",
            source_system="crewai",
            source_agent="executor",
            action_name="fix_tests",
            status="completed",
            summary="all good",
            related_task_id="task-1",
            related_trigger_id="tr-1",
            details={"count": 2},
            meta={"x": "1"},
            correlation_id="corr-1",
        ),
        x_sidar_signature="sig",
    )
    assert feedback_res.status_code == 200
    assert b'"feedback_id":"fb-1"' in feedback_res.body

    class _Req:
        def __init__(self, payload: bytes):
            self._payload = payload

        async def body(self):
            return self._payload

    memory_calls = []

    class _Memory:
        async def add(self, role, content):
            memory_calls.append((role, content))

    monkeypatch.setattr(web_server.cfg, "GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setattr(web_server.cfg, "ENABLE_EVENT_WEBHOOKS", True)
    async def _resolve_agent():
        return SimpleNamespace(memory=_Memory())

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_ci_failure_context", lambda *_: {})
    async def _run_federation(**_):
        return {"workflow_type": "github_pull_request", "correlation_id": "corr-2"}

    monkeypatch.setattr(web_server, "_run_event_driven_federation_workflow", _run_federation)
    dispatch_calls = []
    async def _dispatch_capture(**kwargs):
        dispatch_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", _dispatch_capture)
    monkeypatch.setattr(web_server, "_await_if_needed", lambda value: value)

    payload = b'{"action":"opened","pull_request":{"title":"Fix","number":5}}'
    gh_res = await web_server.github_webhook(_Req(payload), x_github_event="pull_request", x_hub_signature_256="")
    assert gh_res.status_code == 200
    assert memory_calls
    assert dispatch_calls

    bad_json = await web_server.github_webhook(_Req(b"{"), x_github_event="push", x_hub_signature_256="")
    assert bad_json.status_code == 400
