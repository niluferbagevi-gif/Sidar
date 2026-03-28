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