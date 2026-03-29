"""web_server.py için birim testleri (ağır bağımlılıklar stub'lanarak)."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest


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
    """web_server import'u için gerekli dış/iç bağımlılıkları minimal stub'larla enjekte eder."""
    # Dış bağımlılıklar
    for name in (
        "jwt",
        "uvicorn",
        "fastapi",
        "fastapi.middleware",
        "fastapi.middleware.cors",
        "fastapi.responses",
        "fastapi.staticfiles",
        "pydantic",
        "redis",
        "redis.asyncio",
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

    # İç bağımlılıklar
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
    for symbol in (
        "ActionFeedback",
        "ExternalTrigger",
        "FederationTaskEnvelope",
        "FederationTaskResult",
    ):
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


def _get_web_server():
    _inject_web_server_stubs()
    sys.modules.pop("web_server", None)
    return importlib.import_module("web_server")


class TestRoomNormalization:
    def test_empty_room_id_uses_default(self):
        ws = _get_web_server()
        assert ws._normalize_room_id("   ") == "workspace:default"

    def test_invalid_room_id_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._normalize_room_id("bad room id")
        assert exc_info.value.status_code == 400


class TestRoleAndScope:
    def test_normalize_role_empty_to_user(self):
        ws = _get_web_server()
        assert ws._normalize_collaboration_role("  ") == "user"

    def test_admin_scope_is_base_dir(self):
        ws = _get_web_server()
        scopes = ws._collaboration_write_scopes_for_role("admin", "workspace:team")
        assert scopes == [str(Path(".").resolve())]

    def test_developer_scope_is_workspace_subdir(self):
        ws = _get_web_server()
        scopes = ws._collaboration_write_scopes_for_role("developer", "workspace:team")
        assert scopes == [str(Path(".").resolve() / "workspaces" / "workspace/team")]

    def test_user_has_no_write_scope(self):
        ws = _get_web_server()
        assert ws._collaboration_write_scopes_for_role("user", "workspace:team") == []


class TestCommandIntent:
    def test_write_intent_english_detected(self):
        ws = _get_web_server()
        assert ws._collaboration_command_requires_write("please edit this file") is True

    def test_write_intent_turkish_detected(self):
        ws = _get_web_server()
        assert ws._collaboration_command_requires_write("bu dosyayı düzenle") is True

    def test_read_only_command_not_detected(self):
        ws = _get_web_server()
        assert ws._collaboration_command_requires_write("durumu özetle") is False


class TestRoomBuffers:
    def test_append_room_message_applies_limit(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        for i in range(5):
            ws._append_room_message(room, {"id": str(i)}, limit=3)
        assert [item["id"] for item in room.messages] == ["2", "3", "4"]

    def test_append_room_telemetry_masks_sensitive_fields(self, monkeypatch):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        monkeypatch.setattr(ws, "_mask_collaboration_text", lambda text: f"MASKED:{text}")

        ws._append_room_telemetry(
            room,
            {"type": "tool", "content": "token=abc", "error": "secret"},
            limit=5,
        )

        assert room.telemetry[0]["content"] == "MASKED:token=abc"
        assert room.telemetry[0]["error"] == "MASKED:secret"


class TestMessageHelpers:
    def test_build_room_message_uses_mask_and_metadata(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "_mask_collaboration_text", lambda text: text.upper())
        monkeypatch.setattr(ws, "_collaboration_now_iso", lambda: "2026-03-28T00:00:00+00:00")
        monkeypatch.setattr(ws.secrets, "token_hex", lambda _n: "deadbeef")

        payload = ws._build_room_message(
            room_id="workspace:default",
            role="user",
            content="merhaba",
            author_name="Ali",
            author_id="u1",
            kind="message",
            request_id="r1",
        )

        assert payload["id"] == "deadbeef"
        assert payload["content"] == "MERHABA"
        assert payload["ts"] == "2026-03-28T00:00:00+00:00"
        assert payload["author_name"] == "Ali"

    def test_iter_stream_chunks_splits_text(self):
        ws = _get_web_server()
        chunks = ws._iter_stream_chunks("abcdefghij", size=4)
        assert chunks == ["abcd", "efgh", "ij"]

    def test_iter_stream_chunks_empty_returns_empty_list(self):
        ws = _get_web_server()
        assert ws._iter_stream_chunks("", size=4) == []


class TestMentionHelpers:
    def test_is_sidar_mention_detects_case_insensitive(self):
        ws = _get_web_server()
        assert ws._is_sidar_mention("Merhaba @SiDaR nasılsın?") is True

    def test_strip_sidar_mention_removes_first_mention(self):
        ws = _get_web_server()
        assert ws._strip_sidar_mention("@sidar bunu yap") == "bunu yap"


class TestPromptBuilder:
    def test_build_collaboration_prompt_includes_participants_and_command(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")

        ws1 = types.SimpleNamespace()
        participant = ws._CollaborationParticipant(
            websocket=ws1,
            user_id="u1",
            username="ali",
            display_name="Ali",
            role="developer",
            can_write=True,
            write_scopes=["/repo/workspaces/workspace/default"],
            joined_at="2026-03-28T00:00:00+00:00",
        )
        room.participants[1] = participant
        room.messages.append(
            {
                "role": "user",
                "author_name": "Ali",
                "content": "önceki mesaj",
            }
        )

        prompt = ws._build_collaboration_prompt(room, actor_name="Ali", command="testleri çalıştır")

        assert "participants=Ali<developer>" in prompt
        assert "requesting_write_scopes=/repo/workspaces/workspace/default" in prompt
        assert "Current command:\ntestleri çalıştır" in prompt


class TestSocketKey:
    def test_returns_id_of_object(self):
        ws = _get_web_server()
        obj = object()
        assert ws._socket_key(obj) == id(obj)

    def test_different_objects_have_different_keys(self):
        ws = _get_web_server()
        a, b = object(), object()
        assert ws._socket_key(a) != ws._socket_key(b)


class TestCollaborationNowIso:
    def test_returns_string(self):
        ws = _get_web_server()
        result = ws._collaboration_now_iso()
        assert isinstance(result, str)

    def test_contains_utc_offset(self):
        ws = _get_web_server()
        result = ws._collaboration_now_iso()
        assert "+" in result or result.endswith("Z")


class TestSerializeCollaborationParticipant:
    def test_all_fields_present(self):
        ws = _get_web_server()
        stub_ws = types.SimpleNamespace()
        p = ws._CollaborationParticipant(
            websocket=stub_ws,
            user_id="u42",
            username="zeynep",
            display_name="Zeynep K.",
            role="admin",
            can_write=True,
            write_scopes=["/repo"],
            joined_at="2026-03-28T00:00:00+00:00",
        )
        result = ws._serialize_collaboration_participant(p)
        assert result["user_id"] == "u42"
        assert result["username"] == "zeynep"
        assert result["display_name"] == "Zeynep K."
        assert result["role"] == "admin"
        assert result["can_write"] == "true"
        assert result["write_scopes"] == ["/repo"]

    def test_can_write_false_serialized_as_string(self):
        ws = _get_web_server()
        stub_ws = types.SimpleNamespace()
        p = ws._CollaborationParticipant(
            websocket=stub_ws,
            user_id="u1",
            username="ali",
            display_name="Ali",
            role="user",
            can_write=False,
            write_scopes=[],
            joined_at="2026-03-28T00:00:00+00:00",
        )
        result = ws._serialize_collaboration_participant(p)
        assert result["can_write"] == "false"


class TestSerializeCollaborationRoom:
    def test_shape_has_required_keys(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        result = ws._serialize_collaboration_room(room)
        assert "room_id" in result
        assert "participants" in result
        assert "messages" in result
        assert "telemetry" in result

    def test_room_id_matches(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:qa")
        result = ws._serialize_collaboration_room(room)
        assert result["room_id"] == "workspace:qa"

    def test_messages_limited_to_120(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        room.messages = [{"id": str(i)} for i in range(200)]
        result = ws._serialize_collaboration_room(room)
        assert len(result["messages"]) == 120


class TestMaskCollaborationText:
    def test_returns_string_when_dlp_unavailable(self):
        ws = _get_web_server()
        import sys
        sys.modules.pop("core.dlp", None)
        result = ws._mask_collaboration_text("merhaba dünya")
        assert isinstance(result, str)
        assert "merhaba" in result

    def test_empty_string_returns_empty(self):
        ws = _get_web_server()
        assert ws._mask_collaboration_text("") == ""

    def test_none_converted_to_empty(self):
        ws = _get_web_server()
        result = ws._mask_collaboration_text(None)
        assert isinstance(result, str)


class TestNormalizeCollaborationRoleExtended:
    def test_valid_role_returned_as_is(self):
        ws = _get_web_server()
        assert ws._normalize_collaboration_role("admin") == "admin"

    def test_uppercase_role_lowercased(self):
        ws = _get_web_server()
        assert ws._normalize_collaboration_role("DEVELOPER") == "developer"

    def test_whitespace_only_becomes_user(self):
        ws = _get_web_server()
        assert ws._normalize_collaboration_role("   ") == "user"

    def test_maintainer_role_preserved(self):
        ws = _get_web_server()
        assert ws._normalize_collaboration_role("maintainer") == "maintainer"


class TestCollaborationWriteScopesExtended:
    def test_maintainer_scope_is_workspace_subdir(self):
        ws = _get_web_server()
        scopes = ws._collaboration_write_scopes_for_role("maintainer", "workspace:team")
        assert len(scopes) == 1
        assert "workspace" in scopes[0]

    def test_editor_scope_is_workspace_subdir(self):
        ws = _get_web_server()
        scopes = ws._collaboration_write_scopes_for_role("editor", "workspace:docs")
        assert len(scopes) == 1
        assert "workspace" in scopes[0]

    def test_guest_has_no_write_scope(self):
        ws = _get_web_server()
        assert ws._collaboration_write_scopes_for_role("guest", "workspace:x") == []


class TestTrimAutonomyText:
    def test_short_text_returned_unchanged(self):
        ws = _get_web_server()
        assert ws._trim_autonomy_text("kısa metin", 1200) == "kısa metin"

    def test_long_text_truncated_with_marker(self):
        ws = _get_web_server()
        long_text = "a" * 2000
        result = ws._trim_autonomy_text(long_text, 1200)
        assert result.endswith("…[truncated]")
        assert len(result) < 2000

    def test_empty_string_returns_empty(self):
        ws = _get_web_server()
        assert ws._trim_autonomy_text("") == ""

    def test_none_returns_empty(self):
        ws = _get_web_server()
        assert ws._trim_autonomy_text(None) == ""

    def test_exactly_at_limit_not_truncated(self):
        ws = _get_web_server()
        text = "x" * 1200
        result = ws._trim_autonomy_text(text, 1200)
        assert not result.endswith("…[truncated]")


class TestBuildAuditResource:
    def test_formats_resource_correctly(self):
        ws = _get_web_server()
        assert ws._build_audit_resource("rag", "doc-123") == "rag:doc-123"

    def test_empty_resource_id_becomes_wildcard(self):
        ws = _get_web_server()
        assert ws._build_audit_resource("github", "") == "github:*"

    def test_empty_resource_type_returns_empty(self):
        ws = _get_web_server()
        assert ws._build_audit_resource("", "some-id") == ""

    def test_resource_type_lowercased(self):
        ws = _get_web_server()
        assert ws._build_audit_resource("RAG", "doc-1") == "rag:doc-1"


class TestBuildUserFromJwtPayload:
    def test_valid_payload_returns_user(self):
        ws = _get_web_server()
        payload = {"sub": "u1", "username": "ali", "role": "admin", "tenant_id": "acme"}
        user = ws._build_user_from_jwt_payload(payload)
        assert user is not None
        assert user.id == "u1"
        assert user.username == "ali"
        assert user.role == "admin"
        assert user.tenant_id == "acme"

    def test_missing_sub_returns_none(self):
        ws = _get_web_server()
        payload = {"username": "ali", "role": "user"}
        assert ws._build_user_from_jwt_payload(payload) is None

    def test_missing_username_returns_none(self):
        ws = _get_web_server()
        payload = {"sub": "u1", "role": "user"}
        assert ws._build_user_from_jwt_payload(payload) is None

    def test_missing_role_defaults_to_user(self):
        ws = _get_web_server()
        payload = {"sub": "u1", "username": "ali"}
        user = ws._build_user_from_jwt_payload(payload)
        assert user is not None
        assert user.role == "user"

    def test_missing_tenant_id_defaults_to_default(self):
        ws = _get_web_server()
        payload = {"sub": "u1", "username": "ali"}
        user = ws._build_user_from_jwt_payload(payload)
        assert user is not None
        assert user.tenant_id == "default"


class TestGetJwtSecret:
    def test_returns_string(self):
        ws = _get_web_server()
        result = ws._get_jwt_secret()
        assert isinstance(result, str) and len(result) > 0

    def test_fallback_when_key_not_configured(self):
        ws = _get_web_server()
        import types as _types
        old_cfg = ws.cfg
        fake_cfg = _types.SimpleNamespace()
        ws.cfg = fake_cfg
        try:
            result = ws._get_jwt_secret()
            assert result == "sidar-dev-secret"
        finally:
            ws.cfg = old_cfg


class TestIsAdminUser:
    def test_admin_role_returns_true(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(role="admin", username="ali")
        assert ws._is_admin_user(user) is True

    def test_default_admin_username_returns_true(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(role="user", username="default_admin")
        assert ws._is_admin_user(user) is True

    def test_regular_user_returns_false(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(role="user", username="zeynep")
        assert ws._is_admin_user(user) is False

    def test_uppercase_admin_role_detected(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(role="ADMIN", username="ali")
        assert ws._is_admin_user(user) is True


class TestGetUserTenant:
    def test_returns_tenant_id_from_user(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(tenant_id="acme")
        assert ws._get_user_tenant(user) == "acme"

    def test_missing_tenant_id_defaults_to_default(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace()
        assert ws._get_user_tenant(user) == "default"

    def test_empty_tenant_id_defaults_to_default(self):
        ws = _get_web_server()
        import types as _types
        user = _types.SimpleNamespace(tenant_id="")
        assert ws._get_user_tenant(user) == "default"


class TestValidatePluginRoleName:
    def test_valid_role_name_returned_lowercased(self):
        ws = _get_web_server()
        assert ws._validate_plugin_role_name("MyAgent") == "myagent"

    def test_valid_role_with_hyphen(self):
        ws = _get_web_server()
        assert ws._validate_plugin_role_name("aws-ops") == "aws-ops"

    def test_invalid_role_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._validate_plugin_role_name("a b c")
        assert exc_info.value.status_code == 400

    def test_too_short_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._validate_plugin_role_name("x")
        assert exc_info.value.status_code == 400

    def test_empty_string_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException):
            ws._validate_plugin_role_name("")


class TestSanitizeCapabilities:
    def test_normal_list_returned(self):
        ws = _get_web_server()
        assert ws._sanitize_capabilities(["read", "write"]) == ["read", "write"]

    def test_none_returns_empty_list(self):
        ws = _get_web_server()
        assert ws._sanitize_capabilities(None) == []

    def test_empty_list_returns_empty_list(self):
        ws = _get_web_server()
        assert ws._sanitize_capabilities([]) == []

    def test_empty_strings_filtered_out(self):
        ws = _get_web_server()
        assert ws._sanitize_capabilities(["read", "", "  ", "write"]) == ["read", "write"]

    def test_whitespace_stripped(self):
        ws = _get_web_server()
        assert ws._sanitize_capabilities(["  admin  "]) == ["admin"]


class TestPluginSourceFilename:
    def test_normal_label_wrapped(self):
        ws = _get_web_server()
        result = ws._plugin_source_filename("my_plugin")
        assert result == "<sidar-plugin:my_plugin>"

    def test_special_chars_replaced_with_underscore(self):
        ws = _get_web_server()
        result = ws._plugin_source_filename("my plugin/v2")
        assert " " not in result
        assert "/" not in result

    def test_empty_label_defaults_to_plugin(self):
        ws = _get_web_server()
        result = ws._plugin_source_filename("")
        assert result == "<sidar-plugin:plugin>"


class TestFallbackCiFailureContext:
    def test_ci_failure_flag_triggers_context(self):
        ws = _get_web_server()
        payload = {"ci_failure": True, "repo": "org/repo", "branch": "main"}
        result = ws._fallback_ci_failure_context("check_run", payload)
        assert result is not None
        assert result["kind"] == "generic_ci_failure"
        assert result["repo"] == "org/repo"
        assert result["branch"] == "main"

    def test_pipeline_failed_flag_triggers_context(self):
        ws = _get_web_server()
        payload = {"pipeline_failed": True}
        result = ws._fallback_ci_failure_context("push", payload)
        assert result is not None
        assert result["kind"] == "generic_ci_failure"

    def test_ci_failure_event_name_triggers_context(self):
        ws = _get_web_server()
        result = ws._fallback_ci_failure_context("ci_failure_remediation", {})
        assert result is not None

    def test_unrelated_event_returns_empty_dict(self):
        ws = _get_web_server()
        result = ws._fallback_ci_failure_context("push", {"action": "opened"})
        assert result == {}

    def test_conclusion_defaults_to_failure(self):
        ws = _get_web_server()
        result = ws._fallback_ci_failure_context("ci_pipeline_failed", {})
        assert result["conclusion"] == "failure"


class TestBuildSwarmGoalForRole:
    def test_coder_role_includes_coder_marker(self):
        ws = _get_web_server()
        spec = {"context": {"issue_key": "PROJ-1"}, "inputs": ["key=value"]}
        result = ws._build_swarm_goal_for_role("temel hedef", "coder", spec)
        assert "EVENT_DRIVEN_SWARM:CODER" in result
        assert "temel hedef" in result

    def test_reviewer_role_includes_reviewer_marker(self):
        ws = _get_web_server()
        spec = {"context": {}, "inputs": []}
        result = ws._build_swarm_goal_for_role("temel hedef", "reviewer", spec)
        assert "EVENT_DRIVEN_SWARM:REVIEWER" in result

    def test_unknown_role_uses_reviewer_template(self):
        ws = _get_web_server()
        spec = {"context": {}, "inputs": []}
        result = ws._build_swarm_goal_for_role("hedef", "unknown", spec)
        assert "EVENT_DRIVEN_SWARM:REVIEWER" in result


class TestBuildEventDrivenFederationSpec:
    def test_jira_issue_created_returns_spec(self):
        ws = _get_web_server()
        payload = {
            "action": "created",
            "issue": {"key": "PROJ-42", "summary": "Bug fix needed"},
        }
        result = ws._build_event_driven_federation_spec("jira", "issue_created", payload)
        assert result is not None
        assert result["workflow_type"] == "jira_issue"
        assert "proj-42" in result["task_id"]

    def test_github_pr_opened_returns_spec(self):
        ws = _get_web_server()
        payload = {
            "action": "opened",
            "pull_request": {"number": 7, "title": "feat: new feature"},
            "repository": {"full_name": "org/repo"},
        }
        result = ws._build_event_driven_federation_spec("github", "pull_request", payload)
        assert result is not None
        assert result["workflow_type"] == "github_pull_request"
        assert "7" in result["task_id"]

    def test_system_monitor_critical_returns_spec(self):
        ws = _get_web_server()
        payload = {
            "severity": "critical",
            "alert_name": "DB Connection Pool Exhausted",
        }
        result = ws._build_event_driven_federation_spec("system_monitor", "monitor_alert", payload)
        assert result is not None
        assert result["workflow_type"] == "system_error"

    def test_unknown_source_returns_none(self):
        ws = _get_web_server()
        result = ws._build_event_driven_federation_spec("slack", "message", {})
        assert result is None

    def test_jira_without_issue_key_returns_none(self):
        ws = _get_web_server()
        payload = {"action": "created", "issue": {}}
        result = ws._build_event_driven_federation_spec("jira", "issue_created", payload)
        assert result is None

    def test_github_pr_closed_action_returns_none(self):
        ws = _get_web_server()
        payload = {
            "action": "closed",
            "pull_request": {"number": 7, "title": "feat"},
        }
        result = ws._build_event_driven_federation_spec("github", "pull_request", payload)
        assert result is None


class TestResolveCiFailureContext:
    def test_returns_build_ci_failure_context_when_non_empty(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "build_ci_failure_context", lambda e, p: {"kind": "check_run", "repo": "org/repo"})
        result = ws._resolve_ci_failure_context("check_run", {"ci_failure": True})
        assert result["kind"] == "check_run"

    def test_falls_back_when_build_ci_returns_empty(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "build_ci_failure_context", lambda e, p: {})
        result = ws._resolve_ci_failure_context("ci_failure_remediation", {})
        assert result is not None

    def test_returns_empty_dict_for_unrelated_event(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "build_ci_failure_context", lambda e, p: {})
        result = ws._resolve_ci_failure_context("push", {"action": "opened"})
        assert result == {}


class TestEmbedEventDrivenFederationPayload:
    def test_keys_present_in_result(self):
        ws = _get_web_server()
        base = {"event": "ci_failure"}
        workflow = {
            "federation_task": {"task_id": "t1", "source_system": "github", "source_agent": "pr_webhook", "target_agent": "supervisor"},
            "federation_prompt": "inceleme yap",
            "correlation_id": "corr-123",
        }
        result = ws._embed_event_driven_federation_payload(base, workflow)
        assert result["kind"] == "federation_task"
        assert result["federation_prompt"] == "inceleme yap"
        assert result["task_id"] == "t1"
        assert result["source_system"] == "github"
        assert result["correlation_id"] == "corr-123"

    def test_empty_workflow_returns_safe_defaults(self):
        ws = _get_web_server()
        result = ws._embed_event_driven_federation_payload({}, {})
        assert result["kind"] == "federation_task"
        assert result["task_id"] == ""
        assert result["source_system"] == ""
        assert result["correlation_id"] == ""


class TestSerializePolicy:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=1,
            user_id="u1",
            tenant_id="acme",
            resource_type="rag",
            resource_id="doc-1",
            action="read",
            effect="allow",
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        result = ws._serialize_policy(record)
        assert result["id"] == 1
        assert result["user_id"] == "u1"
        assert result["tenant_id"] == "acme"
        assert result["resource_type"] == "rag"
        assert result["resource_id"] == "doc-1"
        assert result["action"] == "read"
        assert result["effect"] == "allow"

    def test_missing_fields_use_defaults(self):
        ws = _get_web_server()
        record = types.SimpleNamespace()
        result = ws._serialize_policy(record)
        assert result["id"] == 0
        assert result["tenant_id"] == "default"
        assert result["effect"] == "allow"


class TestSerializePrompt:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=42,
            role_name="system",
            prompt_text="Sen yararlı bir asistansın.",
            version=3,
            is_active=True,
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        result = ws._serialize_prompt(record)
        assert result["id"] == 42
        assert result["role_name"] == "system"
        assert result["prompt_text"] == "Sen yararlı bir asistansın."
        assert result["version"] == 3
        assert result["is_active"] is True


class TestSerializeSwarmResult:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            task_id="t1",
            agent_role="coder",
            status="completed",
            summary="Kod yazıldı.",
            elapsed_ms=1500,
            evidence=["e1"],
            handoffs=["h1"],
            graph={"nodes": []},
        )
        result = ws._serialize_swarm_result(record)
        assert result["task_id"] == "t1"
        assert result["agent_role"] == "coder"
        assert result["status"] == "completed"
        assert result["elapsed_ms"] == 1500

    def test_missing_fields_use_defaults(self):
        ws = _get_web_server()
        record = types.SimpleNamespace()
        result = ws._serialize_swarm_result(record)
        assert result["task_id"] == ""
        assert result["elapsed_ms"] == 0
        assert result["evidence"] == []
        assert result["graph"] == {}


class TestSerializeCampaign:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=10,
            tenant_id="acme",
            name="Kampanya 1",
            channel="email",
            objective="Satış artırma",
            status="active",
            owner_user_id="u1",
            budget=5000.0,
            metadata_json='{"key": "val"}',
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        result = ws._serialize_campaign(record)
        assert result["id"] == 10
        assert result["name"] == "Kampanya 1"
        assert result["budget"] == 5000.0
        assert result["status"] == "active"

    def test_defaults_when_fields_missing(self):
        ws = _get_web_server()
        record = types.SimpleNamespace()
        result = ws._serialize_campaign(record)
        assert result["id"] == 0
        assert result["tenant_id"] == "default"
        assert result["status"] == "draft"


class TestSerializeContentAsset:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=5,
            campaign_id=10,
            tenant_id="acme",
            asset_type="image",
            title="Banner",
            content="<img>",
            channel="social",
            metadata_json="{}",
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        result = ws._serialize_content_asset(record)
        assert result["id"] == 5
        assert result["asset_type"] == "image"
        assert result["title"] == "Banner"

    def test_defaults_when_fields_missing(self):
        ws = _get_web_server()
        record = types.SimpleNamespace()
        result = ws._serialize_content_asset(record)
        assert result["id"] == 0
        assert result["tenant_id"] == "default"


class TestSerializeOperationChecklist:
    def test_all_fields_serialized(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=3,
            campaign_id=7,
            tenant_id="acme",
            title="Checklist 1",
            items_json='["item1"]',
            status="in_progress",
            owner_user_id="u2",
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        result = ws._serialize_operation_checklist(record)
        assert result["id"] == 3
        assert result["campaign_id"] == 7
        assert result["status"] == "in_progress"

    def test_none_campaign_id_serialized_as_none(self):
        ws = _get_web_server()
        record = types.SimpleNamespace(
            id=1,
            campaign_id=None,
            tenant_id="default",
            title="T",
            items_json="[]",
            status="pending",
            owner_user_id="",
            created_at="",
            updated_at="",
        )
        result = ws._serialize_operation_checklist(record)
        assert result["campaign_id"] is None

    def test_defaults_when_fields_missing(self):
        ws = _get_web_server()
        record = types.SimpleNamespace()
        result = ws._serialize_operation_checklist(record)
        assert result["id"] == 0
        assert result["tenant_id"] == "default"
        assert result["status"] == "pending"


class TestGetRequestUser:
    def test_returns_user_when_present(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(id="u1", username="ali", role="user")
        request = types.SimpleNamespace(state=types.SimpleNamespace(user=user))
        result = ws._get_request_user(request)
        assert result.id == "u1"

    def test_raises_401_when_no_user(self):
        ws = _get_web_server()
        request = types.SimpleNamespace(state=types.SimpleNamespace())
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._get_request_user(request)
        assert exc_info.value.status_code == 401


class TestRequireAdminUser:
    def test_admin_user_passes(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(role="admin", username="ali")
        result = ws._require_admin_user(user=user)
        assert result.role == "admin"

    def test_non_admin_raises_403(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(role="user", username="zeynep")
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._require_admin_user(user=user)
        assert exc_info.value.status_code == 403


class TestRequireMetricsAccess:
    def test_admin_user_allowed(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(role="admin", username="ali")
        request = types.SimpleNamespace(headers={"Authorization": ""})
        result = ws._require_metrics_access(request=request, user=user)
        assert result.role == "admin"

    def test_metrics_token_allows_non_admin(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "METRICS_TOKEN", "supersecret", raising=False)
        user = types.SimpleNamespace(role="user", username="ali")
        request = types.SimpleNamespace(headers={"Authorization": "Bearer supersecret"})
        result = ws._require_metrics_access(request=request, user=user)
        assert result.role == "user"

    def test_non_admin_without_token_raises_403(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "METRICS_TOKEN", "", raising=False)
        user = types.SimpleNamespace(role="user", username="zeynep")
        request = types.SimpleNamespace(headers={"Authorization": ""})
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._require_metrics_access(request=request, user=user)
        assert exc_info.value.status_code == 403


class TestSetupTracing:
    def test_calls_cfg_init_telemetry_when_available(self, monkeypatch):
        ws = _get_web_server()
        called_with = {}

        def fake_init_telemetry(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr(ws.cfg, "init_telemetry", fake_init_telemetry, raising=False)
        ws._setup_tracing()
        assert "service_name" in called_with

    def test_returns_early_when_tracing_disabled(self, monkeypatch):
        ws = _get_web_server()
        # init_telemetry içermeyen sahte bir cfg nesnesi kullan
        fake_cfg = types.SimpleNamespace(ENABLE_TRACING=False)
        monkeypatch.setattr(ws, "cfg", fake_cfg)
        # exception olmadan tamamlanmalı
        ws._setup_tracing()


class TestRegisterExceptionHandlers:
    def test_does_not_raise_for_app_with_handler(self):
        ws = _get_web_server()
        ws._register_exception_handlers(ws.app)  # tekrar çağrılabilmeli

    def test_skips_app_without_exception_handler_attr(self):
        ws = _get_web_server()
        fake_app = types.SimpleNamespace()
        # AttributeError fırlatmamalı
        ws._register_exception_handlers(fake_app)


class TestResolvePolicyFromRequest:
    def _make_request(self, path, method="GET"):
        url = types.SimpleNamespace(path=path)
        return types.SimpleNamespace(url=url, method=method)

    def test_rag_get_returns_read(self):
        ws = _get_web_server()
        req = self._make_request("/rag/docs", "GET")
        r_type, action, _ = ws._resolve_policy_from_request(req)
        assert r_type == "rag"
        assert action == "read"

    def test_rag_post_returns_write(self):
        ws = _get_web_server()
        req = self._make_request("/rag/docs", "POST")
        r_type, action, _ = ws._resolve_policy_from_request(req)
        assert r_type == "rag"
        assert action == "write"

    def test_rag_delete_returns_resource_id(self):
        ws = _get_web_server()
        req = self._make_request("/rag/doc-123", "DELETE")
        r_type, action, resource_id = ws._resolve_policy_from_request(req)
        assert r_type == "rag"
        assert resource_id == "doc-123"

    def test_github_path_returns_github_resource(self):
        ws = _get_web_server()
        req = self._make_request("/github-repos", "GET")
        r_type, action, _ = ws._resolve_policy_from_request(req)
        assert r_type == "github"

    def test_set_repo_returns_github_resource(self):
        ws = _get_web_server()
        req = self._make_request("/set-repo", "POST")
        r_type, _, _ = ws._resolve_policy_from_request(req)
        assert r_type == "github"

    def test_agents_register_path(self):
        ws = _get_web_server()
        req = self._make_request("/api/agents/register", "POST")
        r_type, action, _ = ws._resolve_policy_from_request(req)
        assert r_type == "agents"
        assert action == "register"

    def test_swarm_path_returns_swarm(self):
        ws = _get_web_server()
        req = self._make_request("/api/swarm/execute", "POST")
        r_type, _, _ = ws._resolve_policy_from_request(req)
        assert r_type == "swarm"

    def test_admin_path_returns_admin(self):
        ws = _get_web_server()
        req = self._make_request("/admin/prompts", "GET")
        r_type, _, _ = ws._resolve_policy_from_request(req)
        assert r_type == "admin"

    def test_ws_path_returns_swarm(self):
        ws = _get_web_server()
        req = self._make_request("/ws/chat", "GET")
        r_type, _, _ = ws._resolve_policy_from_request(req)
        assert r_type == "swarm"

    def test_unknown_path_returns_empty(self):
        ws = _get_web_server()
        req = self._make_request("/unknown/path", "GET")
        r_type, action, resource_id = ws._resolve_policy_from_request(req)
        assert r_type == ""
        assert action == ""
        assert resource_id == ""


class TestGetClientIp:
    def _make_request(self, host, headers=None, trusted_proxies=None):
        import types as _t
        client = _t.SimpleNamespace(host=host)
        url = _t.SimpleNamespace(path="/test")
        return _t.SimpleNamespace(
            client=client,
            url=url,
            headers=headers or {},
        )

    def test_returns_direct_ip_when_not_trusted_proxy(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", set(), raising=False)
        req = self._make_request("1.2.3.4")
        assert ws._get_client_ip(req) == "1.2.3.4"

    def test_returns_xff_when_trusted_proxy(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", {"10.0.0.1"}, raising=False)
        req = self._make_request("10.0.0.1", headers={"X-Forwarded-For": "5.6.7.8, 10.0.0.1"})
        assert ws._get_client_ip(req) == "5.6.7.8"

    def test_returns_x_real_ip_when_xff_missing(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", {"10.0.0.1"}, raising=False)
        req = self._make_request("10.0.0.1", headers={"X-Real-IP": "9.8.7.6"})
        assert ws._get_client_ip(req) == "9.8.7.6"

    def test_returns_unknown_when_no_client(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", set(), raising=False)
        req = types.SimpleNamespace(client=None, headers={})
        assert ws._get_client_ip(req) == "unknown"


class TestVerifyHmacSignature:
    def test_valid_signature_does_not_raise(self):
        import hashlib
        import hmac as _hmac
        ws = _get_web_server()
        secret = b"mysecret"
        body = b'{"event": "push"}'
        sig = "sha256=" + _hmac.new(secret, body, hashlib.sha256).hexdigest()
        # exception olmamalı
        ws._verify_hmac_signature(body, "mysecret", sig, label="Test")

    def test_invalid_signature_raises_401(self):
        ws = _get_web_server()
        body = b'{"event": "push"}'
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._verify_hmac_signature(body, "mysecret", "sha256=invalidhash", label="Test")
        assert exc_info.value.status_code == 401

    def test_empty_signature_header_raises_401(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._verify_hmac_signature(b"body", "mysecret", "", label="Test")
        assert exc_info.value.status_code == 401

    def test_empty_secret_skips_verification(self):
        ws = _get_web_server()
        # secret boşsa doğrulama yapılmamalı
        ws._verify_hmac_signature(b"body", "", "anysig", label="Test")


class TestMakeStaticFiles:
    def test_returns_static_files_object(self):
        ws = _get_web_server()
        import pathlib
        result = ws._make_static_files(pathlib.Path("/tmp"))
        assert result is not None

    def test_does_not_raise_for_nonexistent_dir(self):
        ws = _get_web_server()
        import pathlib
        # Var olmayan dizin — exception fırlatmamalı
        result = ws._make_static_files(pathlib.Path("/nonexistent/path"))
        assert result is not None


class TestReapChildProcessesNonblocking:
    def test_returns_zero_when_no_children(self, monkeypatch):
        ws = _get_web_server()
        # ChildProcessError fırlatarak simüle edilir
        monkeypatch.setattr(ws.os, "waitpid", lambda pid, flag: (_ for _ in ()).throw(ChildProcessError()))
        assert ws._reap_child_processes_nonblocking() == 0

    def test_returns_count_of_reaped_children(self, monkeypatch):
        ws = _get_web_server()
        calls = [0]

        def fake_waitpid(pid, flag):
            calls[0] += 1
            if calls[0] == 1:
                return (1234, 0)
            raise ChildProcessError()

        monkeypatch.setattr(ws.os, "waitpid", fake_waitpid)
        assert ws._reap_child_processes_nonblocking() == 1


class TestTerminateOllamaChildPids:
    def test_empty_pids_does_nothing(self, monkeypatch):
        ws = _get_web_server()
        killed = []
        monkeypatch.setattr(ws.os, "kill", lambda pid, sig: killed.append(pid))
        ws._terminate_ollama_child_pids([], grace_seconds=0)
        assert killed == []

    def test_sends_sigterm_then_sigkill(self, monkeypatch):
        import signal as _signal
        ws = _get_web_server()
        kills = []
        monkeypatch.setattr(ws.os, "kill", lambda pid, sig: kills.append((pid, sig)))
        monkeypatch.setattr(ws.time, "sleep", lambda s: None)
        ws._terminate_ollama_child_pids([999], grace_seconds=0.01)
        sigs = [sig for _, sig in kills]
        assert _signal.SIGTERM in sigs
        assert _signal.SIGKILL in sigs


class TestListChildOllamaPids:
    def test_returns_list(self):
        ws = _get_web_server()
        result = ws._list_child_ollama_pids()
        assert isinstance(result, list)

    def test_returns_empty_on_subprocess_failure(self, monkeypatch):
        ws = _get_web_server()
        import sys
        # psutil yoksa subprocess'e düşer; subprocess.check_output hata fırlatır
        monkeypatch.setitem(sys.modules, "psutil", None)
        monkeypatch.setattr(ws.subprocess, "check_output", lambda *a, **kw: (_ for _ in ()).throw(Exception("fail")))
        result = ws._list_child_ollama_pids()
        assert result == []


class TestForceShutdownLocalLlmProcesses:
    def test_skips_when_already_done(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "_shutdown_cleanup_done", True)
        reaped = []
        monkeypatch.setattr(ws, "_reap_child_processes_nonblocking", lambda: reaped.append(1) or 0)
        ws._force_shutdown_local_llm_processes()
        assert reaped == []

    def test_runs_cleanup_for_non_ollama(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "_shutdown_cleanup_done", False)
        monkeypatch.setattr(ws.cfg, "AI_PROVIDER", "openai", raising=False)
        reaped = []
        monkeypatch.setattr(ws, "_reap_child_processes_nonblocking", lambda: reaped.append(1) or 0)
        ws._force_shutdown_local_llm_processes()
        assert len(reaped) >= 1
        # cleanup sonrası flag set edilmeli
        assert ws._shutdown_cleanup_done is True


class TestLoadPluginAgentClass:
    def test_loads_valid_agent_class(self, monkeypatch):
        ws = _get_web_server()
        # BaseAgent'ı object olarak monkeypatch ederek her sınıfın issubclass kontrolünü geçmesini sağla
        monkeypatch.setattr(ws, "BaseAgent", object)
        result = ws._load_plugin_agent_class(
            "class MyAgent:\n    pass\n",
            None,
            "test_label",
        )
        assert result.__name__ == "MyAgent"

    def test_raises_400_for_syntax_error(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class("def broken(:\n    pass", None, "bad_plugin")
        assert exc_info.value.status_code == 400

    def test_raises_400_when_no_agent_class_found(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class("x = 1\n", None, "empty_plugin")
        assert exc_info.value.status_code == 400

    def test_raises_400_for_named_class_not_found(self):
        ws = _get_web_server()
        source = "class Foo:\n    pass\n"
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class(source, "MissingClass", "label")
        assert exc_info.value.status_code == 400


class TestPluginMarketplaceStatePath:
    def test_returns_path_object(self):
        ws = _get_web_server()
        import pathlib
        result = ws._plugin_marketplace_state_path()
        assert isinstance(result, pathlib.Path)
        assert result.name == ".marketplace_state.json"


class TestReadPluginMarketplaceState:
    def test_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws, "_plugin_marketplace_state_path", lambda: tmp_path / "nonexistent.json")
        result = ws._read_plugin_marketplace_state()
        assert result == {}

    def test_returns_parsed_json_when_file_exists(self, tmp_path, monkeypatch):
        ws = _get_web_server()
        state_file = tmp_path / ".marketplace_state.json"
        state_file.write_text('{"aws_management": {"installed_at": "2026-01-01"}}', encoding="utf-8")
        monkeypatch.setattr(ws, "_plugin_marketplace_state_path", lambda: state_file)
        result = ws._read_plugin_marketplace_state()
        assert "aws_management" in result

    def test_returns_empty_dict_on_invalid_json(self, tmp_path, monkeypatch):
        ws = _get_web_server()
        state_file = tmp_path / ".marketplace_state.json"
        state_file.write_text("not-json", encoding="utf-8")
        monkeypatch.setattr(ws, "_plugin_marketplace_state_path", lambda: state_file)
        result = ws._read_plugin_marketplace_state()
        assert result == {}

    def test_returns_empty_dict_when_json_is_not_dict(self, tmp_path, monkeypatch):
        ws = _get_web_server()
        state_file = tmp_path / ".marketplace_state.json"
        state_file.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr(ws, "_plugin_marketplace_state_path", lambda: state_file)
        result = ws._read_plugin_marketplace_state()
        assert result == {}


class TestWritePluginMarketplaceState:
    def test_writes_json_to_file(self, tmp_path, monkeypatch):
        ws = _get_web_server()
        state_file = tmp_path / ".marketplace_state.json"
        monkeypatch.setattr(ws, "_plugin_marketplace_state_path", lambda: state_file)
        ws._write_plugin_marketplace_state({"aws_management": {"installed_at": "2026-01-01"}})
        import json
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "aws_management" in data


class TestGetPluginMarketplaceEntry:
    def test_returns_entry_for_known_plugin(self):
        ws = _get_web_server()
        result = ws._get_plugin_marketplace_entry("aws_management")
        assert result["plugin_id"] == "aws_management"

    def test_case_insensitive_lookup(self):
        ws = _get_web_server()
        result = ws._get_plugin_marketplace_entry("AWS_Management")
        assert result["plugin_id"] == "aws_management"

    def test_raises_404_for_unknown_plugin(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._get_plugin_marketplace_entry("nonexistent_plugin")
        assert exc_info.value.status_code == 404


class TestScheduleAccessAuditLog:
    def test_skips_when_empty_resource(self):
        ws = _get_web_server()
        user = types.SimpleNamespace(id="u1", tenant_id="acme")
        # resource_type boş olduğunda _build_audit_resource "" döner → erken çıkar
        ws._schedule_access_audit_log(
            user=user,
            resource_type="",
            action="read",
            resource_id="doc-1",
            ip_address="1.2.3.4",
            allowed=True,
        )

    def test_schedules_task_when_loop_running(self):
        ws = _get_web_server()
        import asyncio

        user = types.SimpleNamespace(id="u1", tenant_id="acme")
        created_tasks = []

        async def runner():
            loop = asyncio.get_running_loop()
            orig_create = loop.create_task

            def fake_create(coro, **kw):
                task = orig_create(coro, **kw)
                created_tasks.append(task)
                return task

            loop.create_task = fake_create
            ws._schedule_access_audit_log(
                user=user,
                resource_type="rag",
                action="read",
                resource_id="doc-1",
                ip_address="1.2.3.4",
                allowed=True,
            )
            loop.create_task = orig_create
            await asyncio.sleep(0)

        asyncio.run(runner())
        assert len(created_tasks) >= 1


class TestBindLlmUsageSink:
    def test_skips_when_already_bound(self, monkeypatch):
        ws = _get_web_server()
        collector = types.SimpleNamespace(_sidar_usage_sink_bound=True)
        monkeypatch.setattr(ws, "get_llm_metrics_collector", lambda: collector)
        ws._bind_llm_usage_sink(None)
        # usage sink set edilmemeli (zaten bound)
        assert not hasattr(collector, "_sink_set")

    def test_binds_sink_when_not_yet_bound(self, monkeypatch):
        ws = _get_web_server()
        sinks = []
        collector = types.SimpleNamespace(
            _sidar_usage_sink_bound=False,
            set_usage_sink=lambda s: sinks.append(s),
        )
        monkeypatch.setattr(ws, "get_llm_metrics_collector", lambda: collector)
        ws._bind_llm_usage_sink(None)
        assert len(sinks) == 1
        assert collector._sidar_usage_sink_bound is True