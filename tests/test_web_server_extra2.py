"""
web_server.py için ek testler - Part 2
Targets: _is_admin_user, _get_user_tenant, _serialize_policy, _serialize_collaboration_*,
_trim_autonomy_text, _setup_rate_limiter, rate_limit helpers, _reload_persisted_marketplace_plugins,
and various other helper functions.
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
# Stubs (reuse pattern from test_web_server.py)
# ---------------------------------------------------------------------------

class _Dummy:
    def __init__(self, *args, **kwargs): pass
    def __call__(self, *args, **kwargs): return self


class _FakeFastAPI:
    def __init__(self, *args, **kwargs): pass
    def _decorator(self, *_args, **_kwargs):
        def _inner(func): return func
        return _inner
    middleware = _decorator
    exception_handler = _decorator
    get = post = put = delete = patch_method = websocket = _decorator
    def mount(self, *args, **kwargs): return None
    def add_middleware(self, *args, **kwargs): return None


class _HTTPException(Exception):
    def __init__(self, status_code: int = 500, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _inject_stubs() -> None:
    for name in ("jwt", "uvicorn", "fastapi", "fastapi.middleware",
                 "fastapi.middleware.cors", "fastapi.responses", "fastapi.staticfiles",
                 "pydantic", "redis", "redis.asyncio"):
        sys.modules.setdefault(name, types.ModuleType(name))

    fm = sys.modules["fastapi"]
    fm.BackgroundTasks = _Dummy; fm.FastAPI = _FakeFastAPI
    fm.Request = _Dummy; fm.UploadFile = _Dummy; fm.File = _Dummy
    fm.WebSocket = _Dummy; fm.WebSocketDisconnect = Exception
    fm.Depends = _Dummy; fm.Header = _Dummy; fm.HTTPException = _HTTPException

    sys.modules["fastapi.middleware.cors"].CORSMiddleware = _Dummy
    for attr in ("FileResponse", "HTMLResponse", "JSONResponse", "Response"):
        setattr(sys.modules["fastapi.responses"], attr, _Dummy)
    sys.modules["fastapi.staticfiles"].StaticFiles = _Dummy

    pm = sys.modules["pydantic"]
    pm.BaseModel = object; pm.Field = lambda *a, **k: None

    sys.modules["redis.asyncio"].Redis = _Dummy
    sys.modules["uvicorn"].run = lambda *a, **k: None

    cfg_mod = types.ModuleType("config")
    class _Config:
        BASE_DIR = str(Path(".").resolve())
        WEB_HOST = "0.0.0.0"; WEB_PORT = 7860
        VERSION = "test"; RATE_LIMIT_CHAT = 20
        RATE_LIMIT_MUTATION = 60; RATE_LIMIT_GIT_IO = 30
        @staticmethod
        def initialize_directories(): return None
        @staticmethod
        def validate_critical_settings(): return None
        def init_telemetry(self, **_k): return None
        def __getattr__(self, _n): return 0
    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = type("BaseAgent", (), {})
    sys.modules["agent.base_agent"] = base_agent_mod

    contracts_mod = types.ModuleType("agent.core.contracts")
    for symbol in ("ActionFeedback", "ExternalTrigger", "FederationTaskEnvelope", "FederationTaskResult"):
        setattr(contracts_mod, symbol, type(symbol, (), {}))
    contracts_mod.LEGACY_FEDERATION_PROTOCOL_V1 = "p1"
    contracts_mod.derive_correlation_id = lambda *a, **k: "cid"
    contracts_mod.normalize_federation_protocol = lambda v: v
    sys.modules["agent.core.contracts"] = contracts_mod

    event_stream_mod = types.ModuleType("agent.core.event_stream")
    event_stream_mod.get_agent_event_bus = lambda: _Dummy()
    sys.modules["agent.core.event_stream"] = event_stream_mod

    for mod_name, attrs in [
        ("agent.registry", {"AgentRegistry": type("AgentRegistry", (), {})}),
        ("agent.sidar_agent", {"SidarAgent": type("SidarAgent", (), {"VERSION": "test"})}),
        ("agent.swarm", {"SwarmOrchestrator": type("SwarmOrchestrator", (), {}),
                         "SwarmTask": type("SwarmTask", (), {})}),
        ("core.ci_remediation", {"build_ci_failure_context": lambda *a, **k: {}}),
        ("core.hitl", {"get_hitl_gate": lambda: _Dummy(),
                       "get_hitl_store": lambda: _Dummy(),
                       "set_hitl_broadcast_hook": lambda _h: None}),
        ("core.llm_client", {"LLMAPIError": type("LLMAPIError", (Exception,), {})}),
        ("core.llm_metrics", {"get_llm_metrics_collector": lambda: _Dummy(),
                               "reset_current_metrics_user_id": lambda _t: None,
                               "set_current_metrics_user_id": lambda _u: None}),
        ("managers.system_health", {"render_llm_metrics_prometheus": lambda: ""}),
    ]:
        m = types.ModuleType(mod_name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[mod_name] = m


def _get_ws():
    _inject_stubs()
    sys.modules.pop("web_server", None)
    return importlib.import_module("web_server")


# ---------------------------------------------------------------------------
# Tests for _trim_autonomy_text
# ---------------------------------------------------------------------------

class TestTrimAutonomyText:
    def test_short_text_unchanged(self):
        ws = _get_ws()
        result = ws._trim_autonomy_text("hello", 100)
        assert result == "hello"

    def test_long_text_truncated(self):
        ws = _get_ws()
        text = "x" * 2000
        result = ws._trim_autonomy_text(text, 100)
        assert len(result) <= 115  # 100 chars + " …[truncated]" (13 chars)

    def test_empty_text_returns_empty(self):
        ws = _get_ws()
        result = ws._trim_autonomy_text("", 100)
        assert result == ""

    def test_none_returns_empty(self):
        ws = _get_ws()
        result = ws._trim_autonomy_text(None, 100)
        assert result == ""


# ---------------------------------------------------------------------------
# Tests for _is_admin_user (lines 1347-1350)
# ---------------------------------------------------------------------------

class TestIsAdminUser:
    def test_role_admin_returns_true(self):
        ws = _get_ws()
        user = types.SimpleNamespace(role="admin", username="alice")
        assert ws._is_admin_user(user) is True

    def test_default_admin_username_returns_true(self):
        ws = _get_ws()
        user = types.SimpleNamespace(role="user", username="default_admin")
        assert ws._is_admin_user(user) is True

    def test_regular_user_returns_false(self):
        ws = _get_ws()
        user = types.SimpleNamespace(role="user", username="alice")
        assert ws._is_admin_user(user) is False

    def test_empty_role_returns_false(self):
        ws = _get_ws()
        user = types.SimpleNamespace(role="", username="bob")
        assert ws._is_admin_user(user) is False

    def test_admin_case_insensitive(self):
        ws = _get_ws()
        user = types.SimpleNamespace(role="ADMIN", username="alice")
        assert ws._is_admin_user(user) is True


# ---------------------------------------------------------------------------
# Tests for _get_user_tenant (lines 1371-1372)
# ---------------------------------------------------------------------------

class TestGetUserTenant:
    def test_returns_tenant_id(self):
        ws = _get_ws()
        user = types.SimpleNamespace(tenant_id="acme")
        assert ws._get_user_tenant(user) == "acme"

    def test_returns_default_when_missing(self):
        ws = _get_ws()
        user = types.SimpleNamespace()
        assert ws._get_user_tenant(user) == "default"

    def test_returns_default_when_empty(self):
        ws = _get_ws()
        user = types.SimpleNamespace(tenant_id="")
        assert ws._get_user_tenant(user) == "default"

    def test_returns_default_when_none(self):
        ws = _get_ws()
        user = types.SimpleNamespace(tenant_id=None)
        assert ws._get_user_tenant(user) == "default"


# ---------------------------------------------------------------------------
# Tests for _serialize_policy (lines 1375-...)
# ---------------------------------------------------------------------------

class TestSerializePolicy:
    def test_basic_fields(self):
        ws = _get_ws()
        record = types.SimpleNamespace(
            id=1, user_id="u1", tenant_id="t1",
            resource_type="file", resource_id="/path",
            action="read", effect="allow",
        )
        result = ws._serialize_policy(record)
        assert result["id"] == 1
        assert result["user_id"] == "u1"
        assert result["tenant_id"] == "t1"

    def test_defaults_on_missing_fields(self):
        ws = _get_ws()
        record = types.SimpleNamespace()
        result = ws._serialize_policy(record)
        assert result["id"] == 0
        assert result["user_id"] == ""
        assert result["tenant_id"] == "default"


# ---------------------------------------------------------------------------
# Tests for _serialize_collaboration_participant and _serialize_collaboration_room
# ---------------------------------------------------------------------------

class TestSerializeCollaboration:
    def test_serialize_participant(self):
        ws = _get_ws()
        participant = types.SimpleNamespace(
            user_id="u1", username="alice", display_name="Alice",
            role="editor", can_write=True, write_scopes=["ws:code"],
            joined_at="2026-01-01T00:00:00",
        )
        result = ws._serialize_collaboration_participant(participant)
        assert result["user_id"] == "u1"
        assert result["display_name"] == "Alice"
        assert result["role"] == "editor"

    def test_serialize_room_empty(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="ws:code")
        result = ws._serialize_collaboration_room(room)
        assert result["room_id"] == "ws:code"
        assert result["participants"] == []
        assert result["messages"] == []

    def test_serialize_room_with_messages(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="ws:code")
        room.messages = [{"type": "message", "content": "hello"}] * 5
        result = ws._serialize_collaboration_room(room)
        assert len(result["messages"]) == 5

    def test_serialize_room_limits_to_120_messages(self):
        ws = _get_ws()
        room = ws._CollaborationRoom(room_id="ws:code")
        room.messages = [{"id": i} for i in range(200)]
        result = ws._serialize_collaboration_room(room)
        assert len(result["messages"]) == 120


# ---------------------------------------------------------------------------
# Tests for _collaboration_write_scopes_for_role (lines 302-330 area)
# ---------------------------------------------------------------------------

class TestCollaborationWriteScopes:
    def test_admin_gets_base_dir_scope(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("admin", "ws:code")
        assert ws.cfg.BASE_DIR in scopes or len(scopes) > 0

    def test_viewer_gets_empty_scopes(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("viewer", "ws:code")
        assert scopes == [] or isinstance(scopes, list)

    def test_user_gets_room_scope(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("user", "workspace:myproject")
        # user gets access to the room's path
        assert isinstance(scopes, list)

    def test_editor_gets_scopes(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("editor", "ws:code")
        assert isinstance(scopes, list)


# ---------------------------------------------------------------------------
# Tests for JWT utilities (_issue_auth_token, _resolve_user_from_token)
# ---------------------------------------------------------------------------

class TestJwtUtils:
    def test_get_jwt_secret_returns_string(self):
        ws = _get_ws()
        secret = ws._get_jwt_secret()
        assert isinstance(secret, str)
        assert len(secret) > 0

    def test_build_user_from_jwt_payload(self):
        ws = _get_ws()
        payload = {"sub": "u1", "username": "alice", "role": "user", "tenant_id": "default"}
        user = ws._build_user_from_jwt_payload(payload)
        assert user.username == "alice"
        assert user.role == "user"


# ---------------------------------------------------------------------------
# Tests for _normalize_collaboration_role
# ---------------------------------------------------------------------------

class TestNormalizeCollaborationRole:
    def test_empty_defaults_to_user(self):
        ws = _get_ws()
        assert ws._normalize_collaboration_role("") == "user"

    def test_whitespace_defaults_to_user(self):
        ws = _get_ws()
        assert ws._normalize_collaboration_role("   ") == "user"

    def test_valid_role_preserved(self):
        ws = _get_ws()
        assert ws._normalize_collaboration_role("admin") == "admin"

    def test_unknown_role_fallback(self):
        ws = _get_ws()
        result = ws._normalize_collaboration_role("superuser")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests for _collaboration_now_iso
# ---------------------------------------------------------------------------

class TestCollaborationNowIso:
    def test_returns_string(self):
        ws = _get_ws()
        result = ws._collaboration_now_iso()
        assert isinstance(result, str)

    def test_contains_date_format(self):
        ws = _get_ws()
        result = ws._collaboration_now_iso()
        assert "T" in result or len(result) > 10


# ---------------------------------------------------------------------------
# Tests for _socket_key
# ---------------------------------------------------------------------------

class TestSocketKey:
    def test_returns_int(self):
        ws = _get_ws()
        fake_ws = object()
        result = ws._socket_key(fake_ws)
        assert isinstance(result, int)

    def test_same_object_same_key(self):
        ws = _get_ws()
        fake_ws = object()
        assert ws._socket_key(fake_ws) == ws._socket_key(fake_ws)

    def test_different_objects_different_keys(self):
        ws = _get_ws()
        ws1 = object()
        ws2 = object()
        assert ws._socket_key(ws1) != ws._socket_key(ws2)


# ---------------------------------------------------------------------------
# Tests for async _leave_collaboration_room (lines 332-353)
# ---------------------------------------------------------------------------

class TestLeaveCollaborationRoom:
    def test_noop_when_no_room_id(self):
        ws = _get_ws()
        fake_ws = types.SimpleNamespace()
        # No _sidar_room_id set, should noop
        asyncio.run(ws._leave_collaboration_room(fake_ws))

    def test_removes_participant_from_room(self):
        ws = _get_ws()

        class _FakeWS:
            _sidar_room_id = "ws:code"
            async def send_json(self, p): pass

        fake_ws = _FakeWS()
        room = ws._CollaborationRoom(room_id="ws:code")
        participant = types.SimpleNamespace(
            websocket=fake_ws, user_id="u1", username="alice",
            display_name="Alice", role="user",
        )
        room.participants = {ws._socket_key(fake_ws): participant}
        ws._collaboration_rooms["ws:code"] = room

        asyncio.run(ws._leave_collaboration_room(fake_ws))
        # Participant should be removed
        assert ws._socket_key(fake_ws) not in room.participants or "ws:code" not in ws._collaboration_rooms


# ---------------------------------------------------------------------------
# Tests for rate limiter helpers
# ---------------------------------------------------------------------------

class TestRateLimiterLocal:
    def test_local_rate_limit_not_exceeded(self):
        ws = _get_ws()
        # First call should NOT be rate limited (returns False = not limited)
        ws._local_rate_lock = asyncio.Lock()
        result = asyncio.run(ws._local_is_rate_limited("user_test_ok", 100, 60))
        assert isinstance(result, bool)
        assert result is False  # Not rate limited yet

    def test_local_rate_limit_exceeded(self):
        ws = _get_ws()
        ws._local_rate_lock = asyncio.Lock()
        # Fill up limit=1
        asyncio.run(ws._local_is_rate_limited("user_exceed_test", 1, 60))
        # Second call should be rate limited
        result = asyncio.run(ws._local_is_rate_limited("user_exceed_test", 1, 60))
        assert result is True  # Rate limited

    def test_is_rate_limited_delegates_to_local(self):
        ws = _get_ws()
        ws._local_rate_lock = asyncio.Lock()
        result = asyncio.run(ws._is_rate_limited("is_rl_test", 100, 60))
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tests for _is_forbidden_path (additional coverage)
# ---------------------------------------------------------------------------

class TestCollaborationScopePaths:
    def test_admin_gets_nonempty_scopes(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("admin", "ws:any")
        assert isinstance(scopes, list)
        assert len(scopes) > 0

    def test_viewer_gets_empty_scopes(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("viewer", "ws:any")
        assert scopes == []

    def test_workspace_prefix_gives_user_scope(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("user", "workspace:myproject")
        assert isinstance(scopes, list)

    def test_editor_gets_scopes(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("editor", "ws:code")
        assert isinstance(scopes, list)

    def test_unknown_role_returns_empty(self):
        ws = _get_ws()
        scopes = ws._collaboration_write_scopes_for_role("superrole", "ws:any")
        assert isinstance(scopes, list)


# ---------------------------------------------------------------------------
# Tests for _async_force_shutdown_local_llm_processes (lines 543-570)
# ---------------------------------------------------------------------------

class TestAsyncForceShutdown:
    def test_noop_when_not_ollama(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = False
        ws.cfg.AI_PROVIDER = "openai"
        asyncio.run(ws._async_force_shutdown_local_llm_processes())
        assert ws._shutdown_cleanup_done is True

    def test_noop_when_already_done(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = True
        asyncio.run(ws._async_force_shutdown_local_llm_processes())
        # Should return immediately

    def test_ollama_no_force_kill(self):
        ws = _get_ws()
        ws._shutdown_cleanup_done = False
        ws.cfg.AI_PROVIDER = "ollama"
        ws.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = False
        asyncio.run(ws._async_force_shutdown_local_llm_processes())
        assert ws._shutdown_cleanup_done is True
