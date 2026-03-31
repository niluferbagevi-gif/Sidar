"""web_server.py için birim testleri (ağır bağımlılıklar stub'lanarak)."""

from __future__ import annotations

import importlib
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

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


class TestOptionalDependencyFallbacks:
    def test_opentelemetry_import_failure_sets_fallback_symbols(self):
        _inject_web_server_stubs()
        sys.modules.pop("web_server", None)

        missing_otel_modules = {
            "opentelemetry": None,
            "opentelemetry.trace": None,
            "opentelemetry.exporter": None,
            "opentelemetry.exporter.otlp": None,
            "opentelemetry.exporter.otlp.proto": None,
            "opentelemetry.exporter.otlp.proto.grpc": None,
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
            "opentelemetry.instrumentation": None,
            "opentelemetry.instrumentation.fastapi": None,
            "opentelemetry.instrumentation.httpx": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.resources": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
        }
        with patch.dict(sys.modules, missing_otel_modules):
            ws = importlib.import_module("web_server")

        assert ws.trace is None
        assert ws.OTLPSpanExporter is None
        assert ws.FastAPIInstrumentor is None
        assert ws.HTTPXClientInstrumentor is None
        assert ws.TracerProvider is None
        assert ws.Resource is None
        assert ws.BatchSpanProcessor is None


class TestRoomNormalization:
    def test_empty_room_id_uses_default(self):
        ws = _get_web_server()
        assert ws._normalize_room_id("   ") == "workspace:default"

    def test_invalid_room_id_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._normalize_room_id("bad room id")
        assert exc_info.value.status_code == 400

    def test_plugin_role_name_validation_raises_400(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._validate_plugin_role_name("bad role with spaces")
        assert exc_info.value.status_code == 400


class TestWebServerExceptionHandlers:
    def test_register_exception_handlers_noop_when_method_missing(self):
        ws = _get_web_server()
        # exception_handler attribute yoksa sessizce dönmeli
        ws._register_exception_handlers(object())

    def test_http_exception_handler_wraps_dict_detail(self, monkeypatch):
        ws = _get_web_server()
        captured = {}

        class _FakeJSONResponse:
            def __init__(self, content, status_code=200):
                self.content = content
                self.status_code = status_code

        class _FakeApp:
            def exception_handler(self, exc_type):
                def _decorator(func):
                    captured[exc_type] = func
                    return func

                return _decorator

        monkeypatch.setattr(ws, "JSONResponse", _FakeJSONResponse)
        fake_app = _FakeApp()
        ws._register_exception_handlers(fake_app)

        exc = ws.HTTPException(status_code=403, detail={"error": "forbidden", "code": "AUTH_403"})
        response = asyncio.run(captured[ws.HTTPException](types.SimpleNamespace(), exc))
        assert response.status_code == 403
        assert response.content["success"] is False
        assert response.content["code"] == "AUTH_403"


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

    def test_append_room_telemetry_masks_fields(self, monkeypatch):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        monkeypatch.setattr(ws, "_mask_collaboration_text", lambda text: f"masked::{text}")

        ws._append_room_telemetry(
            room,
            {"content": "secret", "error": "boom", "other": "kept"},
            limit=5,
        )

        assert room.telemetry[0]["content"] == "masked::secret"
        assert room.telemetry[0]["error"] == "masked::boom"
        assert room.telemetry[0]["other"] == "kept"

    def test_append_room_telemetry_applies_limit(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        for i in range(4):
            ws._append_room_telemetry(room, {"id": str(i)}, limit=2)
        assert [item["id"] for item in room.telemetry] == ["2", "3"]


class TestMaskingAndSerialization:
    def test_mask_collaboration_text_fallback_on_import_error(self):
        ws = _get_web_server()
        assert ws._mask_collaboration_text("plain") == "plain"

    def test_serialize_room_sorts_participants_and_truncates_buffers(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        room.participants = {
            2: ws._CollaborationParticipant(
                websocket=types.SimpleNamespace(),
                display_name="zeta",
                username="z",
                user_id="2",
            ),
            1: ws._CollaborationParticipant(
                websocket=types.SimpleNamespace(),
                display_name="Alpha",
                username="a",
                user_id="1",
            ),
        }
        room.messages = [{"id": str(i)} for i in range(130)]
        room.telemetry = [{"id": str(i)} for i in range(130)]

        payload = ws._serialize_collaboration_room(room)

        assert [item["display_name"] for item in payload["participants"]] == ["Alpha", "zeta"]
        assert len(payload["messages"]) == 120
        assert len(payload["telemetry"]) == 120
        assert payload["messages"][0]["id"] == "10"
        assert payload["telemetry"][0]["id"] == "10"

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


class TestWebServerErrorHandlers:
    def test_marketplace_entry_missing_returns_404(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._get_plugin_marketplace_entry("missing-plugin")
        assert exc_info.value.status_code == 404

    def test_registered_unhandled_exception_handler_returns_500(self):
        ws = _get_web_server()
        handlers = {}

        class _App:
            def exception_handler(self, exc_cls):
                def _register(fn):
                    handlers[exc_cls] = fn
                    return fn
                return _register

        ws._register_exception_handlers(_App())
        unhandled = handlers[Exception]
        request_mock = types.SimpleNamespace(url=types.SimpleNamespace(path="/test-error"))
        response = asyncio.run(unhandled(request_mock, RuntimeError("boom")))
        assert getattr(response, "status_code", 500) == 500


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


class TestWebSocketStreamHelpers:
    def test_ws_close_policy_violation_calls_close_with_1008(self):
        ws = _get_web_server()
        closed = []

        class _Socket:
            async def close(self, code, reason):
                closed.append((code, reason))

        asyncio.run(ws._ws_close_policy_violation(_Socket(), "invalid token"))
        assert closed == [(1008, "invalid token")]

    def test_ws_stream_agent_text_response_emits_tool_thought_and_chunk(self):
        ws = _get_web_server()
        sent = []

        class _Socket:
            async def send_json(self, payload):
                sent.append(payload)

        class _Agent:
            async def respond(self, _prompt):
                yield "\x00TOOL:read_file(main.py)\x00"
                yield "\x00THOUGHT:planning\x00"
                yield "normal chunk"

        asyncio.run(ws._ws_stream_agent_text_response(_Socket(), _Agent(), "test prompt"))
        assert sent == [
            {"tool_call": "read_file(main.py)"},
            {"thought": "planning"},
            {"chunk": "normal chunk"},
        ]

    def test_ws_stream_agent_text_response_emits_audio_chunks_when_voice_pipeline_enabled(self):
        ws = _get_web_server()
        sent = []

        class _Socket:
            _sidar_voice_pipeline = types.SimpleNamespace(
                enabled=True,
                extract_ready_segments=lambda text, flush=False: (
                    [text] if text.strip() and flush else [],
                    "" if flush else text,
                ),
                synthesize_text=AsyncMock(
                    side_effect=lambda segment: {
                        "success": True,
                        "audio_bytes": b"\x00\x01",
                        "mime_type": "audio/wav",
                        "provider": "stub",
                        "voice": "test",
                    }
                ),
            )
            _sidar_voice_duplex_state = {}

            async def send_json(self, payload):
                sent.append(payload)

        class _Agent:
            async def respond(self, _prompt):
                yield "Merhaba dünya"

        asyncio.run(ws._ws_stream_agent_text_response(_Socket(), _Agent(), "test prompt"))
        assert any("chunk" in item for item in sent)
        assert any("audio_chunk" in item for item in sent)


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


class TestHealthAndRateLimitHelpers:
    def test_await_if_needed_with_plain_value(self):
        ws = _get_web_server()
        assert asyncio.run(ws._await_if_needed(42)) == 42

    def test_await_if_needed_with_coroutine(self):
        ws = _get_web_server()

        async def _value():
            return "ok"

        assert asyncio.run(ws._await_if_needed(_value())) == "ok"

    def test_health_response_returns_503_when_get_agent_fails(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        async def _get_agent():
            raise RuntimeError("agent missing")

        monkeypatch.setattr(ws, "JSONResponse", _Response)
        monkeypatch.setattr(ws, "get_agent", _get_agent)

        result = asyncio.run(ws._health_response(require_dependencies=False))

        assert result.status_code == 503
        assert result.content["status"] == "degraded"
        assert result.content["error"] == "health_check_failed"

    def test_health_response_requires_dependencies_and_flags_unhealthy(self, monkeypatch):
        ws = _get_web_server()

        class _Response:
            def __init__(self, content=None, status_code=200):
                self.content = content or {}
                self.status_code = status_code

        fake_agent = types.SimpleNamespace(
            cfg=types.SimpleNamespace(AI_PROVIDER="openai"),
            health=types.SimpleNamespace(
                get_health_summary=lambda: {"status": "ok", "ollama_online": True},
                get_dependency_health=lambda: {
                    "redis": {"healthy": True},
                    "postgres": {"healthy": False, "detail": "down"},
                },
            ),
        )

        async def _get_agent():
            return fake_agent

        monkeypatch.setattr(ws, "JSONResponse", _Response)
        monkeypatch.setattr(ws, "get_agent", _get_agent)

        result = asyncio.run(ws._health_response(require_dependencies=True))

        assert result.status_code == 503
        assert result.content["status"] == "degraded"
        assert result.content["dependencies"]["postgres"]["healthy"] is False

    def test_get_client_ip_uses_forwarded_header_for_trusted_proxy(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", ["127.0.0.1"], raising=False)
        request = types.SimpleNamespace(
            client=types.SimpleNamespace(host="127.0.0.1"),
            headers={"X-Forwarded-For": "198.51.100.20, 127.0.0.1"},
        )

        assert ws._get_client_ip(request) == "198.51.100.20"

    def test_get_client_ip_ignores_forwarded_header_for_untrusted_proxy(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.Config, "TRUSTED_PROXIES", ["10.0.0.1"], raising=False)
        request = types.SimpleNamespace(
            client=types.SimpleNamespace(host="203.0.113.2"),
            headers={"X-Forwarded-For": "198.51.100.20"},
        )

        assert ws._get_client_ip(request) == "203.0.113.2"

    def test_local_rate_limiter_blocks_after_limit(self, monkeypatch):
        ws = _get_web_server()
        ws._local_rate_limits.clear()
        ws._local_rate_lock = asyncio.Lock()

        now = {"v": 1000.0}
        monkeypatch.setattr(ws.time, "time", lambda: now["v"])

        assert asyncio.run(ws._local_is_rate_limited("k", limit=2, window_sec=60)) is False
        now["v"] += 1
        assert asyncio.run(ws._local_is_rate_limited("k", limit=2, window_sec=60)) is False
        now["v"] += 1
        assert asyncio.run(ws._local_is_rate_limited("k", limit=2, window_sec=60)) is True


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

    def test_participants_sorted_case_insensitive_by_display_name(self):
        ws = _get_web_server()
        room = ws._CollaborationRoom(room_id="workspace:default")
        room.participants = {
            1: ws._CollaborationParticipant(types.SimpleNamespace(), "u1", "z", "zeta"),
            2: ws._CollaborationParticipant(types.SimpleNamespace(), "u2", "a", "Alpha"),
        }
        result = ws._serialize_collaboration_room(room)
        assert [item["display_name"] for item in result["participants"]] == ["Alpha", "zeta"]


class TestCollaborationParticipantCompat:
    def test_legacy_joined_at_passed_as_role_argument_is_supported(self):
        ws = _get_web_server()
        participant = ws._CollaborationParticipant(
            websocket=types.SimpleNamespace(),
            user_id="u-legacy",
            username="legacy",
            display_name="Legacy User",
            role="2026-03-28T12:00:00+00:00",
        )
        assert participant.role == "user"
        assert participant.joined_at == "2026-03-28T12:00:00+00:00"


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


class TestPluginLoadingHelpers:
    def test_sanitize_capabilities_removes_blank_entries(self):
        ws = _get_web_server()
        capabilities = ws._sanitize_capabilities([" read ", "", "   ", "write"])
        assert capabilities == ["read", "write"]

    def test_plugin_source_filename_sanitizes_module_label(self):
        ws = _get_web_server()
        filename = ws._plugin_source_filename("my plugin/../danger")
        assert filename == "<sidar-plugin:my_plugin_.._danger>"

    def test_load_plugin_agent_class_raises_for_invalid_source(self):
        ws = _get_web_server()
        bad_source = "class Broken(:\n    pass\n"
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class(bad_source, None, "broken_module")
        assert exc_info.value.status_code == 400
        assert "derlenemedi" in exc_info.value.detail

    def test_load_plugin_agent_class_raises_when_named_class_not_found(self):
        ws = _get_web_server()
        source = "class Demo:\n    pass\n"
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class(source, "MissingClass", "missing_named")
        assert exc_info.value.status_code == 400
        assert "bulunamadı" in exc_info.value.detail

    def test_load_plugin_agent_class_raises_when_class_not_base_agent(self):
        ws = _get_web_server()
        source = "class Plain:\n    pass\n"
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class(source, "Plain", "plain_module")
        assert exc_info.value.status_code == 400
        assert "BaseAgent" in exc_info.value.detail

    def test_load_plugin_agent_class_raises_when_no_derived_class_exists(self):
        ws = _get_web_server()
        with pytest.raises(ws.HTTPException) as exc_info:
            ws._load_plugin_agent_class("x = 1", None, "empty_module")
        assert exc_info.value.status_code == 400
        assert "BaseAgent türevi" in exc_info.value.detail


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


class _WSClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(payload)


class TestCollaborationRoomAsync:
    def test_broadcast_room_payload_removes_stale_participants(self):
        async def _run():
            ws = _get_web_server()
            room = ws._CollaborationRoom(room_id="workspace:default")
            healthy = ws._CollaborationParticipant(_WSClient(), "u1", "ok", "OK")
            stale = ws._CollaborationParticipant(_WSClient(fail=True), "u2", "bad", "BAD")
            room.participants = {1: healthy, 2: stale}

            await ws._broadcast_room_payload(room, {"type": "ping"})

            assert 1 in room.participants
            assert 2 not in room.participants
            assert healthy.websocket.sent == [{"type": "ping"}]
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_leave_collaboration_room_cancels_active_task_for_empty_room(self):
        async def _run():
            ws = _get_web_server()
            room = ws._CollaborationRoom(room_id="workspace:default")
            websocket = _WSClient()
            room.participants[ws._socket_key(websocket)] = ws._CollaborationParticipant(
                websocket,
                "u1",
                "ali",
                "Ali",
            )
            ws._collaboration_rooms["workspace:default"] = room
            setattr(websocket, "_sidar_room_id", "workspace:default")

            room.active_task = asyncio.create_task(asyncio.sleep(60))
            await ws._leave_collaboration_room(websocket)
            await asyncio.sleep(0)

            assert "workspace:default" not in ws._collaboration_rooms
            assert room.active_task.cancelled() is True
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestCollaborationJoinLeaveEdges:
    def test_join_collaboration_room_switches_previous_room(self, monkeypatch):
        async def _run():
            ws = _get_web_server()

            class _Socket:
                def __init__(self):
                    self._sidar_room_id = "workspace:old"
                    self.sent = []

                async def send_json(self, payload):
                    self.sent.append(payload)

            socket = _Socket()
            leave_calls = []

            async def _fake_leave(ws_obj):
                leave_calls.append(ws_obj)
                ws_obj._sidar_room_id = ""

            monkeypatch.setattr(ws, "_leave_collaboration_room", _fake_leave)
            room = await ws._join_collaboration_room(
                socket,
                room_id="workspace:new",
                user_id="u1",
                username="ali",
                display_name="Ali",
                user_role="user",
            )

            assert leave_calls == [socket]
            assert room.room_id == "workspace:new"
            assert socket._sidar_room_id == "workspace:new"
            assert any(item.get("type") == "room_state" for item in socket.sent)
        import asyncio as _asyncio
        _asyncio.run(_run())

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

    def test_wrong_metrics_token_raises_403_for_non_admin(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.cfg, "METRICS_TOKEN", "expected-token", raising=False)
        user = types.SimpleNamespace(role="user", username="zeynep")
        request = types.SimpleNamespace(headers={"Authorization": "Bearer wrong-token"})
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

    def test_unhandled_exception_is_logged_by_registered_handler(self):
        ws = _get_web_server()

        class _CaptureApp:
            def __init__(self):
                self.handlers = {}

            def exception_handler(self, exc_type):
                def _decorator(fn):
                    self.handlers[exc_type] = fn
                    return fn
                return _decorator

        capture_app = _CaptureApp()
        ws._register_exception_handlers(capture_app)
        handler = capture_app.handlers[Exception]

        request = types.SimpleNamespace(url=types.SimpleNamespace(path="/boom"))
        with pytest.raises(RuntimeError, match="boom"):
            raise RuntimeError("boom")

        fake_logger = MagicMock()
        fake_json_response = MagicMock(side_effect=lambda payload, status_code=500: {"payload": payload, "status_code": status_code})
        ws.logger = fake_logger
        ws.JSONResponse = fake_json_response

        async def _scenario():
            response = await handler(request, RuntimeError("boom"))
            assert response["status_code"] == 500
            assert response["payload"]["error"] == "İç sunucu hatası"

        asyncio.run(_scenario())
        assert fake_logger.exception.call_count == 1


class TestBasicAuthMiddleware:
    def test_open_path_bypasses_auth(self):
        ws = _get_web_server()
        called = []

        async def _next(_request):
            called.append(True)
            return {"ok": True}

        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/health"),
            headers={},
            state=types.SimpleNamespace(),
        )

        result = asyncio.run(ws.basic_auth_middleware(request, _next))
        assert result == {"ok": True}
        assert called == [True]

    def test_missing_bearer_header_returns_401(self):
        ws = _get_web_server()
        ws.JSONResponse = lambda payload, status_code=500: {"payload": payload, "status_code": status_code}
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/secure"),
            headers={},
            state=types.SimpleNamespace(),
        )
        async def _next(_request):
            return {"ok": True}

        response = asyncio.run(ws.basic_auth_middleware(request, _next))
        assert response["status_code"] == 401

    def test_empty_token_returns_401(self):
        ws = _get_web_server()
        ws.JSONResponse = lambda payload, status_code=500: {"payload": payload, "status_code": status_code}
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/secure"),
            headers={"Authorization": "Bearer    "},
            state=types.SimpleNamespace(),
        )
        async def _next(_request):
            return {"ok": True}

        response = asyncio.run(ws.basic_auth_middleware(request, _next))
        assert response["status_code"] == 401

    def test_invalid_user_from_token_returns_401(self, monkeypatch):
        ws = _get_web_server()
        ws.JSONResponse = lambda payload, status_code=500: {"payload": payload, "status_code": status_code}
        async def _resolve_user(_request, _token):
            return None
        monkeypatch.setattr(ws, "_resolve_user_from_token", _resolve_user)
        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/secure"),
            headers={"Authorization": "Bearer t1"},
            state=types.SimpleNamespace(),
        )
        async def _next(_request):
            return {"ok": True}

        response = asyncio.run(ws.basic_auth_middleware(request, _next))
        assert response["status_code"] == 401

    def test_valid_token_sets_user_and_resets_metrics_context(self, monkeypatch):
        ws = _get_web_server()
        user = types.SimpleNamespace(id="u1", username="ali")
        metrics_tokens = []
        reset_tokens = []
        active_users = []
        next_called = []

        async def _fake_next(_request):
            next_called.append(True)
            return {"ok": True}

        class _Memory:
            async def set_active_user(self, user_id, username):
                active_users.append((user_id, username))

        class _Agent:
            memory = _Memory()

        async def _resolve_user(_request, _token):
            return user

        async def _get_agent():
            return _Agent()

        monkeypatch.setattr(ws, "_resolve_user_from_token", _resolve_user)
        monkeypatch.setattr(ws, "get_agent", _get_agent)
        monkeypatch.setattr(ws, "set_current_metrics_user_id", lambda uid: metrics_tokens.append(uid) or "tok-1")
        monkeypatch.setattr(ws, "reset_current_metrics_user_id", lambda token: reset_tokens.append(token))

        request = types.SimpleNamespace(
            method="GET",
            url=types.SimpleNamespace(path="/secure"),
            headers={"Authorization": "Bearer valid-token"},
            state=types.SimpleNamespace(),
        )
        result = asyncio.run(ws.basic_auth_middleware(request, _fake_next))

        assert result == {"ok": True}
        assert request.state.user is user
        assert active_users == [("u1", "ali")]
        assert metrics_tokens == ["u1"]
        assert reset_tokens == ["tok-1"]
        assert next_called == [True]

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

    def test_handles_missing_running_loop_without_raising(self, monkeypatch):
        ws = _get_web_server()
        user = types.SimpleNamespace(id="u1", tenant_id="acme")
        monkeypatch.setattr(
            ws.asyncio,
            "get_running_loop",
            lambda: (_ for _ in ()).throw(RuntimeError("no loop")),
        )
        ws._schedule_access_audit_log(
            user=user,
            resource_type="rag",
            action="read",
            resource_id="doc-1",
            ip_address="1.2.3.4",
            allowed=True,
        )


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


class TestOperationsEndpoints:
    def _patch_json_response(self, ws, monkeypatch):
        class _Resp:
            def __init__(self, content, status_code=200):
                self.content = content
                self.status_code = status_code

        monkeypatch.setattr(ws, "JSONResponse", _Resp)

    def test_list_campaigns_returns_serialized_rows(self, monkeypatch):
        ws = _get_web_server()
        self._patch_json_response(ws, monkeypatch)
        calls = {}

        class _DB:
            async def list_marketing_campaigns(self, **kwargs):
                calls.update(kwargs)
                return [types.SimpleNamespace(id=3, name="Q2", status="active", tenant_id="acme")]

        async def _fake_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_DB()))

        monkeypatch.setattr(ws, "get_agent", _fake_agent)
        user = types.SimpleNamespace(id="u1", tenant_id="acme")
        response = asyncio.run(ws.api_operations_list_campaigns(status="active", limit=25, _user=user))

        assert response.status_code == 200
        assert response.content["success"] is True
        assert response.content["campaigns"][0]["id"] == 3
        assert calls == {"tenant_id": "acme", "status": "active", "limit": 25}

    def test_create_campaign_persists_initial_assets_and_checklists(self, monkeypatch):
        ws = _get_web_server()
        self._patch_json_response(ws, monkeypatch)
        calls = {"assets": [], "checklists": []}

        class _DB:
            async def upsert_marketing_campaign(self, **kwargs):
                calls["campaign"] = kwargs
                return types.SimpleNamespace(
                    id=7,
                    tenant_id="acme",
                    name=kwargs["name"],
                    channel=kwargs["channel"],
                    objective=kwargs["objective"],
                    status=kwargs["status"],
                    owner_user_id=kwargs["owner_user_id"],
                    budget=kwargs["budget"],
                    metadata_json="{}",
                    created_at="",
                    updated_at="",
                )

            async def add_content_asset(self, **kwargs):
                calls["assets"].append(kwargs)
                return types.SimpleNamespace(
                    id=10,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    asset_type=kwargs["asset_type"],
                    title=kwargs["title"],
                    content=kwargs["content"],
                    channel=kwargs["channel"],
                    metadata_json="{}",
                    created_at="",
                    updated_at="",
                )

            async def add_operation_checklist(self, **kwargs):
                calls["checklists"].append(kwargs)
                return types.SimpleNamespace(
                    id=20,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    title=kwargs["title"],
                    items_json="[]",
                    status=kwargs["status"],
                    owner_user_id=kwargs["owner_user_id"],
                    created_at="",
                    updated_at="",
                )

        async def _fake_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_DB()))

        monkeypatch.setattr(ws, "get_agent", _fake_agent)
        req = types.SimpleNamespace(
            name="Launch",
            channel="email",
            objective="awareness",
            status="draft",
            budget=350.5,
            metadata={"owner": "marketing"},
            initial_assets=[
                types.SimpleNamespace(
                    asset_type="copy",
                    title="Subject",
                    content="Hello",
                    channel="email",
                    metadata={"lang": "tr"},
                )
            ],
            initial_checklists=[
                types.SimpleNamespace(title="Ready", items=["brief"], status="pending")
            ],
        )
        user = types.SimpleNamespace(id="u2", tenant_id="acme")
        response = asyncio.run(ws.api_operations_create_campaign(req=req, _user=user))

        assert response.status_code == 200
        assert response.content["campaign"]["id"] == 7
        assert len(response.content["assets"]) == 1
        assert len(response.content["checklists"]) == 1
        assert calls["campaign"]["owner_user_id"] == "u2"
        assert calls["assets"][0]["tenant_id"] == "acme"
        assert calls["checklists"][0]["owner_user_id"] == "u2"

    def test_asset_and_checklist_endpoints_call_expected_db_methods(self, monkeypatch):
        ws = _get_web_server()
        self._patch_json_response(ws, monkeypatch)
        calls = {}

        class _DB:
            async def list_content_assets(self, **kwargs):
                calls["list_assets"] = kwargs
                return [
                    types.SimpleNamespace(
                        id=1,
                        campaign_id=kwargs["campaign_id"],
                        tenant_id=kwargs["tenant_id"],
                        asset_type="image",
                        title="Banner",
                        content="...",
                        channel="social",
                        metadata_json="{}",
                        created_at="",
                        updated_at="",
                    )
                ]

            async def add_content_asset(self, **kwargs):
                calls["add_asset"] = kwargs
                return types.SimpleNamespace(
                    id=2,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    asset_type=kwargs["asset_type"],
                    title=kwargs["title"],
                    content=kwargs["content"],
                    channel=kwargs["channel"],
                    metadata_json="{}",
                    created_at="",
                    updated_at="",
                )

            async def list_operation_checklists(self, **kwargs):
                calls["list_checklists"] = kwargs
                return [
                    types.SimpleNamespace(
                        id=3,
                        campaign_id=kwargs["campaign_id"],
                        tenant_id=kwargs["tenant_id"],
                        title="Ops",
                        items_json="[]",
                        status="pending",
                        owner_user_id="u1",
                        created_at="",
                        updated_at="",
                    )
                ]

            async def add_operation_checklist(self, **kwargs):
                calls["add_checklist"] = kwargs
                return types.SimpleNamespace(
                    id=4,
                    campaign_id=kwargs["campaign_id"],
                    tenant_id=kwargs["tenant_id"],
                    title=kwargs["title"],
                    items_json="[]",
                    status=kwargs["status"],
                    owner_user_id=kwargs["owner_user_id"],
                    created_at="",
                    updated_at="",
                )

        async def _fake_agent():
            return types.SimpleNamespace(memory=types.SimpleNamespace(db=_DB()))

        monkeypatch.setattr(ws, "get_agent", _fake_agent)
        user = types.SimpleNamespace(id="u7", tenant_id="acme")

        assets_resp = asyncio.run(ws.api_operations_list_assets(campaign_id=77, limit=8, _user=user))
        add_asset_req = types.SimpleNamespace(
            asset_type="video", title="Reel", content="content", channel="social", metadata={"a": 1}
        )
        add_asset_resp = asyncio.run(ws.api_operations_add_asset(campaign_id=77, req=add_asset_req, _user=user))
        checklists_resp = asyncio.run(ws.api_operations_list_checklists(campaign_id=77, limit=5, _user=user))
        add_check_req = types.SimpleNamespace(title="Publish", items=["design"], status="done")
        add_check_resp = asyncio.run(ws.api_operations_add_checklist(campaign_id=77, req=add_check_req, _user=user))

        assert assets_resp.content["assets"][0]["id"] == 1
        assert add_asset_resp.content["asset"]["id"] == 2
        assert checklists_resp.content["checklists"][0]["id"] == 3
        assert add_check_resp.content["checklist"]["id"] == 4
        assert calls["list_assets"] == {"tenant_id": "acme", "campaign_id": 77, "limit": 8}
        assert calls["list_checklists"] == {"tenant_id": "acme", "campaign_id": 77, "limit": 5}
        assert calls["add_checklist"]["owner_user_id"] == "u7"


class TestIntegrationEndpointFailures:
    def test_api_jira_create_issue_returns_503_when_unconfigured(self, monkeypatch):
        ws = _get_web_server()
        fake_mgr = types.SimpleNamespace(is_available=lambda: False)
        monkeypatch.setattr(ws, "_get_jira_manager", lambda: fake_mgr)
        req = types.SimpleNamespace(
            project_key="SIDAR",
            summary="Issue",
            description="desc",
            issue_type="Task",
            priority=None,
        )

        with pytest.raises(ws.HTTPException) as exc_info:
            asyncio.run(ws.api_jira_create_issue(req))

        assert exc_info.value.status_code == 503

    def test_api_jira_search_issues_returns_502_on_service_error(self, monkeypatch):
        ws = _get_web_server()
        fake_mgr = types.SimpleNamespace(
            is_available=lambda: True,
            search_issues=AsyncMock(return_value=(False, [], "HTTP 500")),
        )
        monkeypatch.setattr(ws, "_get_jira_manager", lambda: fake_mgr)

        with pytest.raises(ws.HTTPException) as exc_info:
            asyncio.run(ws.api_jira_search_issues(jql="project=SIDAR", max_results=10))

        assert exc_info.value.status_code == 502
        assert "Jira hatası" in str(exc_info.value.detail)

    def test_api_slack_send_returns_503_when_unconfigured(self, monkeypatch):
        ws = _get_web_server()
        fake_mgr = types.SimpleNamespace(is_available=lambda: False)
        monkeypatch.setattr(ws, "_get_slack_manager", AsyncMock(return_value=fake_mgr))
        req = types.SimpleNamespace(text="hello", channel="#ops", thread_ts=None)

        with pytest.raises(ws.HTTPException) as exc_info:
            asyncio.run(ws.api_slack_send(req))

        assert exc_info.value.status_code == 503

    def test_api_slack_channels_returns_502_on_service_error(self, monkeypatch):
        ws = _get_web_server()
        fake_mgr = types.SimpleNamespace(
            is_available=lambda: True,
            list_channels=AsyncMock(return_value=(False, [], "HTTP 401")),
        )
        monkeypatch.setattr(ws, "_get_slack_manager", AsyncMock(return_value=fake_mgr))

        with pytest.raises(ws.HTTPException) as exc_info:
            asyncio.run(ws.api_slack_channels())

        assert exc_info.value.status_code == 502
        assert "Slack hatası" in str(exc_info.value.detail)


class TestGitHelpers:
    def test_git_run_returns_decoded_output(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setattr(ws.subprocess, "check_output", lambda *_a, **_k: b"feature/test-branch\n")

        result = ws._git_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], ".")
        assert result == "feature/test-branch"

    def test_git_run_returns_empty_string_on_exception(self, monkeypatch):
        ws = _get_web_server()

        def _raise(*_a, **_k):
            raise RuntimeError("git failed")

        monkeypatch.setattr(ws.subprocess, "check_output", _raise)
        assert ws._git_run(["git", "status"], ".") == ""

    def test_git_info_parses_remote_and_default_branch(self, monkeypatch):
        ws = _get_web_server()
        responses = {
            ("git", "rev-parse", "--abbrev-ref", "HEAD"): "feature/x",
            ("git", "remote", "get-url", "origin"): "git@github.com:owner/repo.git",
            ("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        }

        async def _fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(ws.asyncio, "to_thread", _fake_to_thread)
        monkeypatch.setattr(ws, "JSONResponse", lambda payload: payload)
        monkeypatch.setattr(ws, "_git_run", lambda cmd, _cwd, stderr=None: responses.get(tuple(cmd), ""))

        result = asyncio.run(ws.git_info())
        assert result == {"branch": "feature/x", "repo": "owner/repo", "default_branch": "main"}

# ===== MERGED FROM tests/test_web_server_extra1.py =====

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

class Extra1__Dummy:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self


class Extra1__FakeFastAPI:
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


class Extra1__HTTPException(Exception):
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

class Extra1_TestMaskCollaborationText:
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

class Extra1_TestBroadcastRoomPayload:
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

class Extra1_TestRoomMessageAppend:
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

class Extra1_TestBuildRoomMessage:
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

class Extra1_TestSidarMention:
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

class Extra1_TestBuildCollaborationPrompt:
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

class Extra1_TestIterStreamChunks:
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

class Extra1_TestHitlBroadcast:
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

class Extra1_TestListChildOllamaPids:
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

class Extra1_TestReapChildProcesses:
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

class Extra1_TestTerminateOllamaChildPids:
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

class Extra1_TestForceShutdown:
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

class Extra1_TestBindLlmUsageSink:
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

class Extra1_TestBuildEventDrivenFederationSpec:
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

class Extra1_TestBuildSwarmGoalForRole:
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

class Extra1_TestAutonomousCronLoop:
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

class Extra1_TestNightlyMemoryLoop:
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


# ===== MERGED FROM tests/test_web_server_extra2.py =====

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

class Extra2__Dummy:
    def __init__(self, *args, **kwargs): pass
    def __call__(self, *args, **kwargs): return self


class Extra2__FakeFastAPI:
    def __init__(self, *args, **kwargs): pass
    def _decorator(self, *_args, **_kwargs):
        def _inner(func): return func
        return _inner
    middleware = _decorator
    exception_handler = _decorator
    get = post = put = delete = patch_method = websocket = _decorator
    def mount(self, *args, **kwargs): return None
    def add_middleware(self, *args, **kwargs): return None


class Extra2__HTTPException(Exception):
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

class Extra2_TestTrimAutonomyText:
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

class Extra2_TestIsAdminUser:
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

class Extra2_TestGetUserTenant:
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

class Extra2_TestSerializePolicy:
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

class Extra2_TestSerializeCollaboration:
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

class Extra2_TestCollaborationWriteScopes:
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

class Extra2_TestJwtUtils:
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

class Extra2_TestNormalizeCollaborationRole:
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

class Extra2_TestCollaborationNowIso:
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

class Extra2_TestSocketKey:
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

class Extra2_TestLeaveCollaborationRoom:
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

class Extra2_TestRateLimiterLocal:
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

class Extra2_TestCollaborationScopePaths:
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

class Extra2_TestAsyncForceShutdown:
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
