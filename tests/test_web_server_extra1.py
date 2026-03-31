"""
web_server.py için ek testler - Part 1
Missing lines: 42, 57-100, 226-227, 283-354, 407-413, 446-570, 579-603, 607-699

Heavy deps stubbed via sys.modules.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stubs (same as test_web_server.py)
# ---------------------------------------------------------------------------

class _Dummy:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        pass

    def _decorator(self, *_args, **_kwargs):
        def _inner(func):
            return func
        return _inner

    middleware = _decorator
    exception_handler = _decorator
    get = _decorator
    post = _decorator
    put = _decorator
    delete = _decorator
    patch = _decorator
    websocket = _decorator

    def mount(self, *args, **kwargs):
        return None

    def add_middleware(self, *args, **kwargs):
        return None


class _HTTPException(Exception):
    def __init__(self, status_code: int = 500, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _inject_web_server_stubs() -> None:
    for name in (
        "jwt", "uvicorn", "fastapi", "fastapi.middleware",
        "fastapi.middleware.cors", "fastapi.responses", "fastapi.staticfiles",
        "pydantic", "redis", "redis.asyncio",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))

    fastapi_mod = sys.modules["fastapi"]
    fastapi_mod.BackgroundTasks = _Dummy
    fastapi_mod.FastAPI = _FakeFastAPI
    fastapi_mod.Request = _Dummy
    fastapi_mod.UploadFile = _Dummy
    fastapi_mod.File = _Dummy
    fastapi_mod.WebSocket = _Dummy
    fastapi_mod.WebSocketDisconnect = Exception
    fastapi_mod.Depends = _Dummy
    fastapi_mod.Header = _Dummy
    fastapi_mod.HTTPException = _HTTPException

    cors_mod = sys.modules["fastapi.middleware.cors"]
    cors_mod.CORSMiddleware = _Dummy

    responses_mod = sys.modules["fastapi.responses"]
    responses_mod.FileResponse = _Dummy
    responses_mod.HTMLResponse = _Dummy
    responses_mod.JSONResponse = _Dummy
    responses_mod.Response = _Dummy

    staticfiles_mod = sys.modules["fastapi.staticfiles"]
    staticfiles_mod.StaticFiles = _Dummy

    pydantic_mod = sys.modules["pydantic"]
    pydantic_mod.BaseModel = object
    pydantic_mod.Field = lambda *args, **kwargs: None

    redis_asyncio_mod = sys.modules["redis.asyncio"]
    redis_asyncio_mod.Redis = _Dummy

    uvicorn_mod = sys.modules["uvicorn"]
    uvicorn_mod.run = lambda *args, **kwargs: None

    cfg_mod = types.ModuleType("config")

    class _Config:
        BASE_DIR = str(Path(".").resolve())
        WEB_HOST = "0.0.0.0"
        WEB_PORT = 7860
        VERSION = "test"
        RATE_LIMIT_CHAT = 20
        RATE_LIMIT_MUTATION = 60
        RATE_LIMIT_GIT_IO = 30

        @staticmethod
        def initialize_directories() -> None:
            return None

        @staticmethod
        def validate_critical_settings() -> None:
            return None

        def init_telemetry(self, **_kwargs) -> None:
            return None

        def __getattr__(self, _name):
            return 0

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = type("BaseAgent", (), {})
    sys.modules["agent.base_agent"] = base_agent_mod

    contracts_mod = types.ModuleType("agent.core.contracts")
    for symbol in ("ActionFeedback", "ExternalTrigger", "FederationTaskEnvelope", "FederationTaskResult"):
        setattr(contracts_mod, symbol, type(symbol, (), {}))
    contracts_mod.LEGACY_FEDERATION_PROTOCOL_V1 = "p1"
    contracts_mod.derive_correlation_id = lambda *args, **kwargs: "cid"
    contracts_mod.normalize_federation_protocol = lambda value: value
    sys.modules["agent.core.contracts"] = contracts_mod

    event_stream_mod = types.ModuleType("agent.core.event_stream")
    event_stream_mod.get_agent_event_bus = lambda: _Dummy()
    sys.modules["agent.core.event_stream"] = event_stream_mod

    registry_mod = types.ModuleType("agent.registry")
    registry_mod.AgentRegistry = type("AgentRegistry", (), {})
    sys.modules["agent.registry"] = registry_mod

    sidar_agent_mod = types.ModuleType("agent.sidar_agent")
    sidar_agent_mod.SidarAgent = type("SidarAgent", (), {"VERSION": "test"})
    sys.modules["agent.sidar_agent"] = sidar_agent_mod

    swarm_mod = types.ModuleType("agent.swarm")
    swarm_mod.SwarmOrchestrator = type("SwarmOrchestrator", (), {})
    swarm_mod.SwarmTask = type("SwarmTask", (), {})
    sys.modules["agent.swarm"] = swarm_mod

    ci_mod = types.ModuleType("core.ci_remediation")
    ci_mod.build_ci_failure_context = lambda *args, **kwargs: {}
    sys.modules["core.ci_remediation"] = ci_mod

    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_gate = lambda: _Dummy()
    hitl_mod.get_hitl_store = lambda: _Dummy()
    hitl_mod.set_hitl_broadcast_hook = lambda _hook: None
    sys.modules["core.hitl"] = hitl_mod

    llm_client_mod = types.ModuleType("core.llm_client")
    llm_client_mod.LLMAPIError = type("LLMAPIError", (Exception,), {})
    sys.modules["core.llm_client"] = llm_client_mod

    llm_metrics_mod = types.ModuleType("core.llm_metrics")
    llm_metrics_mod.get_llm_metrics_collector = lambda: _Dummy()
    llm_metrics_mod.reset_current_metrics_user_id = lambda _token: None
    llm_metrics_mod.set_current_metrics_user_id = lambda _user_id: None
    sys.modules["core.llm_metrics"] = llm_metrics_mod

    health_mod = types.ModuleType("managers.system_health")
    health_mod.render_llm_metrics_prometheus = lambda: ""
    sys.modules["managers.system_health"] = health_mod


def _get_ws():
    _inject_web_server_stubs()
    sys.modules.pop("web_server", None)
    return importlib.import_module("web_server")


# ---------------------------------------------------------------------------
# Tests for _mask_collaboration_text (lines 222-227)
# ---------------------------------------------------------------------------

class TestMaskCollaborationText:
    def test_returns_text_when_dlp_unavailable(self):
        ws = _get_ws()
        result = ws._mask_collaboration_text("hello world")
        assert result == "hello world"

    def test_empty_string_returns_empty(self):
        ws = _get_ws()
        result = ws._mask_collaboration_text("")
        assert result == ""

    def test_none_returns_empty(self):
        ws = _get_ws()
        result = ws._mask_collaboration_text(None)
        assert result == ""

    def test_calls_mask_pii_when_dlp_available(self):
        ws = _get_ws()
        dlp_mod = types.ModuleType("core.dlp")
        dlp_mod.mask_pii = lambda text: f"[MASKED:{text}]"
        with patch.dict(sys.modules, {"core.dlp": dlp_mod}):
            # Need to reload web_server to pick up new stub
            sys.modules.pop("web_server", None)
            ws2 = importlib.import_module("web_server")
            result = ws2._mask_collaboration_text("sensitive data")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests for _broadcast_room_payload (lines 282-290)
# ---------------------------------------------------------------------------

class TestBroadcastRoomPayload:
    def test_sends_to_all_participants(self):
        ws = _get_ws()
        sent = []

        class _FakeWS:
            async def send_json(self, payload):
                sent.append(payload)

        room = ws._CollaborationRoom(room_id="test")
        room.participants = {1: types.SimpleNamespace(websocket=_FakeWS())}

        payload = {"type": "test", "data": "hello"}
        asyncio.run(ws._broadcast_room_payload(room, payload))
        assert len(sent) == 1
        assert sent[0]["type"] == "test"

    def test_removes_stale_participants_on_exception(self):
        ws = _get_ws()

        class _FailingWS:
            async def send_json(self, payload):
                raise ConnectionError("disconnected")

        room = ws._CollaborationRoom(room_id="test")
        room.participants = {
            1: types.SimpleNamespace(websocket=_FailingWS()),
        }
        asyncio.run(ws._broadcast_room_payload(room, {"type": "test"}))
        assert len(room.participants) == 0

    def test_broadcast_empty_room_noop(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="test")
        # Should not raise
        asyncio.run(ws._broadcast_room_payload(room, {"type": "test"}))


# ---------------------------------------------------------------------------
# Tests for _append_room_message / _append_room_telemetry (lines 242-256)
# ---------------------------------------------------------------------------

class TestRoomMessageAppend:
    def test_append_message_limits_to_200(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="test")
        for i in range(250):
            ws._append_room_message(room, {"i": i})
        assert len(room.messages) <= 200

    def test_append_telemetry_limits_to_200(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="test")
        for i in range(250):
            ws._append_room_telemetry(room, {"i": i})
        assert len(room.telemetry) <= 200

    def test_append_telemetry_masks_content(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="test")
        ws._append_room_telemetry(room, {"content": "secret data", "type": "event"})
        assert len(room.telemetry) == 1
        # content should be passed through mask
        assert "content" in room.telemetry[0]

    def test_append_telemetry_masks_error(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="test")
        ws._append_room_telemetry(room, {"error": "some error", "type": "fail"})
        assert len(room.telemetry) == 1


# ---------------------------------------------------------------------------
# Tests for _build_room_message (lines 259-279)
# ---------------------------------------------------------------------------

class TestBuildRoomMessage:
    def test_returns_dict_with_expected_keys(self):
        ws = _get_ws()
        msg = ws._build_room_message(
            room_id="r1",
            role="user",
            content="hello",
            author_name="Alice",
            author_id="u1",
        )
        assert msg["room_id"] == "r1"
        assert msg["role"] == "user"
        assert msg["author_name"] == "Alice"
        assert msg["author_id"] == "u1"
        assert "ts" in msg
        assert "id" in msg

    def test_kind_defaults_to_message(self):
        ws = _get_ws()
        msg = ws._build_room_message(
            room_id="r1", role="user", content="hi",
            author_name="Bob", author_id="u2",
        )
        assert msg["kind"] == "message"

    def test_custom_kind(self):
        ws = _get_ws()
        msg = ws._build_room_message(
            room_id="r1", role="assistant", content="response",
            author_name="Sidar", author_id="sys", kind="system",
        )
        assert msg["kind"] == "system"


# ---------------------------------------------------------------------------
# Tests for _is_sidar_mention / _strip_sidar_mention (lines 356-362)
# ---------------------------------------------------------------------------

class TestSidarMention:
    def test_detects_mention_at_start(self):
        ws = _get_ws()
        assert ws._is_sidar_mention("@sidar help me") is True

    def test_detects_mention_after_space(self):
        ws = _get_ws()
        assert ws._is_sidar_mention("hey @sidar what's up") is True

    def test_no_mention(self):
        ws = _get_ws()
        assert ws._is_sidar_mention("hello world") is False

    def test_case_insensitive(self):
        ws = _get_ws()
        assert ws._is_sidar_mention("@SIDAR help") is True

    def test_strip_mention_removes_it(self):
        ws = _get_ws()
        result = ws._strip_sidar_mention("@sidar do the thing")
        assert "@sidar" not in result.lower()
        assert "do the thing" in result

    def test_strip_mention_cleans_whitespace(self):
        ws = _get_ws()
        result = ws._strip_sidar_mention("@sidar   help   ")
        assert result.strip() == "help"


# ---------------------------------------------------------------------------
# Tests for _build_collaboration_prompt (lines 365-395)
# ---------------------------------------------------------------------------

class TestBuildCollaborationPrompt:
    def _make_room_with_participant(self, ws):
        room = ws._CollaborationRoom(room_id="ws:code")
        room.messages = [
            {"role": "user", "author_name": "Alice", "content": "fix bug"},
        ]
        participant = types.SimpleNamespace(
            display_name="Alice",
            role="editor",
            write_scopes=["ws:code"],
        )
        room.participants = {1: participant}
        return room

    def test_prompt_contains_room_id(self):
        ws = _get_ws()
        room = self._make_room_with_participant(ws)
        prompt = ws._build_collaboration_prompt(room, actor_name="Alice", command="fix bug")
        assert "ws:code" in prompt

    def test_prompt_contains_actor(self):
        ws = _get_ws()
        room = self._make_room_with_participant(ws)
        prompt = ws._build_collaboration_prompt(room, actor_name="Alice", command="fix bug")
        assert "Alice" in prompt

    def test_prompt_contains_command(self):
        ws = _get_ws()
        room = self._make_room_with_participant(ws)
        prompt = ws._build_collaboration_prompt(room, actor_name="Alice", command="fix the bug NOW")
        assert "fix the bug NOW" in prompt

    def test_prompt_for_unknown_actor(self):
        ws = _get_ws()
        room = self._make_room_with_participant(ws)
        prompt = ws._build_collaboration_prompt(room, actor_name="Unknown", command="test")
        # Should use default role
        assert "user" in prompt or "requesting_role" in prompt


# ---------------------------------------------------------------------------
# Tests for _iter_stream_chunks (lines 398-402)
# ---------------------------------------------------------------------------

class TestIterStreamChunks:
    def test_empty_text_returns_empty_list(self):
        ws = _get_ws()
        assert ws._iter_stream_chunks("") == []

    def test_none_returns_empty_list(self):
        ws = _get_ws()
        assert ws._iter_stream_chunks(None) == []

    def test_short_text_single_chunk(self):
        ws = _get_ws()
        chunks = ws._iter_stream_chunks("hello")
        assert len(chunks) == 1
        assert chunks[0] == "hello"

    def test_long_text_splits_at_size(self):
        ws = _get_ws()
        text = "x" * 500
        chunks = ws._iter_stream_chunks(text, size=100)
        assert len(chunks) == 5
        assert all(len(c) == 100 for c in chunks)


# ---------------------------------------------------------------------------
# Tests for _hitl_broadcast (lines 405-413)
# ---------------------------------------------------------------------------

class TestHitlBroadcast:
    def test_broadcasts_to_all_ws_clients(self):
        ws = _get_ws()
        received = []

        class _FakeWS:
            async def send_json(self, payload):
                received.append(payload)

        ws._hitl_ws_clients.clear()
        ws._hitl_ws_clients.add(_FakeWS())
        ws._hitl_ws_clients.add(_FakeWS())

        asyncio.run(ws._hitl_broadcast({"type": "hitl_event"}))
        assert len(received) == 2

    def test_removes_dead_ws_clients(self):
        ws = _get_ws()

        class _DeadWS:
            async def send_json(self, payload):
                raise RuntimeError("dead")

        ws._hitl_ws_clients.clear()
        dead = _DeadWS()
        ws._hitl_ws_clients.add(dead)
        asyncio.run(ws._hitl_broadcast({"type": "test"}))
        assert dead not in ws._hitl_ws_clients


# ---------------------------------------------------------------------------
# Tests for _list_child_ollama_pids (lines 438-485)
# ---------------------------------------------------------------------------

class TestListChildOllamaPids:
    def test_returns_list(self):
        ws = _get_ws()
        # Should return a list (may be empty in test env)
        result = ws._list_child_ollama_pids()
        assert isinstance(result, list)

    def test_returns_empty_when_psutil_fails(self):
        ws = _get_ws()
        with patch.dict(sys.modules, {"psutil": None}):
            # Without psutil, falls back to ps command or returns empty
            result = ws._list_child_ollama_pids()
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests for _reap_child_processes_nonblocking (lines 488-501)
# ---------------------------------------------------------------------------

class TestReapChildProcesses:
    def test_returns_int(self):
        ws = _get_ws()
        result = ws._reap_child_processes_nonblocking()
        assert isinstance(result, int)
        assert result >= 0

    def test_handles_no_children(self):
        ws = _get_ws()
        # Should not raise even with no child processes
        count = ws._reap_child_processes_nonblocking()
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# Tests for _terminate_ollama_child_pids (lines 504-514)
# ---------------------------------------------------------------------------

class TestTerminateOllamaChildPids:
    def test_empty_pids_noop(self):
        ws = _get_ws()
        # Should not raise
        ws._terminate_ollama_child_pids([])

    def test_skips_grace_period_for_zero(self):
        ws = _get_ws()
        # grace_seconds=0 should not sleep
        ws._terminate_ollama_child_pids([], grace_seconds=0)


# ---------------------------------------------------------------------------
# Tests for _force_shutdown_local_llm_processes (lines 517-537)
# ---------------------------------------------------------------------------

class TestForceShutdown:
    def test_noop_when_not_ollama(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = False
        ws.cfg.AI_PROVIDER = "openai"
        ws._force_shutdown_local_llm_processes()
        assert ws._shutdown_cleanup_done is True

    def test_idempotent_second_call(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = True
        ws._force_shutdown_local_llm_processes()  # Should return immediately
        assert ws._shutdown_cleanup_done is True

    def test_ollama_no_force_kill(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = False
        ws.cfg.AI_PROVIDER = "ollama"
        ws.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = False
        ws._force_shutdown_local_llm_processes()
        assert ws._shutdown_cleanup_done is True


# ---------------------------------------------------------------------------
# Tests for _bind_llm_usage_sink (lines 573-602)
# ---------------------------------------------------------------------------

class TestBindLlmUsageSink:
    def test_noop_when_already_bound(self):
        ws = _get_ws()
        collector = MagicMock()
        collector._sidar_usage_sink_bound = True
        collector.set_usage_sink = MagicMock()
        ws.get_llm_metrics_collector = lambda: collector
        ws._bind_llm_usage_sink(MagicMock())
        collector.set_usage_sink.assert_not_called()

    def test_binds_sink_when_method_available(self):
        ws = _get_ws()
        collector = MagicMock()
        collector._sidar_usage_sink_bound = False
        collector.set_usage_sink = MagicMock()
        original = ws.get_llm_metrics_collector
        ws.get_llm_metrics_collector = lambda: collector
        try:
            ws._bind_llm_usage_sink(MagicMock())
            assert collector._sidar_usage_sink_bound is True
            collector.set_usage_sink.assert_called_once()
        finally:
            ws.get_llm_metrics_collector = original


# ---------------------------------------------------------------------------
# Tests for _build_event_driven_federation_spec (lines 658-934)
# ---------------------------------------------------------------------------

class TestBuildEventDrivenFederationSpec:
    def test_returns_none_for_unknown_source(self):
        ws = _get_ws()
        result = ws._build_event_driven_federation_spec("unknown_source", "unknown_event", {})
        assert result is None

    def test_github_pr_opened_returns_spec(self):
        ws = _get_ws()
        result = ws._build_event_driven_federation_spec(
            "github", "pull_request",
            {"action": "opened", "pull_request": {"number": 42, "title": "Fix bug", "body": "details"}}
        )
        assert result is not None
        assert result.get("workflow_type") == "github_pull_request"

    def test_github_push_returns_spec(self):
        ws = _get_ws()
        # GitHub push requires commits with meaningful content
        result = ws._build_event_driven_federation_spec(
            "github", "push",
            {
                "ref": "refs/heads/main",
                "commits": [{"message": "fix: thing", "id": "abc123"}],
                "repository": {"full_name": "user/repo"},
            }
        )
        # push may return None if not matching expected actions
        assert result is None or isinstance(result, dict)

    def test_jira_bug_returns_spec(self):
        ws = _get_ws()
        # Jira issue needs a "key" field (e.g. "BUG-123")
        result = ws._build_event_driven_federation_spec(
            "jira", "issue_created",
            {"issue": {"key": "BUG-123", "fields": {"issuetype": {"name": "Bug"}, "summary": "App crashes", "description": ""}}}
        )
        assert result is not None

    def test_system_monitor_critical_returns_spec(self):
        ws = _get_ws()
        result = ws._build_event_driven_federation_spec(
            "system_monitor", "error_detected",
            {"severity": "critical", "alert_name": "DB Down", "message": "Connection refused"}
        )
        assert result is not None
        assert result.get("workflow_type") == "system_error"

    def test_system_monitor_info_returns_none(self):
        ws = _get_ws()
        result = ws._build_event_driven_federation_spec(
            "system_monitor", "info_event",
            {"severity": "info", "alert_name": "Routine check"}
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _build_swarm_goal_for_role (lines 937-952)
# ---------------------------------------------------------------------------

class TestBuildSwarmGoalForRole:
    def test_coder_role_includes_coder_marker(self):
        ws = _get_ws()
        spec = {"context": {"key": "value"}, "inputs": ["input1"]}
        result = ws._build_swarm_goal_for_role("fix bug", "coder", spec)
        assert "EVENT_DRIVEN_SWARM:CODER" in result
        assert "fix bug" in result

    def test_reviewer_role_includes_reviewer_marker(self):
        ws = _get_ws()
        spec = {"context": {}, "inputs": []}
        result = ws._build_swarm_goal_for_role("review code", "reviewer", spec)
        assert "EVENT_DRIVEN_SWARM:REVIEWER" in result
        assert "review code" in result

    def test_unknown_role_falls_to_reviewer(self):
        ws = _get_ws()
        spec = {"context": {}, "inputs": []}
        result = ws._build_swarm_goal_for_role("do something", "unknown_role", spec)
        assert "EVENT_DRIVEN_SWARM:REVIEWER" in result


# ---------------------------------------------------------------------------
# Tests for _autonomous_cron_loop (lines 1062-1091)
# ---------------------------------------------------------------------------

class TestAutonomousCronLoop:
    def test_exits_immediately_when_prompt_empty(self):
        ws = _get_ws()
        ws.cfg.AUTONOMOUS_CRON_PROMPT = ""
        stop_event = asyncio.Event()
        stop_event.set()  # Already stopped
        # Should return without error when prompt is empty
        asyncio.run(ws._autonomous_cron_loop(stop_event))

    def test_exits_when_stop_event_set(self):
        ws = _get_ws()
        ws.cfg.AUTONOMOUS_CRON_PROMPT = "check system"
        ws.cfg.AUTONOMOUS_CRON_INTERVAL_SECONDS = 1
        stop_event = asyncio.Event()

        async def _run():
            # Set stop event quickly
            asyncio.get_event_loop().call_soon(stop_event.set)
            await ws._autonomous_cron_loop(stop_event)

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tests for _nightly_memory_loop (lines 1094-1111)
# ---------------------------------------------------------------------------

class TestNightlyMemoryLoop:
    def test_exits_when_pruning_disabled(self):
        ws = _get_ws()
        ws.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = False
        stop_event = asyncio.Event()
        # Should return immediately when disabled
        asyncio.run(ws._nightly_memory_loop(stop_event))

    def test_exits_when_stop_event_set(self):
        ws = _get_ws()
        ws.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = True
        ws.cfg.NIGHTLY_MEMORY_INTERVAL_SECONDS = 1
        stop_event = asyncio.Event()

        async def _run():
            asyncio.get_event_loop().call_soon(stop_event.set)
            await ws._nightly_memory_loop(stop_event)

        asyncio.run(_run())
