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
