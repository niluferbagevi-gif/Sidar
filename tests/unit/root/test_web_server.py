import asyncio
import io
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
from pydantic import ValidationError
from starlette.datastructures import UploadFile
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


def test_force_shutdown_local_llm_processes_non_ollama_and_idempotent(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    reaped = {"count": 0}
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("count", reaped["count"] + 1))

    web_server._force_shutdown_local_llm_processes()
    assert reaped["count"] == 1
    assert web_server._shutdown_cleanup_done is True

    # ikinci çağrı idempotent olmalı; reaper tekrar çağrılmamalı
    web_server._force_shutdown_local_llm_processes()
    assert reaped["count"] == 1


def test_force_shutdown_local_llm_processes_ollama_without_force_kill(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    calls = {"reap": 0, "terminate": 0}
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: calls.__setitem__("reap", calls["reap"] + 1))
    monkeypatch.setattr(web_server, "_terminate_ollama_child_pids", lambda *_: calls.__setitem__("terminate", calls["terminate"] + 1))

    web_server._force_shutdown_local_llm_processes()

    assert calls["reap"] == 1
    assert calls["terminate"] == 0
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
async def test_bind_llm_usage_sink_persists_usage_and_handles_errors(monkeypatch):
    captured = {}
    persisted = {"calls": []}

    class _Collector:
        _sidar_usage_sink_bound = False

        def set_usage_sink(self, sink):
            captured["sink"] = sink

    async def _record_provider_usage_daily(**kwargs):
        persisted["calls"].append(kwargs)

    agent = SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_provider_usage_daily=_record_provider_usage_daily)))
    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: _Collector())

    web_server._bind_llm_usage_sink(agent)
    sink = captured["sink"]

    sink(SimpleNamespace(user_id="u-1", provider="openai", total_tokens="15"))
    await asyncio.sleep(0)
    assert persisted["calls"][0]["user_id"] == "u-1"
    assert persisted["calls"][0]["tokens_used"] == 15

    debug_logs = []
    monkeypatch.setattr(web_server.logger, "debug", lambda msg, *args: debug_logs.append(msg % args if args else msg))

    async def _raise_db_error(**_kwargs):
        raise RuntimeError("db unavailable")

    agent.memory.db.record_provider_usage_daily = _raise_db_error
    sink(SimpleNamespace(user_id="u-2", provider="openai", total_tokens=3))
    await asyncio.sleep(0)
    assert any("LLM usage DB yazımı atlandı" in msg for msg in debug_logs)


def test_bind_llm_usage_sink_skips_when_no_running_loop(monkeypatch):
    captured = {}

    class _Collector:
        _sidar_usage_sink_bound = False

        def set_usage_sink(self, sink):
            captured["sink"] = sink

    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: _Collector())
    monkeypatch.setattr(web_server.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no-loop")))
    agent = SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_provider_usage_daily=lambda **_: None)))

    web_server._bind_llm_usage_sink(agent)
    captured["sink"](SimpleNamespace(user_id="u-1", provider="openai", total_tokens=2))


@pytest.mark.asyncio
async def test_get_agent_initializes_once_and_reuses_singleton(monkeypatch):
    created = {"count": 0}

    class _FakeAgent:
        def __init__(self, _cfg):
            created["count"] += 1

        async def initialize(self):
            return None

    monkeypatch.setattr(web_server, "SidarAgent", _FakeAgent)
    monkeypatch.setattr(web_server, "_bind_llm_usage_sink", lambda _agent: None)
    monkeypatch.setattr(web_server, "_agent", None)
    monkeypatch.setattr(web_server, "_agent_lock", asyncio.Lock())

    first = await web_server.get_agent()
    second = await web_server.get_agent()

    assert first is second
    assert created["count"] == 1


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


@pytest.mark.asyncio
async def test_dispatch_autonomy_trigger_without_handler_uses_action_feedback_prompt(monkeypatch):
    captured = {"prompt": None}

    class _Agent:
        async def respond(self, prompt):
            captured["prompt"] = prompt
            for chunk in [" özet ", "oluştu "]:
                yield chunk

    async def _resolve_agent():
        return _Agent()

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    result = await web_server._dispatch_autonomy_trigger(
        trigger_source="jira",
        event_name="feedback",
        payload={
            "kind": "action_feedback",
            "feedback_id": "fb-1",
            "source_system": "jira",
            "action_name": "assign_ticket",
            "status": "ok",
            "summary": "Ticket atandı",
            "details": {"k": "v"},
        },
        meta={"tenant": "t1"},
    )

    assert "ACTION FEEDBACK" in (captured["prompt"] or "").upper()
    assert result["status"] == "success"
    assert result["summary"] == "özet oluştu"
    assert result["meta"] == {"tenant": "t1"}


@pytest.mark.asyncio
async def test_get_agent_instance_and_resolve_agent_instance_with_sync_overrides(monkeypatch):
    fake_agent = SimpleNamespace(name="sync-agent")
    monkeypatch.setattr(web_server, "get_agent", lambda: fake_agent)
    assert await web_server._get_agent_instance() is fake_agent

    monkeypatch.setattr(web_server, "_get_agent_instance", lambda: fake_agent)
    assert await web_server._resolve_agent_instance() is fake_agent


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


def test_fallback_ci_failure_context_for_check_run_and_suite_and_generic_payload():
    check_run_payload = {
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "check_run": {
            "id": 7,
            "name": "lint",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "abc",
            "html_url": "http://example/check/7",
            "details_url": "http://example/check/7/details",
            "output": {"title": "Lint failed", "summary": "2 errors", "text": "flake8 E999"},
        },
    }
    check_run_context = web_server._fallback_ci_failure_context("check_run", check_run_payload)
    assert check_run_context["kind"] == "check_run"
    assert check_run_context["workflow_name"] == "lint"
    assert "flake8" in check_run_context["log_excerpt"]

    check_suite_payload = {
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "check_suite": {
            "id": 9,
            "status": "completed",
            "conclusion": "timed_out",
            "head_branch": "feature/x",
            "head_sha": "def",
            "app": {"name": "GitHub Actions"},
            "url": "http://example/suite/9",
        },
    }
    suite_context = web_server._fallback_ci_failure_context("check_suite", check_suite_payload)
    assert suite_context["kind"] == "check_suite"
    assert suite_context["workflow_name"] == "GitHub Actions"
    assert suite_context["branch"] == "feature/x"

    generic_payload = {
        "repo": "group/repo",
        "pipeline_id": 101,
        "pipeline_number": "55",
        "target_branch": "main",
        "ref": "feature/y",
        "commit": "123abc",
        "status": "completed",
        "conclusion": "failed",
        "pipeline_url": "http://example/pipeline/101",
        "logs": "Build crashed",
        "summary": "Pipeline failed",
        "jobs": [{"name": "test"}],
    }
    generic_context = web_server._fallback_ci_failure_context("pipeline_failed", generic_payload)
    assert generic_context["kind"] == "generic_ci_failure"
    assert generic_context["repo"] == "group/repo"
    assert generic_context["run_id"] == "101"
    assert generic_context["failure_summary"] == "Pipeline failed"


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


@pytest.mark.asyncio
async def test_resolve_user_from_token_invalid_jwt_without_db_returns_none(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "JWT_SECRET_KEY", "s3cr3t")
    monkeypatch.setattr(web_server.cfg, "JWT_ALGORITHM", "HS256")

    user = await web_server._resolve_user_from_token(None, "not-a-jwt-token")
    assert user is None


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


def test_register_exception_handlers_without_exception_handler_attr_is_noop():
    class _NoExceptionHandler:
        pass

    web_server._register_exception_handlers(_NoExceptionHandler())


@pytest.mark.asyncio
async def test_basic_auth_middleware_auth_paths(monkeypatch):
    async def _ok_next(_request):
        return web_server.JSONResponse({"ok": True}, status_code=200)

    open_req = _make_request("/", method="GET")
    open_res = await web_server.basic_auth_middleware(open_req, _ok_next)
    assert open_res.status_code == 200

    denied = await web_server.basic_auth_middleware(_make_request("/secure", method="GET"), _ok_next)
    assert denied.status_code == 401
    assert b"Yetkisiz" in denied.body

    empty_token_req = _make_request("/secure", method="GET", headers={"Authorization": "Bearer   "})
    empty_token_res = await web_server.basic_auth_middleware(empty_token_req, _ok_next)
    assert empty_token_res.status_code == 401
    assert b"Ge" in empty_token_res.body  # Geçersiz token

    async def _resolve_none(*_):
        return None

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_none)
    invalid_req = _make_request("/secure", method="GET", headers={"Authorization": "Bearer bad"})
    invalid_res = await web_server.basic_auth_middleware(invalid_req, _ok_next)
    assert invalid_res.status_code == 401
    assert b"ge" in invalid_res.body.lower()  # geçersiz/süresi dolmuş

    events = {"active_user": None, "metric_set": None, "metric_reset": None}

    async def _resolve_user(*_):
        return SimpleNamespace(id="u1", username="ada", role="admin", tenant_id="t1")

    async def _set_active_user(user_id, username):
        events["active_user"] = (user_id, username)

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=_set_active_user))

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "set_current_metrics_user_id", lambda uid: events.__setitem__("metric_set", uid) or "tok")
    monkeypatch.setattr(web_server, "reset_current_metrics_user_id", lambda token: events.__setitem__("metric_reset", token))

    valid_req = _make_request("/secure", method="GET", headers={"Authorization": "Bearer valid-token"})
    valid_res = await web_server.basic_auth_middleware(valid_req, _ok_next)
    assert valid_res.status_code == 200
    assert events["active_user"] == ("u1", "ada")
    assert events["metric_set"] == "u1"
    assert events["metric_reset"] == "tok"
    assert getattr(valid_req.state, "user").id == "u1"


def test_trim_autonomy_text_truncates_with_suffix():
    short = web_server._trim_autonomy_text(" kısa ", limit=10)
    assert short == "kısa"

    truncated = web_server._trim_autonomy_text("abcdefghijk", limit=5)
    assert truncated == "abcde …[truncated]"


def test_plugin_role_capabilities_and_filename_helpers():
    assert web_server._validate_plugin_role_name("  Custom-Role_9 ") == "custom-role_9"
    with pytest.raises(HTTPException):
        web_server._validate_plugin_role_name("!")

    assert web_server._sanitize_capabilities([" read ", "", " write", "   "]) == ["read", "write"]
    assert web_server._sanitize_capabilities(None) == []

    assert web_server._plugin_source_filename(" my/plugin ") == "<sidar-plugin:my_plugin>"
    assert web_server._plugin_source_filename("") == "<sidar-plugin:plugin>"


def test_plugin_marketplace_state_read_write_and_bad_payload(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert web_server._read_plugin_marketplace_state() == {}

    state = {"aws_management": {"installed_at": "2026-01-01T00:00:00+00:00"}}
    web_server._write_plugin_marketplace_state(state)
    assert web_server._read_plugin_marketplace_state() == state

    bad_path = web_server._plugin_marketplace_state_path()
    bad_path.write_text("[]", encoding="utf-8")
    assert web_server._read_plugin_marketplace_state() == {}

    bad_path.write_text("{", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(web_server.logger, "warning", lambda *args, **kwargs: warnings.append(args))
    assert web_server._read_plugin_marketplace_state() == {}
    assert warnings


@pytest.mark.asyncio
async def test_app_lifespan_starts_and_cleans_background_tasks(monkeypatch):
    cancelled = {"prewarm": False, "cron": False, "nightly": False}
    thread_calls = {"count": 0}
    cleanup = {"redis": 0, "shutdown": 0}

    async def _wait_forever(key):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled[key] = True
            raise

    async def _prewarm():
        await _wait_forever("prewarm")

    async def _cron(_stop_event):
        await _wait_forever("cron")

    async def _nightly(_stop_event):
        await _wait_forever("nightly")

    async def _close_redis():
        cleanup["redis"] += 1

    async def _shutdown():
        cleanup["shutdown"] += 1

    async def _to_thread(func, *args, **kwargs):
        thread_calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(web_server, "_prewarm_rag_embeddings", _prewarm)
    monkeypatch.setattr(web_server, "_autonomous_cron_loop", _cron)
    monkeypatch.setattr(web_server, "_nightly_memory_loop", _nightly)
    monkeypatch.setattr(web_server, "_close_redis_client", _close_redis)
    monkeypatch.setattr(web_server, "_async_force_shutdown_local_llm_processes", _shutdown)
    monkeypatch.setattr(web_server.asyncio, "to_thread", _to_thread)
    monkeypatch.setattr(web_server.cfg, "ENABLE_AUTONOMOUS_CRON", True)
    monkeypatch.setattr(web_server.cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", True)
    monkeypatch.setattr(web_server.Config, "validate_critical_settings", staticmethod(lambda: None))
    monkeypatch.setattr(web_server, "_reload_persisted_marketplace_plugins", lambda: [])

    async with web_server._app_lifespan(web_server.FastAPI()):
        assert isinstance(web_server._agent_lock, asyncio.Lock)
        assert isinstance(web_server._redis_lock, asyncio.Lock)
        assert isinstance(web_server._local_rate_lock, asyncio.Lock)

    assert thread_calls["count"] == 2
    assert cancelled["prewarm"] is True
    assert web_server._autonomy_cron_task is None or web_server._autonomy_cron_task.done()
    assert web_server._nightly_memory_task is None or web_server._nightly_memory_task.done()
    assert cleanup["redis"] == 1
    assert cleanup["shutdown"] == 1


@pytest.mark.asyncio
async def test_autonomous_cron_loop_skips_when_prompt_blank(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "AUTONOMOUS_CRON_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(web_server.cfg, "AUTONOMOUS_CRON_PROMPT", "   ")

    logs: list[str] = []
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: logs.append(msg % args if args else msg))

    stop_event = asyncio.Event()
    await web_server._autonomous_cron_loop(stop_event)

    assert any("prompt boş" in item for item in logs)


@pytest.mark.asyncio
async def test_metrics_returns_json_payload_and_prometheus_importerror_fallback(monkeypatch):
    class _Memory:
        def __len__(self):
            return 4

        def get_all_sessions(self):
            return ["s1", "s2"]

    fake_agent = SimpleNamespace(
        VERSION="test-1.0",
        cfg=SimpleNamespace(AI_PROVIDER="openai", USE_GPU=False),
        docs=SimpleNamespace(doc_count=3),
        memory=_Memory(),
    )
    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: fake_agent)
    monkeypatch.setattr(web_server, "_local_rate_limits", {"u1": [1, 2]})
    monkeypatch.setattr(
        web_server,
        "get_llm_metrics_collector",
        lambda: SimpleNamespace(snapshot=lambda: {"totals": {"calls": 7, "total_tokens": 99}}),
    )

    json_req = _make_request("/metrics")
    json_res = await web_server.metrics(json_req, _user=SimpleNamespace(role="admin"))
    assert json_res.status_code == 200
    assert b'"llm_calls":7' in json_res.body
    assert b'"sessions_total":2' in json_res.body

    import builtins

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "prometheus_client":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    prom_req = _make_request("/metrics", headers={"accept": "text/plain"})
    prom_res = await web_server.metrics(prom_req, _user=SimpleNamespace(role="admin"))
    assert prom_res.status_code == 200
    assert b'"provider":"openai"' in prom_res.body


@pytest.mark.asyncio
async def test_upload_rag_file_success_too_large_and_backend_failure(monkeypatch):
    calls = {"add": []}

    class _Docs:
        def add_document_from_file(self, path, original_name, _meta, session_id):
            calls["add"].append((path, original_name, session_id))
            return True, "eklendi"

    fake_agent = SimpleNamespace(docs=_Docs(), memory=SimpleNamespace(active_session_id=None))
    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: fake_agent)
    monkeypatch.setattr(web_server.Config, "MAX_RAG_UPLOAD_BYTES", 8)

    ok_file = UploadFile(filename="demo.txt", file=io.BytesIO(b"hello"))
    ok_res = await web_server.upload_rag_file(ok_file)
    assert ok_res.status_code == 200
    assert b'"success":true' in ok_res.body
    assert calls["add"][0][1] == "demo.txt"
    assert calls["add"][0][2] == "global"

    big_file = UploadFile(filename="big.bin", file=io.BytesIO(b"123456789"))
    with pytest.raises(HTTPException) as exc_info:
        await web_server.upload_rag_file(big_file)
    assert exc_info.value.status_code == 413

    class _FailDocs:
        def add_document_from_file(self, *_args, **_kwargs):
            return False, "parse failed"

    fake_agent_fail = SimpleNamespace(docs=_FailDocs(), memory=SimpleNamespace(active_session_id="room-1"))
    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: fake_agent_fail)
    fail_file = UploadFile(filename="bad.txt", file=io.BytesIO(b"hello"))
    fail_res = await web_server.upload_rag_file(fail_file)
    assert fail_res.status_code == 400
    assert b'parse failed' in fail_res.body


@pytest.mark.asyncio
async def test_entity_feedback_slack_jira_teams_endpoints(monkeypatch):
    events = {"upsert": None, "delete": None, "feedback": None}

    class _EntityMemory:
        async def upsert(self, **kwargs):
            events["upsert"] = kwargs

        async def get_profile(self, user_id):
            return {"user_id": user_id, "prefs": {"lang": "tr"}}

        async def delete(self, user_id, key):
            events["delete"] = (user_id, key)
            return True

    monkeypatch.setattr(web_server, "_entity_memory_instance", _EntityMemory())
    upsert_res = await web_server.api_entity_upsert(
        web_server._EntityUpsertRequest(user_id="u1", key="timezone", value="UTC", ttl_days=7)
    )
    assert upsert_res.status_code == 200
    assert events["upsert"]["key"] == "timezone"

    profile_res = await web_server.api_entity_get_profile("u1")
    assert profile_res.status_code == 200
    assert b'"success":true' in profile_res.body

    delete_res = await web_server.api_entity_delete("u1", "timezone")
    assert delete_res.status_code == 200
    assert events["delete"] == ("u1", "timezone")

    class _FeedbackStore:
        async def record(self, **kwargs):
            events["feedback"] = kwargs

        async def stats(self):
            return {"avg_rating": 4.5}

    monkeypatch.setattr(web_server, "_feedback_store_instance", _FeedbackStore())
    record_res = await web_server.api_feedback_record(
        web_server._FeedbackRecordRequest(
            user_id="u1",
            prompt="p",
            response="r",
            rating=5,
            note="ok",
        )
    )
    assert record_res.status_code == 200
    assert events["feedback"]["rating"] == 5
    stats_res = await web_server.api_feedback_stats()
    assert stats_res.status_code == 200
    assert b'avg_rating' in stats_res.body

    class _SlackMgr:
        def __init__(self, available=True, send_ok=True, channels_ok=True):
            self._available = available
            self._send_ok = send_ok
            self._channels_ok = channels_ok

        def is_available(self):
            return self._available

        async def send_message(self, **_kwargs):
            return self._send_ok, "err"

        async def list_channels(self):
            if self._channels_ok:
                return True, [{"id": "C1"}], ""
            return False, [], "boom"

    monkeypatch.setattr(web_server, "_get_slack_manager", lambda: _SlackMgr(available=False))
    with pytest.raises(HTTPException):
        await web_server.api_slack_send(web_server._SlackSendRequest(text="merhaba"))
    with pytest.raises(HTTPException):
        await web_server.api_slack_channels()

    monkeypatch.setattr(web_server, "_get_slack_manager", lambda: _SlackMgr(available=True, send_ok=False))
    with pytest.raises(HTTPException):
        await web_server.api_slack_send(web_server._SlackSendRequest(text="merhaba"))

    monkeypatch.setattr(web_server, "_get_slack_manager", lambda: _SlackMgr(available=True, send_ok=True, channels_ok=False))
    with pytest.raises(HTTPException):
        await web_server.api_slack_channels()

    ok_send = await web_server.api_slack_send(web_server._SlackSendRequest(text="ok"))
    assert ok_send.status_code == 200

    class _JiraMgr:
        def __init__(self, available=True, create_ok=True, search_ok=True):
            self._available = available
            self._create_ok = create_ok
            self._search_ok = search_ok

        def is_available(self):
            return self._available

        async def create_issue(self, **_kwargs):
            return self._create_ok, {"key": "SID-1"}, "jira err"

        async def search_issues(self, **_kwargs):
            return self._search_ok, [{"id": "1"}], "jira err"

    monkeypatch.setattr(web_server, "_get_jira_manager", lambda: _JiraMgr(available=False))
    with pytest.raises(HTTPException):
        await web_server.api_jira_create_issue(web_server._JiraCreateRequest(project_key="SID", summary="s"))
    with pytest.raises(HTTPException):
        await web_server.api_jira_search_issues()

    monkeypatch.setattr(web_server, "_get_jira_manager", lambda: _JiraMgr(available=True, create_ok=False, search_ok=False))
    with pytest.raises(HTTPException):
        await web_server.api_jira_create_issue(web_server._JiraCreateRequest(project_key="SID", summary="s"))
    with pytest.raises(HTTPException):
        await web_server.api_jira_search_issues()

    monkeypatch.setattr(web_server, "_get_jira_manager", lambda: _JiraMgr())
    ok_issue = await web_server.api_jira_create_issue(web_server._JiraCreateRequest(project_key="SID", summary="s"))
    assert ok_issue.status_code == 200
    ok_search = await web_server.api_jira_search_issues()
    assert ok_search.status_code == 200

    class _TeamsMgr:
        def __init__(self, available=True, send_ok=True):
            self._available = available
            self._send_ok = send_ok

        def is_available(self):
            return self._available

        async def send_message(self, **_kwargs):
            return self._send_ok, "teams err"

    monkeypatch.setattr(web_server, "_get_teams_manager", lambda: _TeamsMgr(available=False))
    with pytest.raises(HTTPException):
        await web_server.api_teams_send(web_server._TeamsSendRequest(text="x"))

    monkeypatch.setattr(web_server, "_get_teams_manager", lambda: _TeamsMgr(available=True, send_ok=False))
    with pytest.raises(HTTPException):
        await web_server.api_teams_send(web_server._TeamsSendRequest(text="x"))

    monkeypatch.setattr(web_server, "_get_teams_manager", lambda: _TeamsMgr())
    ok_teams = await web_server.api_teams_send(web_server._TeamsSendRequest(text="x"))
    assert ok_teams.status_code == 200


@pytest.mark.asyncio
async def test_autonomous_cron_loop_dispatches_and_logs_failure(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "AUTONOMOUS_CRON_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(web_server.cfg, "AUTONOMOUS_CRON_PROMPT", "Durum kontrolü yap")

    class _StopAfterFirstTimeout:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls >= 2

        async def wait(self):
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError()
            return True

    async def _wait_for(awaitable, timeout):
        return await awaitable

    calls = {"dispatch": 0, "warn": []}

    async def _dispatch(**_kwargs):
        calls["dispatch"] += 1
        raise RuntimeError("cron boom")

    monkeypatch.setattr(web_server.asyncio, "wait_for", _wait_for)
    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", _dispatch)
    monkeypatch.setattr(web_server.logger, "warning", lambda msg, *args: calls["warn"].append(msg % args if args else msg))

    await web_server._autonomous_cron_loop(_StopAfterFirstTimeout())

    assert calls["dispatch"] == 1
    assert any("tetikleme hatası" in item for item in calls["warn"])


@pytest.mark.asyncio
async def test_nightly_memory_loop_disabled_and_failure_paths(monkeypatch):
    monkeypatch.setattr(web_server.cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)
    logs: list[str] = []
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: logs.append(msg % args if args else msg))
    await web_server._nightly_memory_loop(asyncio.Event())
    assert any("devre dışı" in item for item in logs)

    monkeypatch.setattr(web_server.cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", True)
    monkeypatch.setattr(web_server.cfg, "NIGHTLY_MEMORY_INTERVAL_SECONDS", 1)

    class _StopAfterFirstTimeout:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            return self.calls >= 2

        async def wait(self):
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError()
            return True

    async def _wait_for(awaitable, timeout):
        return await awaitable

    warns: list[str] = []

    class _Agent:
        async def run_nightly_memory_maintenance(self, reason):
            assert reason == "nightly_loop"
            raise RuntimeError("nightly boom")

    monkeypatch.setattr(web_server.asyncio, "wait_for", _wait_for)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: _Agent())
    monkeypatch.setattr(web_server.logger, "warning", lambda msg, *args: warns.append(msg % args if args else msg))

    await web_server._nightly_memory_loop(_StopAfterFirstTimeout())
    assert any("maintenance hatası" in item for item in warns)


def test_get_plugin_marketplace_entry_and_serialization(monkeypatch):
    with pytest.raises(HTTPException):
        web_server._get_plugin_marketplace_entry("unknown")

    fake_spec = SimpleNamespace(
        role_name="aws_management",
        description="desc",
        capabilities=["a"],
        version="9.9.9",
        is_builtin=False,
    )
    monkeypatch.setattr(web_server.AgentRegistry, "get", lambda role: fake_spec if role == "aws_management" else None)

    serialized = web_server._serialize_marketplace_plugin(
        "aws_management",
        installed_state={"installed_at": "now", "last_reloaded_at": "later"},
    )

    assert serialized["plugin_id"] == "aws_management"
    assert serialized["installed"] is True
    assert serialized["live_registered"] is True
    assert serialized["agent"]["version"] == "9.9.9"


def test_verify_hmac_signature_happy_path_and_failures():
    payload = b'{"ok":true}'
    secret = "top-secret"
    expected = "sha256=" + web_server.hmac.new(secret.encode("utf-8"), payload, web_server.hashlib.sha256).hexdigest()

    # no secret => signature checks are bypassed
    web_server._verify_hmac_signature(payload, "", "", label="Webhook")
    web_server._verify_hmac_signature(payload, secret, expected, label="Webhook")

    with pytest.raises(HTTPException) as exc_info:
        web_server._verify_hmac_signature(payload, secret, "", label="Webhook")
    assert exc_info.value.status_code == 401
    assert "imza başlığı" in str(exc_info.value.detail)

    with pytest.raises(HTTPException) as exc_info:
        web_server._verify_hmac_signature(payload, secret, "sha256=deadbeef", label="Webhook")
    assert exc_info.value.status_code == 401
    assert "Geçersiz imza" in str(exc_info.value.detail)


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


@pytest.mark.asyncio
async def test_run_event_driven_federation_workflow_none_when_spec_missing(monkeypatch):
    monkeypatch.setattr(web_server, "_build_event_driven_federation_spec", lambda *_: None)
    result = await web_server._run_event_driven_federation_workflow(source="github", event_name="push", payload={"x": 1})
    assert result is None


@pytest.mark.asyncio
async def test_run_event_driven_federation_workflow_builds_result_payload(monkeypatch):
    monkeypatch.setattr(web_server, "_trim_autonomy_text", lambda value, limit=1200: str(value)[:limit])
    monkeypatch.setattr(web_server, "_build_swarm_goal_for_role", lambda goal, role, _spec: f"{role}:{goal}")
    monkeypatch.setattr(web_server, "derive_correlation_id", lambda *args: "corr-42")

    spec = {
        "workflow_type": "github_pull_request",
        "task_id": "task-42",
        "source_system": "github",
        "source_agent": "pull_request_webhook",
        "goal": "PR'i değerlendir",
        "context": {"repo": "org/repo", "pr_number": "42"},
        "inputs": ["pr_number=42", "title=Fix"],
        "correlation_id": "corr-42",
    }
    monkeypatch.setattr(web_server, "_build_event_driven_federation_spec", lambda *_: spec)

    class _FakeOrchestrator:
        def __init__(self, _cfg):
            pass

        async def run_pipeline(self, tasks, session_id):
            assert session_id == "corr-42"
            assert len(tasks) == 2
            @dataclass
            class _Result:
                task_id: str
                role: str
                status: str
                summary: str

            return [
                _Result(task_id="task-42", role="coder", status="success", summary="Kod planı hazır"),
                _Result(task_id="task-42", role="reviewer", status="success", summary="Review tamam"),
            ]

    monkeypatch.setattr(web_server, "SwarmOrchestrator", _FakeOrchestrator)

    result = await web_server._run_event_driven_federation_workflow(
        source="github",
        event_name="pull_request",
        payload={"action": "opened"},
    )

    assert result is not None
    assert result["workflow_type"] == "github_pull_request"
    assert result["correlation_id"] == "corr-42"
    assert result["federation_task"]["task_id"] == "task-42"
    assert result["federation_result"]["status"] == "success"
    assert len(result["pipeline"]) == 2
    assert "SWARM_PIPELINE_RESULT" in result["federation_prompt"]


def test_setup_tracing_custom_init_and_fallback_paths(monkeypatch):
    calls = {"init": None, "warnings": [], "infos": []}

    original_cfg = web_server.cfg

    def _init_telemetry(**kwargs):
        calls["init"] = kwargs

    cfg_with_custom = SimpleNamespace(init_telemetry=_init_telemetry, OTEL_SERVICE_NAME="sidar-test")
    monkeypatch.setattr(web_server, "cfg", cfg_with_custom)
    web_server._setup_tracing()
    assert calls["init"]["service_name"]

    # Fallback: tracing kapalı
    fallback_cfg = SimpleNamespace(
        ENABLE_TRACING=False,
        OTEL_SERVICE_NAME="sidar-test",
        OTEL_EXPORTER_ENDPOINT="http://otel:4318",
    )
    monkeypatch.setattr(web_server, "cfg", fallback_cfg)
    web_server._setup_tracing()

    # Fallback: tracing açık fakat bağımlılık eksik
    fallback_cfg.ENABLE_TRACING = True
    monkeypatch.setattr(web_server, "trace", None)
    monkeypatch.setattr(web_server.logger, "warning", lambda msg, *args: calls["warnings"].append(msg))
    web_server._setup_tracing()
    assert calls["warnings"]

    # Fallback: full tracing başarıyla kurulur ve info log atılır
    class _Trace:
        @staticmethod
        def set_tracer_provider(provider):
            calls["provider"] = provider

    class _Resource:
        @staticmethod
        def create(payload):
            calls["resource"] = payload
            return "resource"

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, processor):
            calls["processor"] = processor

    class _Exporter:
        def __init__(self, endpoint, insecure):
            calls["exporter"] = (endpoint, insecure)

    class _Batch:
        def __init__(self, exporter):
            calls["batch"] = exporter

    class _FastAPIInstrumentor:
        @staticmethod
        def instrument_app(_app):
            calls["fastapi_instrumented"] = True

    class _HTTPXInstrumentor:
        def instrument(self):
            raise RuntimeError("test suppress")

    monkeypatch.setattr(web_server, "trace", _Trace())
    monkeypatch.setattr(web_server, "Resource", _Resource)
    monkeypatch.setattr(web_server, "TracerProvider", _Provider)
    monkeypatch.setattr(web_server, "OTLPSpanExporter", _Exporter)
    monkeypatch.setattr(web_server, "BatchSpanProcessor", _Batch)
    monkeypatch.setattr(web_server, "FastAPIInstrumentor", _FastAPIInstrumentor)
    monkeypatch.setattr(web_server, "HTTPXClientInstrumentor", _HTTPXInstrumentor)
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: calls["infos"].append(msg))
    web_server._setup_tracing()
    assert calls["fastapi_instrumented"] is True
    assert calls["infos"]
    monkeypatch.setattr(web_server, "cfg", original_cfg)


def test_request_user_admin_and_metrics_guards():
    req = _make_request("/metrics", method="GET")
    req.state.user = SimpleNamespace(id="u1", username="ada", role="admin")
    assert web_server._get_request_user(req).id == "u1"
    assert web_server._is_admin_user(SimpleNamespace(role="admin", username="x")) is True
    assert web_server._is_admin_user(SimpleNamespace(role="user", username="default_admin")) is True
    assert web_server._is_admin_user(SimpleNamespace(role="user", username="ada")) is False

    user = SimpleNamespace(role="user", username="ada")
    with pytest.raises(HTTPException) as exc_info:
        web_server._require_admin_user(user)
    assert exc_info.value.status_code == 403

    req.headers.__dict__["_list"] = [(b"authorization", b"Bearer metrics-secret")]
    web_server.cfg.METRICS_TOKEN = "metrics-secret"
    assert web_server._require_metrics_access(req, user) is user
    admin = SimpleNamespace(role="admin", username="root")
    req_no_token = _make_request("/metrics", method="GET")
    assert web_server._require_metrics_access(req_no_token, admin) is admin
    with pytest.raises(HTTPException):
        web_server._require_metrics_access(req_no_token, user)


def test_policy_resolution_and_audit_resource_builder():
    assert web_server._resolve_policy_from_request(_make_request("/rag/docs", method="GET")) == ("rag", "read", "*")
    assert web_server._resolve_policy_from_request(_make_request("/rag/docs/42", method="DELETE")) == ("rag", "write", "42")
    assert web_server._resolve_policy_from_request(_make_request("/github-repos", method="POST")) == ("github", "write", "*")
    assert web_server._resolve_policy_from_request(_make_request("/api/agents/register", method="POST")) == ("agents", "register", "*")
    assert web_server._resolve_policy_from_request(_make_request("/api/swarm/execute", method="POST")) == ("swarm", "execute", "*")
    assert web_server._resolve_policy_from_request(_make_request("/admin/stats", method="GET")) == ("admin", "manage", "*")
    assert web_server._resolve_policy_from_request(_make_request("/ws/room", method="GET")) == ("swarm", "execute", "*")
    assert web_server._resolve_policy_from_request(_make_request("/unknown", method="GET")) == ("", "", "")
    assert web_server._build_audit_resource("rag", "x") == "rag:x"
    assert web_server._build_audit_resource("", "x") == ""


@pytest.mark.asyncio
async def test_schedule_access_audit_log_success_and_no_loop(monkeypatch):
    recorded = {}

    async def _record_audit_log(**kwargs):
        recorded.update(kwargs)

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_audit_log=_record_audit_log)))

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)

    scheduled = {}

    class _Loop:
        def create_task(self, coro):
            scheduled["task"] = asyncio.create_task(coro)

    monkeypatch.setattr(web_server.asyncio, "get_running_loop", lambda: _Loop())
    web_server._schedule_access_audit_log(
        user=SimpleNamespace(id="u1", tenant_id="t1"),
        resource_type="rag",
        action="read",
        resource_id="doc1",
        ip_address="127.0.0.1",
        allowed=True,
    )
    await scheduled["task"]
    assert recorded["resource"] == "rag:doc1"

    monkeypatch.setattr(web_server.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no-loop")))
    debug_logs = []
    monkeypatch.setattr(web_server.logger, "debug", lambda msg, *args: debug_logs.append(msg))
    web_server._schedule_access_audit_log(
        user=SimpleNamespace(id="u1"),
        resource_type="",
        action="read",
        resource_id="doc1",
        ip_address="127.0.0.1",
        allowed=False,
    )
    web_server._schedule_access_audit_log(
        user=SimpleNamespace(id="u1"),
        resource_type="rag",
        action="read",
        resource_id="doc1",
        ip_address="127.0.0.1",
        allowed=False,
    )
    assert debug_logs


def test_serialize_marketing_records():
    campaign = SimpleNamespace(id=1, tenant_id="t1", name="Launch", channel="email", objective="signup", status="draft", owner_user_id="u1", budget=99.5, metadata_json="{}", created_at="c", updated_at="u")
    asset = SimpleNamespace(id=2, campaign_id=1, tenant_id="t1", asset_type="post", title="Hello", content="World", channel="x", metadata_json="{}", created_at="c", updated_at="u")
    checklist = SimpleNamespace(id=3, campaign_id=None, tenant_id="t1", title="Ops", items_json="[]", status="pending", owner_user_id="u2", created_at="c", updated_at="u")

    assert web_server._serialize_campaign(campaign)["name"] == "Launch"
    assert web_server._serialize_content_asset(asset)["campaign_id"] == 1
    assert web_server._serialize_operation_checklist(checklist)["campaign_id"] is None


def test_load_plugin_agent_class_branches():
    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("not valid py(", None, "bad_mod")

    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("class X: pass", "Missing", "mod")

    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("class X: pass", "X", "mod")

    source = "from agent.base_agent import BaseAgent\nclass MyAgent(BaseAgent):\n    ROLE_NAME='my'\n    async def respond(self, prompt):\n        yield prompt\n"
    cls = web_server._load_plugin_agent_class(source, "MyAgent", "mod")
    assert cls.__name__ == "MyAgent"

    discovered = web_server._load_plugin_agent_class(source, None, "mod2")
    assert discovered.__name__ == "MyAgent"

    with pytest.raises(HTTPException):
        web_server._load_plugin_agent_class("x = 1", None, "mod3")


def test_persist_and_import_plugin_file_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    imported = web_server._persist_and_import_plugin_file("demo", b"x=1\n", "plugin_demo")
    assert imported.name == "demo.py"
    assert imported.exists()

    monkeypatch.setattr(web_server.importlib.util, "spec_from_file_location", lambda *_: None)
    with pytest.raises(HTTPException):
        web_server._persist_and_import_plugin_file("demo2.py", b"x=1\n", "plugin_bad")

    class _Loader:
        def exec_module(self, module):
            raise RuntimeError("boom")

    class _Spec:
        loader = _Loader()

    monkeypatch.setattr(web_server.importlib.util, "spec_from_file_location", lambda *_: _Spec())
    monkeypatch.setattr(web_server.importlib.util, "module_from_spec", lambda _spec: object())
    with pytest.raises(HTTPException):
        web_server._persist_and_import_plugin_file("demo3.py", b"x=1\n", "plugin_boom")


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


def test_contracts_import_fallback_defines_dataclasses(monkeypatch):
    mod = _load_web_server_with_import_failures(
        monkeypatch,
        module_name="web_server_contracts_fallback_case",
        fail_rules=set(),
    )

    import builtins
    import importlib.util
    import sys

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agent.core.contracts":
            raise ImportError("forced contracts failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    spec = importlib.util.spec_from_file_location("web_server_contracts_fallback_forced", Path("web_server.py"))
    forced = importlib.util.module_from_spec(spec)
    sys.modules["web_server_contracts_fallback_forced"] = forced
    assert spec and spec.loader
    spec.loader.exec_module(forced)

    trigger = forced.ExternalTrigger(trigger_id="t1", source="github", event_name="opened", payload={"x": 1})
    feedback = forced.ActionFeedback(
        feedback_id="f1",
        source_system="github",
        source_agent="agent",
        action_name="fix",
        status="ok",
        summary="done",
    )
    assert trigger.protocol == "trigger.v1"
    assert feedback.protocol == "action_feedback.v1"
    assert forced.normalize_federation_protocol(forced.LEGACY_FEDERATION_PROTOCOL_V1) == "federation.v1"
    assert forced.derive_correlation_id("", None, "corr-1") == "corr-1"
    assert isinstance(mod.LEGACY_FEDERATION_PROTOCOL_V1, str)


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


class _ChatWebSocket:
    def __init__(self, messages: list[str], headers: dict[str, str] | None = None):
        self._messages = list(messages)
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.sent: list[dict] = []
        self.accepted: list[str | None] = []

    async def accept(self, subprotocol=None):
        self.accepted.append(subprotocol)

    async def receive_text(self):
        if not self._messages:
            raise web_server.WebSocketDisconnect()
        return self._messages.pop(0)

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_websocket_chat_requires_auth_before_non_auth_actions(monkeypatch):
    ws = _ChatWebSocket([web_server.json.dumps({"action": "noop"})])
    closed = {}

    async def _close(_websocket, reason):
        closed["reason"] = reason

    monkeypatch.setattr(web_server, "_ws_close_policy_violation", _close)
    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace())

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)

    await web_server.websocket_chat(ws)

    assert ws.accepted == [None]
    assert closed["reason"] == "Authentication required"


@pytest.mark.asyncio
async def test_websocket_chat_rate_limit_and_room_mention_validation(monkeypatch):
    user = SimpleNamespace(id="u1", username="ada", role="developer")
    ws = _ChatWebSocket(
        [
            web_server.json.dumps({"action": "join_room", "room_id": "team:sync", "display_name": "Ada"}),
            web_server.json.dumps({"action": "message", "message": "@sidar   "}),
            web_server.json.dumps({"action": "message", "message": "hello"}),
        ],
        headers={"sec-websocket-protocol": "token-1"},
    )

    participant = web_server._CollaborationParticipant(
        ws,
        "u1",
        "ada",
        "Ada",
        role="developer",
        can_write=True,
        write_scopes=["/tmp/workspaces/team/sync"],
    )
    room = web_server._CollaborationRoom(room_id="team:sync", participants={web_server._socket_key(ws): participant})
    broadcast_events: list[dict] = []

    async def _join(*_args, **_kwargs):
        web_server._collaboration_rooms["team:sync"] = room
        setattr(ws, "_sidar_room_id", "team:sync")
        return room

    async def _broadcast(_room, payload):
        broadcast_events.append(payload)

    async def _resolve_user(*_args, **_kwargs):
        return user

    async def _set_active_user(*_args, **_kwargs):
        return None

    agent = SimpleNamespace(
        memory=SimpleNamespace(set_active_user=_set_active_user),
    )
    async def _resolve_agent():
        return agent

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    rate_calls = {"n": 0}

    async def _rate_limited(*_args, **_kwargs):
        rate_calls["n"] += 1
        return rate_calls["n"] >= 2

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_join_collaboration_room", _join)
    monkeypatch.setattr(web_server, "_broadcast_room_payload", _broadcast)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _rate_limited)

    await web_server.websocket_chat(ws)

    assert ws.accepted == ["token-1"]
    assert any(event.get("type") == "room_error" for event in broadcast_events)
    assert any("Hız Sınırı" in payload.get("chunk", "") for payload in ws.sent)

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


def test_mask_collaboration_text_success_and_import_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "core.dlp", SimpleNamespace(mask_pii=lambda value: f"masked:{value}"))
    assert web_server._mask_collaboration_text("abc") == "masked:abc"

    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.dlp":
            raise ImportError("blocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "core.dlp", raising=False)
    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert web_server._mask_collaboration_text("abc") == "abc"


def test_list_child_ollama_pids_windows_and_psutil_failure(monkeypatch):
    class _Psutil:
        class Process:
            def __init__(self, _pid):
                raise RuntimeError("psutil broken")

    monkeypatch.setitem(sys.modules, "psutil", _Psutil)
    monkeypatch.setattr(web_server, "os", SimpleNamespace(name="nt", getpid=lambda: 1))

    assert web_server._list_child_ollama_pids() == []


def test_list_child_ollama_pids_psutil_success_path(monkeypatch):
    class _Child:
        def __init__(self, pid, comm, args):
            self.pid = pid
            self._comm = comm
            self._args = args

        def name(self):
            return self._comm

        def cmdline(self):
            return self._args

    class _Process:
        def __init__(self, _pid):
            pass

        def children(self, recursive=False):
            assert recursive is False
            return [
                _Child(11, "ollama", ["ollama", "serve"]),
                _Child(12, "python", ["python", "app.py"]),
                _Child(13, "bash", ["bash", "-lc", "ollama serve"]),
            ]

    class _Psutil:
        Process = _Process

    monkeypatch.setitem(sys.modules, "psutil", _Psutil)
    monkeypatch.setattr(web_server, "os", SimpleNamespace(name="posix", getpid=lambda: 999))
    assert web_server._list_child_ollama_pids() == [11, 13]


def test_reap_child_processes_nonblocking_handles_generic_exception(monkeypatch):
    monkeypatch.setattr(web_server.os, "waitpid", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert web_server._reap_child_processes_nonblocking() == 0


def test_list_child_ollama_pids_ps_fallback_handles_malformed_and_failures(monkeypatch):
    monkeypatch.setattr(web_server, "os", SimpleNamespace(name="posix", getpid=lambda: 77))
    original_import = __import__

    class _Psutil:
        class Process:
            def __init__(self, _pid):
                raise RuntimeError("psutil broken")

    def _fake_import(name, *args, **kwargs):
        if name == "psutil":
            return _Psutil
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    monkeypatch.setattr(
        web_server,
        "subprocess",
        SimpleNamespace(
            DEVNULL=object(),
            check_output=lambda *args, **kwargs: (
                b"broken-line-without-columns\n"
                b" abc 77 ollama ollama serve\n"
                b" 13 xyz ollama ollama serve\n"
                b" 15 77 ollama ollama serve\n"
            ),
        ),
    )

    assert web_server._list_child_ollama_pids() == [15]

    monkeypatch.setattr(
        web_server,
        "subprocess",
        SimpleNamespace(
            DEVNULL=object(),
            check_output=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ps failed")),
        ),
    )
    assert web_server._list_child_ollama_pids() == []


@pytest.mark.asyncio
async def test_leave_collaboration_room_broadcasts_when_room_survives(monkeypatch):
    ws_departing = _DummyWebSocket()
    ws_staying = _DummyWebSocket()
    setattr(ws_departing, "_sidar_room_id", "team:survive")
    setattr(ws_staying, "_sidar_room_id", "team:survive")

    room = web_server._CollaborationRoom(
        room_id="team:survive",
        participants={
            web_server._socket_key(ws_departing): web_server._CollaborationParticipant(ws_departing, "u1", "a", "A"),
            web_server._socket_key(ws_staying): web_server._CollaborationParticipant(ws_staying, "u2", "b", "B"),
        },
    )
    web_server._collaboration_rooms["team:survive"] = room

    await web_server._leave_collaboration_room(ws_departing)

    assert "team:survive" in web_server._collaboration_rooms
    assert web_server._socket_key(ws_departing) not in room.participants
    assert ws_staying.messages
    assert ws_staying.messages[-1]["type"] == "presence"


def test_terminate_ollama_child_pids_sends_term_and_kill(monkeypatch):
    calls = []

    def _kill(pid, sig):
        calls.append((pid, sig))

    monkeypatch.setattr(web_server.os, "kill", _kill)
    monkeypatch.setattr(web_server.time, "sleep", lambda _s: calls.append(("sleep", _s)))

    web_server._terminate_ollama_child_pids([7, 8], grace_seconds=0.01)

    assert calls[0] == (7, web_server.signal.SIGTERM)
    assert calls[1] == (8, web_server.signal.SIGTERM)
    assert calls[2] == ("sleep", 0.01)
    assert calls[3] == (7, web_server.signal.SIGKILL)
    assert calls[4] == (8, web_server.signal.SIGKILL)


def test_terminate_ollama_child_pids_without_grace_skips_sleep_and_kill(monkeypatch):
    calls = []
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(web_server.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    web_server._terminate_ollama_child_pids([99], grace_seconds=0)
    web_server._terminate_ollama_child_pids([], grace_seconds=0.2)

    assert calls == [(99, web_server.signal.SIGTERM)]


def test_force_shutdown_local_llm_processes_non_ollama_and_without_force_kill(monkeypatch):
    reaped = {"count": 0}
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("count", reaped["count"] + 1) or 0)

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    web_server._force_shutdown_local_llm_processes()
    assert reaped["count"] == 1

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    web_server._force_shutdown_local_llm_processes()
    assert reaped["count"] == 2


def test_force_shutdown_local_llm_processes_logs_when_reap_or_pids_present(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [])
    monkeypatch.setattr(web_server, "_terminate_ollama_child_pids", lambda _pids: None)
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 2)
    infos = []
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: infos.append(msg % args))

    web_server._force_shutdown_local_llm_processes()

    assert any("shutdown cleanup" in msg for msg in infos)


@pytest.mark.asyncio
async def test_async_force_shutdown_handles_idempotent_and_no_force_paths(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", True)
    reaped = {"count": 0}
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("count", reaped["count"] + 1))
    await web_server._async_force_shutdown_local_llm_processes()
    assert reaped["count"] == 0

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    await web_server._async_force_shutdown_local_llm_processes()
    assert reaped["count"] == 1


def test_bind_llm_usage_sink_handles_missing_setter_and_runtime_error(monkeypatch):
    class _Collector:
        _sidar_usage_sink_bound = False

    collector = _Collector()
    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: collector)

    agent = SimpleNamespace(memory=SimpleNamespace(db=SimpleNamespace(record_provider_usage_daily=lambda **_: None)))
    web_server._bind_llm_usage_sink(agent)

    assert collector._sidar_usage_sink_bound is True

    sink_holder = {}

    class _CollectorWithSetter:
        _sidar_usage_sink_bound = False

        def set_usage_sink(self, sink):
            sink_holder["sink"] = sink

    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: _CollectorWithSetter())
    web_server._bind_llm_usage_sink(agent)
    sink = sink_holder["sink"]

    sink(SimpleNamespace(user_id="", provider="x", total_tokens=1))
    monkeypatch.setattr(web_server.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    sink(SimpleNamespace(user_id="u-1", provider="x", total_tokens=1))


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_handles_sentinels_and_voice_packets():
    class _Ws:
        def __init__(self):
            self.payloads = []
            self._sidar_voice_duplex_state = object()

        async def send_json(self, payload):
            self.payloads.append(payload)

    class _VoicePipeline:
        enabled = True

        def __init__(self):
            self.calls = []

        def buffer_assistant_text(self, _state, text, flush=False):
            self.calls.append((text, flush))
            packets = []
            normalized = text.strip()
            if normalized:
                packets.append({"assistant_turn_id": 11, "audio_sequence": 1, "text": normalized})
            return "turn-1", packets

        async def synthesize_text(self, text):
            return {
                "success": True,
                "audio_bytes": text.encode("utf-8"),
                "mime_type": "audio/wav",
                "provider": "fake-tts",
                "voice": "standard",
            }

    class _Agent:
        async def respond(self, _prompt):
            for chunk in ["\x00TOOL:search\x00", "\x00THOUGHT:thinking\x00", "Merhaba"]:
                yield chunk

    ws = _Ws()
    ws._sidar_voice_pipeline = _VoicePipeline()
    await web_server._ws_stream_agent_text_response(ws, _Agent(), "prompt")

    assert {"tool_call": "search"} in ws.payloads
    assert {"thought": "thinking"} in ws.payloads
    assert {"chunk": "Merhaba"} in ws.payloads
    assert any("audio_chunk" in payload and payload["audio_text"] == "Merhaba" for payload in ws.payloads)


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_extract_ready_segments_fallback():
    class _Ws:
        def __init__(self):
            self.payloads = []

        async def send_json(self, payload):
            self.payloads.append(payload)

    class _VoicePipeline:
        enabled = True

        def extract_ready_segments(self, text, flush=False):
            if flush:
                return ([text.strip()] if text.strip() else []), ""
            return [], text

        async def synthesize_text(self, text):
            return {"success": True, "audio_bytes": text.encode(), "mime_type": "audio/wav"}

    class _Agent:
        async def respond(self, _prompt):
            for chunk in ["Parça ", "metin"]:
                yield chunk

    ws = _Ws()
    ws._sidar_voice_pipeline = _VoicePipeline()
    await web_server._ws_stream_agent_text_response(ws, _Agent(), "prompt")

    assert ws.payloads[0] == {"chunk": "Parça "}
    assert ws.payloads[1] == {"chunk": "metin"}
    assert any(payload.get("audio_text") == "Parça metin" for payload in ws.payloads)


@pytest.mark.asyncio
async def test_websocket_chat_requires_auth_before_processing(monkeypatch):
    class _Ws:
        def __init__(self):
            self.headers = {}
            self.client = SimpleNamespace(host="127.0.0.1")
            self.accepted = False
            self.closed = None
            self.messages = iter(["not-json", '{"action":"message","message":"selam"}'])

        async def accept(self, subprotocol=None):
            self.accepted = True
            self.subprotocol = subprotocol

        async def receive_text(self):
            return next(self.messages)

        async def send_json(self, _payload):
            return None

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    async def _resolve_none(*_):
        return None

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_none)

    ws = _Ws()
    await web_server.websocket_chat(ws)

    assert ws.accepted is True
    assert ws.closed == {"code": 1008, "reason": "Authentication required"}


@pytest.mark.asyncio
async def test_github_webhook_signature_and_event_variants(monkeypatch):
    class _Req:
        def __init__(self, payload: bytes):
            self._payload = payload

        async def body(self):
            return self._payload

    class _Memory:
        def __init__(self):
            self.messages = []

        async def add(self, role, content):
            self.messages.append((role, content))

    agent = SimpleNamespace(memory=_Memory())
    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: agent)
    monkeypatch.setattr(web_server, "_resolve_ci_failure_context", lambda *_: {})
    monkeypatch.setattr(web_server, "_await_if_needed", lambda value: value)
    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", lambda **_: {"ok": True})
    monkeypatch.setattr(web_server, "_run_event_driven_federation_workflow", lambda **_: None)

    monkeypatch.setattr(web_server.cfg, "GITHUB_WEBHOOK_SECRET", "sekret")
    with pytest.raises(HTTPException):
        await web_server.github_webhook(_Req(b"{}"), x_github_event="push", x_hub_signature_256="")

    with pytest.raises(HTTPException):
        await web_server.github_webhook(
            _Req(b"{}"),
            x_github_event="push",
            x_hub_signature_256="sha256=invalid",
        )

    good_sig = "sha256=" + __import__("hmac").new(b"sekret", b"{}", __import__("hashlib").sha256).hexdigest()
    push_res = await web_server.github_webhook(_Req(b"{}"), x_github_event="push", x_hub_signature_256=good_sig)
    assert push_res.status_code == 200

    payload = b'{"action":"opened","issue":{"title":"Bug","number":3}}'
    issue_sig = "sha256=" + __import__("hmac").new(b"sekret", payload, __import__("hashlib").sha256).hexdigest()
    issues_res = await web_server.github_webhook(_Req(payload), x_github_event="issues", x_hub_signature_256=issue_sig)
    assert issues_res.status_code == 200
    assert any("Issue #3" in content for role, content in agent.memory.messages if role == "user")


@pytest.mark.asyncio
async def test_spa_fallback_rejects_static_like_paths_and_index_passthrough(monkeypatch):
    api_like = await web_server.spa_fallback("api/metrics")
    static_like = await web_server.spa_fallback("assets/app.js")
    assert api_like.status_code == 404
    assert static_like.status_code == 404

    monkeypatch.setattr(web_server, "index", lambda: web_server.HTMLResponse("<h1>ok</h1>", status_code=200))
    ok = await web_server.spa_fallback("dashboard/home")
    assert ok.status_code == 200
    assert b"<h1>ok</h1>" in ok.body


@pytest.mark.asyncio
async def test_spa_fallback_handles_empty_path_async_index_and_extension_guard(monkeypatch):
    async def _async_index():
        return web_server.HTMLResponse("<h1>async</h1>", status_code=200)

    monkeypatch.setattr(web_server, "index", _async_index)
    empty = await web_server.spa_fallback("   ")
    assert empty.status_code == 200
    assert b"async" in empty.body

    dotted = await web_server.spa_fallback("nested/app.css")
    assert dotted.status_code == 404


@pytest.mark.asyncio
async def test_github_webhook_ci_context_and_webhook_toggle(monkeypatch):
    class _Req:
        async def body(self):
            return b'{"workflow_run":{"id":10}}'

    class _Memory:
        def __init__(self):
            self.messages = []

        async def add(self, role, content):
            self.messages.append((role, content))

    dispatch_calls = []
    workflow_calls = []
    agent = SimpleNamespace(memory=_Memory())

    monkeypatch.setattr(web_server, "_resolve_agent_instance", lambda: agent)
    monkeypatch.setattr(
        web_server,
        "_resolve_ci_failure_context",
        lambda *_: {"workflow_name": "CI", "run_id": 10, "conclusion": "failure"},
    )
    monkeypatch.setattr(web_server, "_await_if_needed", lambda value: value)
    monkeypatch.setattr(web_server, "_dispatch_autonomy_trigger", lambda **kwargs: dispatch_calls.append(kwargs) or {"ok": True})
    monkeypatch.setattr(
        web_server,
        "_run_event_driven_federation_workflow",
        lambda **kwargs: workflow_calls.append(kwargs) or {"workflow_type": "external_event", "correlation_id": "cid-1"},
    )
    monkeypatch.setattr(web_server.cfg, "GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setattr(web_server.cfg, "ENABLE_EVENT_WEBHOOKS", True)

    response = await web_server.github_webhook(_Req(), x_github_event="issues", x_hub_signature_256="")
    assert response.status_code == 200
    assert dispatch_calls[-1]["trigger_source"] == "webhook:github:ci_failure"
    assert workflow_calls == []  # ci_context varken federation workflow çağrılmaz.
    assert any("[GITHUB CI]" in content for role, content in agent.memory.messages if role == "user")

    monkeypatch.setattr(web_server.cfg, "ENABLE_EVENT_WEBHOOKS", False)
    dispatch_calls.clear()
    response_disabled = await web_server.github_webhook(_Req(), x_github_event="issues", x_hub_signature_256="")
    assert response_disabled.status_code == 200
    assert dispatch_calls == []


@pytest.mark.asyncio
async def test_auth_endpoints_cover_success_and_validation_errors(monkeypatch):
    class _DB:
        async def register_user(self, username, password, tenant_id):
            if username == "taken":
                raise RuntimeError("exists")
            return SimpleNamespace(id="u1", username=username, role="user", tenant_id=tenant_id)

        async def authenticate_user(self, username, password):
            if username == "db-error":
                raise RuntimeError("db down")
            if password == "ok":
                return SimpleNamespace(id="u2", username=username, role="admin", tenant_id="t1")
            return None

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))
    async def _resolve_agent():
        return agent

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    async def _issue_token(*_):
        return "jwt-token"

    monkeypatch.setattr(web_server, "_issue_auth_token", _issue_token)

    with pytest.raises(ValidationError):
        web_server._RegisterRequest(username="ab", password="123456", tenant_id="")

    register_res = await web_server.register_user(
        web_server._RegisterRequest(username="ada", password="123456", tenant_id="team")
    )
    assert register_res.status_code == 200
    assert b'"access_token":"jwt-token"' in register_res.body

    with pytest.raises(HTTPException):
        await web_server.register_user(web_server._RegisterRequest(username="taken", password="123456", tenant_id="t1"))

    with pytest.raises(HTTPException):
        await web_server.login_user(web_server._LoginRequest(username="lin", password="bad"))

    login_ok = await web_server.login_user(web_server._LoginRequest(username="lin", password="ok"))
    assert login_ok.status_code == 200

    with pytest.raises(HTTPException):
        await web_server.login_user(web_server._LoginRequest(username="db-error", password="ok"))

    me = await web_server.auth_me(_make_request("/auth/me"), user=SimpleNamespace(id="u", username="ada", role="admin"))
    assert me.status_code == 200
    assert b'"username":"ada"' in me.body


@pytest.mark.asyncio
async def test_admin_prompt_and_policy_endpoints(monkeypatch):
    class _DB:
        async def list_prompts(self, role_name=None):
            return [
                SimpleNamespace(
                    id="1",
                    role_name=role_name or "system",
                    prompt_text="p",
                    version="1",
                    is_active=1,
                    created_at="ts1",
                    updated_at="ts2",
                )
            ]

        async def get_active_prompt(self, role_name):
            return None if role_name == "none" else SimpleNamespace(
                id="2", role_name=role_name, prompt_text="live", version="2", is_active=1, created_at="ts1", updated_at="ts2"
            )

        async def upsert_prompt(self, role_name, prompt_text, activate):
            return SimpleNamespace(
                id="3",
                role_name=role_name,
                prompt_text=prompt_text,
                version="3",
                is_active=1 if activate else 0,
                created_at="ts1",
                updated_at="ts2",
            )

        async def activate_prompt(self, prompt_id):
            return None if prompt_id == 0 else SimpleNamespace(
                id=str(prompt_id), role_name="system", prompt_text="new", version="4", is_active=1, created_at="ts1", updated_at="ts2"
            )

        async def list_access_policies(self, **_):
            return [SimpleNamespace(user_id="u1", tenant_id="t1", resource_type="rag", resource_id="*", action="read", effect="allow")]

        async def upsert_access_policy(self, **_):
            return None

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()), system_prompt="old")
    async def _resolve_agent():
        return agent

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)

    prompts = await web_server.admin_list_prompts(role_name="reviewer", _user=SimpleNamespace(role="admin"))
    assert prompts.status_code == 200

    with pytest.raises(HTTPException):
        await web_server.admin_active_prompt(role_name="none", _user=SimpleNamespace(role="admin"))

    active = await web_server.admin_active_prompt(role_name="system", _user=SimpleNamespace(role="admin"))
    assert active.status_code == 200

    with pytest.raises(ValidationError):
        web_server._PromptUpsertRequest(role_name="", prompt_text="", activate=True)

    upsert = await web_server.admin_upsert_prompt(
        web_server._PromptUpsertRequest(role_name="system", prompt_text="fresh", activate=True),
        _user=SimpleNamespace(role="admin"),
    )
    assert upsert.status_code == 200
    assert agent.system_prompt == "fresh"

    with pytest.raises(ValidationError):
        web_server._PromptActivateRequest(prompt_id=0)

    activated = await web_server.admin_activate_prompt(
        web_server._PromptActivateRequest(prompt_id=9), _user=SimpleNamespace(role="admin")
    )
    assert activated.status_code == 200

    policies = await web_server.admin_list_policies("u1", tenant_id="t1", _user=SimpleNamespace(role="admin"))
    assert policies.status_code == 200
    policy_upsert = await web_server.admin_upsert_policy(
        web_server._PolicyUpsertRequest(
            user_id="u1", tenant_id="t1", resource_type="rag", resource_id="*", action="read", effect="allow"
        ),
        _user=SimpleNamespace(role="admin"),
    )
    assert policy_upsert.status_code == 200


def test_main_bootstrap_paths_with_and_without_agent_init(monkeypatch):
    class _Args:
        host = "0.0.0.0"
        port = 9191
        level = "sandbox"
        provider = "openai"
        log = "INFO"

    class _Parser:
        def add_argument(self, *_, **__):
            return None

        def parse_known_args(self):
            return _Args(), []

    run_calls = []
    monkeypatch.setattr(web_server.argparse, "ArgumentParser", lambda **_: _Parser())
    monkeypatch.setattr(
        web_server,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: run_calls.append((args, kwargs))),
    )
    monkeypatch.setattr(web_server, "print", lambda *_, **__: None)
    def _run_and_finalize(coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        return None

    monkeypatch.setattr(web_server, "asyncio", SimpleNamespace(run=_run_and_finalize))

    class _AgentOK:
        VERSION = "9.9.9"

        async def initialize(self):
            return None

    monkeypatch.setattr(web_server, "SidarAgent", lambda _cfg: _AgentOK())
    web_server.main()
    assert run_calls[-1][1]["host"] == "0.0.0.0"
    assert run_calls[-1][1]["port"] == 9191
    assert run_calls[-1][1]["log_level"] == "info"
    assert web_server.cfg.ACCESS_LEVEL == "sandbox"
    assert web_server.cfg.AI_PROVIDER == "openai"

    monkeypatch.setattr(web_server, "SidarAgent", lambda _cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    web_server.main()
    assert run_calls[-1][1]["port"] == 9191

    class _AgentSync:
        VERSION = "1.2.3"

        def initialize(self):
            return None

    monkeypatch.setattr(web_server, "SidarAgent", lambda _cfg: _AgentSync())
    web_server.main()
    assert run_calls[-1][1]["host"] == "0.0.0.0"


def test_main_skips_config_override_when_optional_args_missing(monkeypatch):
    original_level = web_server.cfg.ACCESS_LEVEL
    original_provider = web_server.cfg.AI_PROVIDER

    class _Args:
        host = "127.0.0.1"
        port = 9192
        level = None
        provider = None
        log = "warning"

    class _Parser:
        def add_argument(self, *_, **__):
            return None

        def parse_known_args(self):
            return _Args(), []

    run_calls = []
    monkeypatch.setattr(web_server.argparse, "ArgumentParser", lambda **_: _Parser())
    monkeypatch.setattr(
        web_server,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: run_calls.append((args, kwargs))),
    )
    monkeypatch.setattr(web_server, "print", lambda *_, **__: None)
    monkeypatch.setattr(web_server, "SidarAgent", lambda _cfg: SimpleNamespace(VERSION="1.0.0", initialize=lambda: None))

    web_server.main()

    assert run_calls[-1][1]["host"] == "127.0.0.1"
    assert run_calls[-1][1]["port"] == 9192
    assert run_calls[-1][1]["log_level"] == "warning"
    assert web_server.cfg.ACCESS_LEVEL == original_level
    assert web_server.cfg.AI_PROVIDER == original_provider


@pytest.mark.asyncio
async def test_favicon_vendor_and_index_paths(tmp_path, monkeypatch):
    web_server.WEB_DIR = tmp_path

    favicon_res = await web_server.favicon()
    assert favicon_res.status_code == 204

    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "bundle.js").write_text("console.log('ok')", encoding="utf-8")

    vendor_ok = await web_server.serve_vendor("bundle.js")
    assert vendor_ok.status_code == 200

    vendor_missing = await web_server.serve_vendor("missing.js")
    assert vendor_missing.status_code == 404

    vendor_forbidden = await web_server.serve_vendor("../secret.txt")
    assert vendor_forbidden.status_code == 403

    monkeypatch.setattr(web_server.cfg, "GRAFANA_URL", "http://grafana.local")
    index_missing = await web_server.index()
    assert index_missing.status_code == 500

    (tmp_path / "index.html").write_text("<html><head></head><body>ok</body></html>", encoding="utf-8")
    index_ok = await web_server.index()
    assert index_ok.status_code == 200
    assert "grafana.local" in index_ok.body.decode("utf-8")


@pytest.mark.asyncio
async def test_ws_close_policy_violation_and_close_redis_client(monkeypatch):
    class _Ws:
        def __init__(self):
            self.calls = []

        async def close(self, code, reason):
            self.calls.append((code, reason))

    ws = _Ws()
    await web_server._ws_close_policy_violation(ws, "policy")
    assert ws.calls == [(1008, "policy")]

    class _Redis:
        def __init__(self, runtime_error=False):
            self.runtime_error = runtime_error
            self.closed = False

        async def aclose(self):
            if self.runtime_error:
                raise RuntimeError("Event loop is closed")
            self.closed = True

    redis_ok = _Redis(runtime_error=False)
    monkeypatch.setattr(web_server, "_redis_client", redis_ok)
    await web_server._close_redis_client()
    assert web_server._redis_client is None
    assert redis_ok.closed is True

    redis_closed_loop = _Redis(runtime_error=True)
    monkeypatch.setattr(web_server, "_redis_client", redis_closed_loop)
    await web_server._close_redis_client()
    assert web_server._redis_client is None

@pytest.mark.asyncio
async def test_get_redis_initialization_success_and_failure_paths(monkeypatch):
    class _RedisClient:
        def __init__(self, should_fail=False):
            self.should_fail = should_fail
            self.ping_called = False

        async def ping(self):
            self.ping_called = True
            if self.should_fail:
                raise RuntimeError("redis-down")

    holder = {"client": None}

    class _RedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            holder["client"] = _RedisClient(should_fail=False)
            return holder["client"]

    monkeypatch.setattr(web_server, "Redis", _RedisFactory)
    monkeypatch.setattr(web_server, "_redis_client", None)
    monkeypatch.setattr(web_server, "_redis_lock", None)

    first = await web_server._get_redis()
    second = await web_server._get_redis()

    assert first is holder["client"]
    assert second is first
    assert first.ping_called is True

    class _RedisFactoryFail:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return _RedisClient(should_fail=True)

    monkeypatch.setattr(web_server, "Redis", _RedisFactoryFail)
    monkeypatch.setattr(web_server, "_redis_client", None)
    monkeypatch.setattr(web_server, "_redis_lock", None)

    failed = await web_server._get_redis()
    assert failed is None


@pytest.mark.asyncio
async def test_redis_rate_limit_first_request_sets_expire_and_get_client_ip_real_ip(monkeypatch):
    calls = {"expire": []}

    class _RedisStub:
        async def incr(self, *_):
            return 1

        async def expire(self, key, ttl):
            calls["expire"].append((key, ttl))
            return True

    async def _get_redis():
        return _RedisStub()

    monkeypatch.setattr(web_server, "_get_redis", _get_redis)
    assert await web_server._redis_is_rate_limited("chat", "2.2.2.2", 5, 60) is False
    assert calls["expire"]

    monkeypatch.setattr(web_server.Config, "TRUSTED_PROXIES", {"127.0.0.1"})
    req_real = _make_request("/x", headers={"X-Real-IP": "8.8.8.8"}, client_ip="127.0.0.1")
    assert web_server._get_client_ip(req_real) == "8.8.8.8"

    req_untrusted = _make_request("/x", headers={"X-Forwarded-For": "9.9.9.9"}, client_ip="10.0.0.7")
    assert web_server._get_client_ip(req_untrusted) == "10.0.0.7"


@pytest.mark.asyncio
async def test_ws_helpers_cover_no_close_and_voice_tts_skip_branches():
    class _NoClose:
        pass

    await web_server._ws_close_policy_violation(_NoClose(), "no-op")

    class _Ws:
        def __init__(self):
            self.payloads = []
            self._sidar_voice_duplex_state = object()

        async def send_json(self, payload):
            self.payloads.append(payload)

    class _VoicePipeline:
        enabled = True

        def buffer_assistant_text(self, _state, text, flush=False):
            cleaned = text.strip()
            if not cleaned:
                return "turn", [{"assistant_turn_id": 1, "audio_sequence": 1, "text": ""}]
            return "turn", [
                {"assistant_turn_id": 1, "audio_sequence": 1, "text": "fail-tts"},
                {"assistant_turn_id": 1, "audio_sequence": 2, "text": "empty-audio"},
                {"assistant_turn_id": 1, "audio_sequence": 3, "text": "ok"},
            ]

        async def synthesize_text(self, text):
            if text == "fail-tts":
                return {"success": False}
            if text == "empty-audio":
                return {"success": True, "audio_bytes": b""}
            return {"success": True, "audio_bytes": b"ok", "mime_type": "audio/wav"}

    class _Agent:
        async def respond(self, _prompt):
            for chunk in [" ", "done"]:
                yield chunk

    ws = _Ws()
    ws._sidar_voice_pipeline = _VoicePipeline()
    await web_server._ws_stream_agent_text_response(ws, _Agent(), "prompt")

    assert {"chunk": " "} in ws.payloads
    assert {"chunk": "done"} in ws.payloads
    assert sum(1 for payload in ws.payloads if "audio_chunk" in payload) == 1


@pytest.mark.asyncio
async def test_websocket_chat_rejects_invalid_header_token(monkeypatch):
    class _Ws:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "bad-token"}
            self.client = SimpleNamespace(host="127.0.0.1")
            self.accepted = None
            self.closed = None

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    async def _resolve_none(*_):
        return None

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_none)

    ws = _Ws()
    await web_server.websocket_chat(ws)
    assert ws.accepted == "bad-token"
    assert ws.closed == {"code": 1008, "reason": "Invalid or expired token"}


@pytest.mark.asyncio
async def test_websocket_chat_auth_message_requires_token(monkeypatch):
    class _Ws:
        def __init__(self):
            self.headers = {}
            self.client = SimpleNamespace(host="127.0.0.1")
            self.closed = None
            self.messages = iter(['{"action":"auth","token":"   "}'])

        async def accept(self, subprotocol=None):
            return None

        async def receive_text(self):
            return next(self.messages)

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    ws = _Ws()
    await web_server.websocket_chat(ws)
    assert ws.closed == {"code": 1008, "reason": "Authentication token missing"}


@pytest.mark.asyncio
async def test_websocket_chat_header_auth_and_message_flow(monkeypatch):
    class _EventBus:
        def subscribe(self):
            q = asyncio.Queue()
            return "sub-1", q

        def unsubscribe(self, _sub_id):
            return None

    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _prompt):
            yield "Merhaba"

    class _Ws:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "good-token"}
            self.client = SimpleNamespace(host="127.0.0.1")
            self.payloads = []
            self.messages = iter(['{"action":"message","message":"selam"}'])

        async def accept(self, subprotocol=None):
            self.subprotocol = subprotocol

        async def receive_text(self):
            try:
                return next(self.messages)
            except StopIteration:
                raise web_server.WebSocketDisconnect()

        async def send_json(self, payload):
            self.payloads.append(payload)

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    async def _resolve_agent():
        return _Agent()

    async def _resolve_user(*_):
        return SimpleNamespace(id="u1", username="ada", role="developer")

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(web_server, "get_agent_event_bus", lambda: _EventBus())
    monkeypatch.setattr(web_server, "set_current_metrics_user_id", lambda _uid: None)
    monkeypatch.setattr(web_server, "reset_current_metrics_user_id", lambda _tok: None)

    ws = _Ws()
    await web_server.websocket_chat(ws)

    assert ws.subprotocol == "good-token"
    assert {"auth_ok": True} in ws.payloads


@pytest.mark.asyncio
async def test_status_endpoint_returns_provider_specific_model(monkeypatch):
    class _Health:
        def get_gpu_info(self):
            return {"devices": ["GPU-0"]}

        def check_ollama(self):
            return True

    class _Agent:
        VERSION = "1.2.3"

        def __init__(self):
            self.cfg = SimpleNamespace(
                AI_PROVIDER="gemini",
                GEMINI_MODEL="gemini-2.0-flash",
                CODING_MODEL="ignored",
                ACCESS_LEVEL="dev",
                MEMORY_ENCRYPTION_KEY="secret",
                USE_GPU=True,
                GPU_INFO={"vendor": "nvidia"},
                GPU_COUNT=1,
                CUDA_VERSION="12.4",
            )
            self.memory = ["m1"]
            self.github = SimpleNamespace(is_available=lambda: True)
            self.web = SimpleNamespace(is_available=lambda: False)
            self.docs = SimpleNamespace(status=lambda: {"ok": True})
            self.pkg = SimpleNamespace(status=lambda: {"ok": True})
            self.health = _Health()

    async def _resolve_agent():
        return _Agent()

    ticks = iter([10.0, 10.1226, 10.1226])
    def _monotonic():
        try:
            return next(ticks)
        except StopIteration:
            return 10.1226
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server.time, "monotonic", _monotonic)

    response = await web_server.status()
    payload = response.body.decode("utf-8")

    assert '"provider":"gemini"' in payload
    assert '"model":"gemini-2.0-flash"' in payload
    assert '"ollama_online":true' in payload
    assert '"ollama_latency_ms":122' in payload


@pytest.mark.asyncio
async def test_websocket_voice_import_error_closes_connection(monkeypatch):
    class _Ws:
        def __init__(self):
            self.headers = {}
            self.sent = []
            self.closed = None
            self.accepted = False

        async def accept(self, subprotocol=None):
            self.accepted = True

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

    orig_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.multimodal":
            raise ImportError("missing")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    ws = _Ws()
    await web_server.websocket_voice(ws)

    assert ws.accepted is True
    assert ws.sent[-1]["error"] == "core.multimodal modülü yüklenemedi."
    assert ws.closed == {"code": 1011, "reason": "multimodal unavailable"}


@pytest.mark.asyncio
async def test_websocket_voice_auth_start_append_commit_and_cancel(monkeypatch):
    class _VoicePipeline:
        def __init__(self, _cfg):
            self.enabled = True
            self.vad_enabled = True
            self.duplex_enabled = True

        def create_duplex_state(self):
            return SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")

        def build_voice_state_payload(self, event, buffered_bytes, sequence, duplex_state):
            return {
                "voice_state": event,
                "buffered_bytes": buffered_bytes,
                "sequence": sequence,
                "assistant_turn_id": duplex_state.assistant_turn_id,
            }

        def begin_assistant_turn(self, duplex_state):
            duplex_state.assistant_turn_id += 1
            return duplex_state.assistant_turn_id

        def interrupt_assistant_turn(self, duplex_state, reason):
            duplex_state.last_interrupt_reason = reason
            return {
                "assistant_turn_id": duplex_state.assistant_turn_id,
                "dropped_text_chars": 0,
                "cancelled_audio_sequences": 0,
                "reason": reason,
            }

        def should_interrupt_response(self, _buffer_len, event):
            return event == "speech_start"

        def should_commit_audio(self, _buffer_len, event):
            return event == "speech_end"

    class _MultimodalPipeline:
        def __init__(self, *_):
            pass

        async def transcribe_bytes(self, *_args, **_kwargs):
            return {"success": True, "text": "merhaba", "language": "tr", "provider": "fake"}

    class _Memory:
        async def set_active_user(self, *_):
            return None

    class _Agent:
        def __init__(self):
            self.llm = object()
            self.memory = _Memory()

    class _Ws:
        def __init__(self):
            self.headers = {}
            self.sent = []
            self.accepted = None
            self.closed = None
            self._packets = iter([
                {"type": "websocket.receive", "text": '{"action":"auth","token":"tok"}'},
                {"type": "websocket.receive", "text": '{"action":"start","mime_type":"audio/wav"}'},
                {"type": "websocket.receive", "text": '{"action":"append_base64","chunk":"###"}'},
                {"type": "websocket.receive", "text": '{"action":"append_base64","chunk":"YQ=="}'},
                {"type": "websocket.receive", "text": '{"action":"vad_event","state":"speech_end"}'},
                {"type": "websocket.receive", "text": '{"action":"cancel"}'},
                {"type": "websocket.disconnect"},
            ])

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = {"code": code, "reason": reason}

        async def receive(self):
            await asyncio.sleep(0)
            return next(self._packets)

    async def _resolve_agent():
        return _Agent()

    async def _resolve_user(*_):
        return SimpleNamespace(id="u1", username="ada")

    async def _fake_stream(ws, _agent, text):
        await ws.send_json({"chunk": text})

    mm_module = types.ModuleType("core.multimodal")
    mm_module.MultimodalPipeline = _MultimodalPipeline
    voice_module = types.ModuleType("core.voice")
    voice_module.VoicePipeline = _VoicePipeline

    monkeypatch.setitem(sys.modules, "core.multimodal", mm_module)
    monkeypatch.setitem(sys.modules, "core.voice", voice_module)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_ws_stream_agent_text_response", _fake_stream)
    monkeypatch.setattr(web_server.cfg, "VOICE_WS_MAX_BYTES", 1024)

    ws = _Ws()
    await web_server.websocket_voice(ws)

    assert ws.accepted is None
    assert {"auth_ok": True} in ws.sent
    assert any(item.get("voice_session") == "ready" for item in ws.sent)
    assert any(item.get("error") == "Geçersiz base64 ses parçası" for item in ws.sent)
    assert any(item.get("transcript") == "merhaba" for item in ws.sent)
    assert any(item.get("assistant_turn") == "completed" for item in ws.sent)
    assert any(item.get("cancelled") is True for item in ws.sent)


@pytest.mark.asyncio
async def test_websocket_voice_rejects_invalid_header_token(monkeypatch):
    class _MultimodalPipeline:
        def __init__(self, *_):
            pass

    class _Memory:
        async def set_active_user(self, *_):
            return None

    class _Agent:
        def __init__(self):
            self.llm = object()
            self.memory = _Memory()

    class _Ws:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "bad-token"}
            self.sent = []
            self.accepted = None

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive(self):
            return {"type": "websocket.disconnect"}

    async def _resolve_agent():
        return _Agent()

    async def _resolve_user(*_):
        return None

    closed = {}

    async def _close_policy(_ws, reason):
        closed["reason"] = reason

    mm_module = types.ModuleType("core.multimodal")
    mm_module.MultimodalPipeline = _MultimodalPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", mm_module)
    monkeypatch.delitem(sys.modules, "core.voice", raising=False)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "_ws_close_policy_violation", _close_policy)

    ws = _Ws()
    await web_server.websocket_voice(ws)

    assert ws.accepted == "bad-token"
    assert closed["reason"] == "Invalid or expired token"


@pytest.mark.asyncio
async def test_websocket_voice_closes_on_binary_before_auth_and_payload_limit(monkeypatch):
    class _MultimodalPipeline:
        def __init__(self, *_):
            pass

        async def transcribe_bytes(self, *_args, **_kwargs):
            return {"success": False, "reason": "x"}

    class _Memory:
        async def set_active_user(self, *_):
            return None

    class _Agent:
        def __init__(self):
            self.llm = object()
            self.memory = _Memory()

    class _Ws:
        def __init__(self, packets):
            self.headers = {}
            self.sent = []
            self._packets = iter(packets)

        async def accept(self, subprotocol=None):
            return None

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive(self):
            await asyncio.sleep(0)
            return next(self._packets)

    async def _resolve_agent():
        return _Agent()

    async def _resolve_user(*_):
        return SimpleNamespace(id="u1", username="ada")

    mm_module = types.ModuleType("core.multimodal")
    mm_module.MultimodalPipeline = _MultimodalPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", mm_module)
    monkeypatch.delitem(sys.modules, "core.voice", raising=False)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server.cfg, "VOICE_WS_MAX_BYTES", 2)

    closed = []

    async def _close_policy(_ws, reason):
        closed.append(reason)

    monkeypatch.setattr(web_server, "_ws_close_policy_violation", _close_policy)

    ws_unauth = _Ws([{"type": "websocket.receive", "bytes": b"abc"}])
    await web_server.websocket_voice(ws_unauth)
    assert closed[-1] == "Authentication required"

    ws_big = _Ws(
        [
            {"type": "websocket.receive", "text": '{"action":"auth","token":"ok"}'},
            {"type": "websocket.receive", "bytes": b"abc"},
        ]
    )
    await web_server.websocket_voice(ws_big)
    assert closed[-1] == "Voice payload too large"


@pytest.mark.asyncio
async def test_websocket_voice_auth_token_validation_paths(monkeypatch):
    class _MultimodalPipeline:
        def __init__(self, *_):
            pass

    class _Memory:
        async def set_active_user(self, *_):
            return None

    class _Agent:
        def __init__(self):
            self.llm = object()
            self.memory = _Memory()

    class _Ws:
        def __init__(self, first_message):
            self.headers = {}
            self._packets = iter([{"type": "websocket.receive", "text": first_message}])

        async def accept(self, subprotocol=None):
            return None

        async def send_json(self, payload):
            _ = payload

        async def receive(self):
            await asyncio.sleep(0)
            return next(self._packets)

    async def _resolve_agent():
        return _Agent()

    mm_module = types.ModuleType("core.multimodal")
    mm_module.MultimodalPipeline = _MultimodalPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", mm_module)
    monkeypatch.delitem(sys.modules, "core.voice", raising=False)
    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)

    closed = []

    async def _close_policy(_ws, reason):
        closed.append(reason)

    monkeypatch.setattr(web_server, "_ws_close_policy_violation", _close_policy)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", lambda *_: None)

    ws_missing = _Ws('{"action":"auth","token":""}')
    await web_server.websocket_voice(ws_missing)
    assert closed[-1] == "Authentication token missing"

    ws_invalid = _Ws('{"action":"auth","token":"bad"}')
    await web_server.websocket_voice(ws_invalid)
    assert closed[-1] == "Invalid or expired token"


@pytest.mark.asyncio
async def test_status_uses_coding_model_for_non_gemini_provider(monkeypatch):
    class _Health:
        def get_gpu_info(self):
            return {"devices": []}

        def check_ollama(self):
            return False

    class _Agent:
        VERSION = "v"

        def __init__(self):
            self.cfg = SimpleNamespace(
                AI_PROVIDER="openai",
                CODING_MODEL="gpt-x",
                ACCESS_LEVEL="dev",
                MEMORY_ENCRYPTION_KEY="",
                USE_GPU=False,
                GPU_INFO={},
            )
            self.memory = []
            self.github = SimpleNamespace(is_available=lambda: True)
            self.web = SimpleNamespace(is_available=lambda: True)
            self.docs = SimpleNamespace(status=lambda: {"ok": True})
            self.pkg = SimpleNamespace(status=lambda: {"ok": True})
            self.health = _Health()

    async def _resolve_agent():
        return _Agent()

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)
    monkeypatch.setattr(web_server.time, "monotonic", lambda: 100.0)
    response = await web_server.status()
    payload = response.body.decode("utf-8")
    assert '"model":"gpt-x"' in payload


@pytest.mark.asyncio
async def test_agent_plugin_registration_endpoints(monkeypatch):
    captured = {}

    def _register_plugin_agent(**kwargs):
        captured.update(kwargs)
        return {"role_name": kwargs["role_name"], "status": "ok"}

    monkeypatch.setattr(web_server, "_register_plugin_agent", _register_plugin_agent)

    payload = web_server._AgentPluginRegisterRequest(
        role_name="demo_role",
        source_code="class Demo: pass",
        class_name="Demo",
        capabilities=["code_generation"],
        description="demo",
        version="1.2.3",
    )
    response = await web_server.register_agent_plugin(payload, _user=SimpleNamespace(role="admin"))

    assert response.status_code == 200
    assert response.body
    assert captured["role_name"] == "demo_role"
    assert captured["capabilities"] == ["code_generation"]


@pytest.mark.asyncio
async def test_register_agent_plugin_file_validations_and_success(monkeypatch):
    class _Upload:
        def __init__(self, filename: str, data: bytes):
            self.filename = filename
            self._data = data
            self.closed = False

        async def read(self):
            return self._data

        async def close(self):
            self.closed = True

    with pytest.raises(HTTPException) as empty_exc:
        await web_server.register_agent_plugin_file(_Upload("demo.py", b""), _user=SimpleNamespace(role="admin"))
    assert empty_exc.value.status_code == 400

    too_large = b"a" * (web_server.MAX_FILE_CONTENT_BYTES + 1)
    with pytest.raises(HTTPException) as large_exc:
        await web_server.register_agent_plugin_file(_Upload("demo.py", too_large), _user=SimpleNamespace(role="admin"))
    assert large_exc.value.status_code == 413

    with pytest.raises(HTTPException) as utf_exc:
        await web_server.register_agent_plugin_file(_Upload("demo.py", b"\xff"), _user=SimpleNamespace(role="admin"))
    assert utf_exc.value.status_code == 400

    captured = {}
    monkeypatch.setattr(web_server.secrets, "token_hex", lambda _: "beefbeef")
    monkeypatch.setattr(web_server, "_persist_and_import_plugin_file", lambda *args: captured.setdefault("persist", args))

    def _register_plugin_agent(**kwargs):
        captured["register"] = kwargs
        return {"role_name": kwargs["role_name"], "installed": True}

    monkeypatch.setattr(web_server, "_register_plugin_agent", _register_plugin_agent)
    ok_response = await web_server.register_agent_plugin_file(
        _Upload("my_plugin.py", b"print('ok')\n"),
        role_name="",
        class_name=" AgentClass ",
        capabilities="alpha, beta ,,",
        description="desc",
        version="2.0.0",
        _user=SimpleNamespace(role="admin"),
    )

    assert ok_response.status_code == 200
    assert captured["persist"][2] == "sidar_uploaded_plugin_beefbeef"
    assert captured["register"]["role_name"] == "my_plugin"
    assert captured["register"]["class_name"] == "AgentClass"
    assert captured["register"]["capabilities"] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_plugin_marketplace_http_handlers(monkeypatch):
    monkeypatch.setattr(web_server, "PLUGIN_MARKETPLACE_CATALOG", {
        "xx": {"name": "Plugin X"},
        "aa": {"name": "Plugin A"},
    })
    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: {"aa": {"installed_at": "now"}})
    monkeypatch.setattr(
        web_server,
        "_serialize_marketplace_plugin",
        lambda plugin_id, installed_state=None: {"plugin_id": plugin_id, "state": installed_state or {}},
    )
    monkeypatch.setattr(web_server, "_install_marketplace_plugin", lambda plugin_id: {"ok": True, "plugin_id": plugin_id})
    monkeypatch.setattr(web_server, "_uninstall_marketplace_plugin", lambda plugin_id: {"removed": plugin_id})

    catalog = await web_server.plugin_marketplace_catalog(_user=SimpleNamespace(role="admin"))
    assert b'"plugin_id":"aa"' in catalog.body
    assert b'"plugin_id":"xx"' in catalog.body

    payload = web_server._PluginMarketplaceInstallRequest(plugin_id="aa")
    install = await web_server.install_plugin_marketplace_item(payload, _user=SimpleNamespace(role="admin"))
    reload_res = await web_server.reload_plugin_marketplace_item(payload, _user=SimpleNamespace(role="admin"))
    uninstall = await web_server.uninstall_plugin_marketplace_item("aa", _user=SimpleNamespace(role="admin"))

    assert install.body == b'{"ok":true,"plugin_id":"aa"}'
    assert reload_res.body == b'{"ok":true,"plugin_id":"aa"}'
    assert uninstall.body == b'{"removed":"aa"}'


@pytest.mark.asyncio
async def test_execute_swarm_pipeline_parallel_and_validation(monkeypatch):
    class _Orchestrator:
        def __init__(self, _cfg):
            self.cfg = _cfg

        async def run_pipeline(self, tasks, session_id):
            return [SimpleNamespace(task_id="p1", status="ok", summary=f"{session_id}:{len(tasks)}")]

        async def run_parallel(self, tasks, session_id, max_concurrency):
            return [SimpleNamespace(task_id="r1", status="ok", summary=f"{session_id}:{max_concurrency}:{len(tasks)}")]

    monkeypatch.setattr(web_server, "SwarmOrchestrator", _Orchestrator)
    async def _resolve_agent():
        return SimpleNamespace(cfg=SimpleNamespace())

    monkeypatch.setattr(web_server, "_resolve_agent_instance", _resolve_agent)

    pipeline_payload = web_server._SwarmExecuteRequest(
        mode="pipeline",
        tasks=[web_server._SwarmTaskRequest(goal="  Ship  ", intent=" build ", context={"k": "v"})],
        session_id="sess-1",
        max_concurrency=3,
    )
    user = SimpleNamespace(id="u1")
    pipeline = await web_server.execute_swarm(pipeline_payload, user=user)
    assert b'"mode":"pipeline"' in pipeline.body
    assert b'"task_count":1' in pipeline.body

    parallel_payload = web_server._SwarmExecuteRequest(
        mode="parallel",
        tasks=[web_server._SwarmTaskRequest(goal="Analyze")],
        session_id="",
        max_concurrency=2,
    )
    parallel = await web_server.execute_swarm(parallel_payload, user=user)
    assert b'"mode":"parallel"' in parallel.body
    assert b'"session_id":"swarm-u1"' in parallel.body

    bad_payload = web_server._SwarmExecuteRequest(
        mode="parallel",
        tasks=[web_server._SwarmTaskRequest(goal="   ")],
        session_id="",
        max_concurrency=2,
    )
    with pytest.raises(HTTPException) as bad_exc:
        await web_server.execute_swarm(bad_payload, user=user)
    assert bad_exc.value.status_code == 400


@pytest.mark.asyncio
async def test_hitl_endpoints_cover_create_pending_and_respond(monkeypatch):
    added: list[object] = []
    pending_items = [SimpleNamespace(to_dict=lambda: {"request_id": "r1"})]

    class _Store:
        async def pending(self):
            return pending_items

        async def add(self, request):
            added.append(request)

    class _Gate:
        timeout = 42

        async def respond(self, request_id, approved, decided_by, rejection_reason):
            if request_id == "missing":
                return None
            return SimpleNamespace(
                request_id=request_id,
                decision=SimpleNamespace(value="approved" if approved else "rejected"),
            )

    async def _notify(_req):
        return None

    monkeypatch.setattr(web_server, "get_hitl_store", lambda: _Store())
    monkeypatch.setattr(web_server, "get_hitl_gate", lambda: _Gate())
    monkeypatch.setitem(
        sys.modules,
        "core.hitl",
        SimpleNamespace(
            HITLRequest=lambda **kwargs: SimpleNamespace(**kwargs),
            notify=_notify,
            get_hitl_store=lambda: _Store(),
        ),
    )

    user = SimpleNamespace(username="ada")
    pending = await web_server.hitl_pending(user=user)
    assert pending.status_code == 200
    assert b'"count":1' in pending.body

    created = await web_server.hitl_create_request(
        {"action": "deploy", "description": "Prod deploy", "payload": {"env": "prod"}},
        user=user,
    )
    assert created.status_code == 200
    assert added

    approved = await web_server.hitl_respond(
        "req-1",
        payload=web_server._HITLRespondRequest(approved=True, decided_by="", rejection_reason=""),
        user=user,
    )
    assert approved.status_code == 200
    assert b'"decision":"approved"' in approved.body

    with pytest.raises(HTTPException) as exc_info:
        await web_server.hitl_respond(
            "missing",
            payload=web_server._HITLRespondRequest(approved=False, decided_by="op", rejection_reason="no"),
            user=user,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_file_content_covers_security_dir_and_size_guards(tmp_path, monkeypatch):
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / "docs").mkdir()
    (fake_root / "big.txt").write_text("x" * 20, encoding="utf-8")
    monkeypatch.setattr(web_server, "__file__", str(fake_root / "web_server.py"))
    monkeypatch.setattr(web_server, "MAX_FILE_CONTENT_BYTES", 5)

    outside = await web_server.file_content("../secret.txt")
    assert outside.status_code == 403

    is_dir = await web_server.file_content("docs")
    assert is_dir.status_code == 400

    too_big = await web_server.file_content("big.txt")
    assert too_big.status_code == 413


@pytest.mark.asyncio
async def test_set_branch_empty_and_checkout_error_paths(monkeypatch):
    empty_name = await web_server.set_branch(_JsonRequest({"branch": "   "}))
    assert empty_name.status_code == 400

    async def _inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def _raise_checkout(*_args, **_kwargs):
        raise web_server.subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "checkout", "feature/x"],
            output=b"checkout failed",
        )

    monkeypatch.setattr(web_server.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(web_server.subprocess, "check_output", _raise_checkout)
    failed = await web_server.set_branch(_JsonRequest({"branch": "feature/x"}))
    assert failed.status_code == 400
    assert b"checkout failed" in failed.body


@pytest.mark.asyncio
async def test_github_endpoints_failure_paths(monkeypatch):
    class _Github:
        repo_name = "org/active"

        def list_repos(self, owner="", limit=200):
            return False, []

        def is_available(self):
            return False

        def get_pull_requests_detailed(self, **_):
            return False, [], "boom"

        def get_pull_request(self, number):
            return False, f"missing-{number}"

    agent = SimpleNamespace(github=_Github())
    monkeypatch.setattr(web_server, "_get_agent_instance", lambda: agent)

    repos = await web_server.github_repos()
    prs = await web_server.github_prs()
    detail = await web_server.github_pr_detail(99)

    assert repos.status_code == 400
    assert prs.status_code == 503
    assert detail.status_code == 503


@pytest.mark.asyncio
async def test_upload_rag_file_size_error_and_backend_failure(monkeypatch):
    class _FakeUpload:
        def __init__(self, filename: str, data: bytes):
            self.filename = filename
            self._data = data
            self.closed = False

        async def read(self, _size: int):
            return self._data

        async def close(self):
            self.closed = True

    class _Docs:
        def add_document_from_file(self, *_args, **_kwargs):
            return False, "index failed"

    agent = SimpleNamespace(docs=_Docs(), memory=SimpleNamespace(active_session_id=None))
    monkeypatch.setattr(web_server, "_get_agent_instance", lambda: agent)

    async def _inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(web_server.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(web_server.Config, "MAX_RAG_UPLOAD_BYTES", 4)

    too_big_file = _FakeUpload("huge.txt", b"012345")
    with pytest.raises(HTTPException) as too_big_exc:
        await web_server.upload_rag_file(too_big_file)
    assert too_big_exc.value.status_code == 413
    assert too_big_file.closed is True

    small_file = _FakeUpload("safe.txt", b"ok")
    failed = await web_server.upload_rag_file(small_file)
    assert failed.status_code == 400
    assert b"index failed" in failed.body
    assert small_file.closed is True
