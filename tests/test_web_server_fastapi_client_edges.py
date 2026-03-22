import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("pydantic")


ROOT = Path(__file__).resolve().parents[1]


def _load_web_server_with_real_fastapi():
    saved = {name: sys.modules.get(name) for name in (
        "redis.asyncio",
        "uvicorn",
        "config",
        "agent",
        "agent.core",
        "agent.sidar_agent",
        "agent.base_agent",
        "agent.registry",
        "agent.swarm",
        "agent.core.event_stream",
        "managers",
        "managers.system_health",
        "core",
        "core.llm_metrics",
        "core.llm_client",
        "core.ci_remediation",
        "core.hitl",
    )}

    def _set(name: str, module):
        sys.modules[name] = module

    redis_mod = types.ModuleType("redis.asyncio")

    class _Redis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()

        async def ping(self):
            return True

    redis_mod.Redis = _Redis

    uvicorn_mod = types.ModuleType("uvicorn")
    uvicorn_mod.run = lambda *a, **k: None

    cfg_mod = types.ModuleType("config")

    class _Config:
        API_KEY = ""
        ENABLE_TRACING = False
        OTEL_EXPORTER_ENDPOINT = ""
        RATE_LIMIT_CHAT = 5
        RATE_LIMIT_MUTATIONS = 5
        RATE_LIMIT_GET_IO = 5
        RATE_LIMIT_WINDOW = 60
        REDIS_URL = "redis://localhost:6379/0"
        WEB_HOST = "127.0.0.1"
        WEB_PORT = 7860
        GITHUB_WEBHOOK_SECRET = ""
        GITHUB_REPO = ""
        TRUSTED_PROXIES = []
        ACCESS_LEVEL = "sandbox"
        AI_PROVIDER = "ollama"
        METRICS_TOKEN = ""
        MAX_RAG_UPLOAD_BYTES = 50 * 1024 * 1024

        @staticmethod
        def initialize_directories():
            return None

        @staticmethod
        def validate_critical_settings():
            return None

    cfg_mod.Config = _Config

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str((ROOT / "agent").resolve())]
    agent_core_pkg = types.ModuleType("agent.core")
    agent_core_pkg.__path__ = [str((ROOT / "agent" / "core").resolve())]

    sidar_agent_mod = types.ModuleType("agent.sidar_agent")
    sidar_agent_mod.SidarAgent = object

    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = object

    registry_mod = types.ModuleType("agent.registry")
    registry_mod.AgentRegistry = type("_AgentRegistry", (), {"list_all": classmethod(lambda cls: [])})

    swarm_mod = types.ModuleType("agent.swarm")
    swarm_mod.SwarmOrchestrator = lambda cfg: types.SimpleNamespace(cfg=cfg)
    swarm_mod.SwarmTask = lambda **kwargs: types.SimpleNamespace(**kwargs)

    event_stream_mod = types.ModuleType("agent.core.event_stream")
    event_stream_mod.get_agent_event_bus = lambda: types.SimpleNamespace(subscribe=lambda: ("sub-1", asyncio.Queue()), unsubscribe=lambda *_a, **_k: None, publish=lambda *_a, **_k: None)

    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = []
    managers_health_mod = types.ModuleType("managers.system_health")
    managers_health_mod.render_llm_metrics_prometheus = lambda *_a, **_k: ""

    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []

    core_metrics_mod = types.ModuleType("core.llm_metrics")
    core_metrics_mod.get_llm_metrics_collector = lambda: types.SimpleNamespace(snapshot=lambda: {"totals": {"calls": 0, "total_tokens": 0}})
    core_metrics_mod.set_current_metrics_user_id = lambda _user_id: None
    core_metrics_mod.reset_current_metrics_user_id = lambda _token: None

    llm_client_mod = types.ModuleType("core.llm_client")

    class _LLMAPIError(Exception):
        def __init__(self, message="err", provider="stub", status_code=None, retryable=False):
            super().__init__(message)
            self.provider = provider
            self.status_code = status_code
            self.retryable = retryable

    llm_client_mod.LLMAPIError = _LLMAPIError

    ci_mod = types.ModuleType("core.ci_remediation")
    ci_mod.build_ci_failure_context = lambda *_a, **_k: {}

    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_gate = lambda: types.SimpleNamespace()
    hitl_mod.get_hitl_store = lambda: types.SimpleNamespace(list_pending=lambda: [], get=lambda *_a, **_k: None)
    hitl_mod.set_hitl_broadcast_hook = lambda *_a, **_k: None

    for name, module in (
        ("redis.asyncio", redis_mod),
        ("uvicorn", uvicorn_mod),
        ("config", cfg_mod),
        ("agent", agent_pkg),
        ("agent.core", agent_core_pkg),
        ("agent.sidar_agent", sidar_agent_mod),
        ("agent.base_agent", base_agent_mod),
        ("agent.registry", registry_mod),
        ("agent.swarm", swarm_mod),
        ("agent.core.event_stream", event_stream_mod),
        ("managers", managers_pkg),
        ("managers.system_health", managers_health_mod),
        ("core", core_pkg),
        ("core.llm_metrics", core_metrics_mod),
        ("core.llm_client", llm_client_mod),
        ("core.ci_remediation", ci_mod),
        ("core.hitl", hitl_mod),
    ):
        _set(name, module)

    spec = importlib.util.spec_from_file_location("web_server_fastapi_test", ROOT / "web_server.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def fastapi_web_mod(monkeypatch):
    mod = _load_web_server_with_real_fastapi()

    class _Memory:
        def __init__(self):
            self.db = types.SimpleNamespace()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 0

    agent = types.SimpleNamespace(
        VERSION="test",
        cfg=types.SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
        docs=types.SimpleNamespace(doc_count=0),
        memory=_Memory(),
        health=types.SimpleNamespace(
            get_health_summary=lambda: {"status": "ok", "ollama_online": True},
            get_dependency_health=lambda: {"redis": {"healthy": True}, "database": {"healthy": True}},
        ),
    )

    async def _get_agent():
        return agent

    async def _resolve_user(_agent, token):
        if token == "good-token":
            return types.SimpleNamespace(id="u1", username="alice", role="user")
        if token == "admin-token":
            return types.SimpleNamespace(id="a1", username="default_admin", role="admin")
        return None

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", lambda *_a, **_k: asyncio.sleep(0, result=False))
    return mod


def test_fastapi_client_handles_401_403_422_and_readiness_503(fastapi_web_mod, monkeypatch):
    from fastapi.testclient import TestClient

    mod = fastapi_web_mod

    class _Store:
        async def initialize(self):
            raise AssertionError("validation should fail before feedback store init")

    active_learning_mod = types.ModuleType("core.active_learning")
    active_learning_mod.get_feedback_store = lambda _cfg: _Store()
    monkeypatch.setitem(sys.modules, "core.active_learning", active_learning_mod)

    client = TestClient(mod.app)

    unauthorized = client.get("/metrics")
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"error": "Yetkisiz erişim"}

    forbidden = client.get("/metrics", headers={"Authorization": "Bearer good-token"})
    assert forbidden.status_code == 403
    forbidden_body = forbidden.json()
    forbidden_message = forbidden_body.get("detail") or forbidden_body.get("error", "")
    assert "admin yetkisi" in forbidden_message or "METRICS_TOKEN" in forbidden_message

    invalid_payload = client.post(
        "/api/feedback/record",
        headers={"Authorization": "Bearer good-token"},
        json={"user_id": "u1", "prompt": "Merhaba"},
    )
    assert invalid_payload.status_code == 422

    mod.get_agent = lambda: asyncio.sleep(0, result=types.SimpleNamespace(
        cfg=types.SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
        docs=types.SimpleNamespace(doc_count=0),
        memory=types.SimpleNamespace(set_active_user=lambda *_a, **_k: asyncio.sleep(0), __len__=lambda self: 0),
        health=types.SimpleNamespace(
            get_health_summary=lambda: {"status": "ok", "ollama_online": True},
            get_dependency_health=lambda: (_ for _ in ()).throw(RuntimeError("redis/db offline")),
        ),
        VERSION="test",
    ))

    readiness = client.get("/readyz", headers={"Authorization": "Bearer admin-token"})
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "degraded"
    assert readiness.json()["dependencies"]["error"]["healthy"] is False


def test_fastapi_client_websocket_disconnect_does_not_crash(fastapi_web_mod):
    from fastapi.testclient import TestClient

    mod = fastapi_web_mod

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice", role="user")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield None

    async def _get_agent():
        return _Agent()

    mod.get_agent = _get_agent

    client = TestClient(mod.app)
    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_text('{"action":"auth","token":"good-token"}')
        websocket.send_text('{"action":"send","message":"merhaba"}')
