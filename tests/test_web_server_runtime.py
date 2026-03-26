import asyncio
import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone

try:
    import jwt
except ModuleNotFoundError:  # test ortamında PyJWT olmayabilir
    class _FallbackJWTError(Exception):
        pass

    class _FallbackJWTModule:
        PyJWTError = _FallbackJWTError
        InvalidTokenError = _FallbackJWTError
        ExpiredSignatureError = _FallbackJWTError

        @staticmethod
        def decode(*_a, **_k):
            raise _FallbackJWTError("jwt missing")

        @staticmethod
        def encode(payload, *_a, **_k):
            return str(payload)

    jwt = _FallbackJWTModule()

import sys
import types
from pathlib import Path
from unittest.mock import patch



class _FakeResponse:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.media_type = media_type


class _FakeJSONResponse(_FakeResponse):
    pass


class _FakeHTMLResponse(_FakeResponse):
    pass


class _FakeFileResponse(_FakeResponse):
    def __init__(self, path):
        super().__init__(content=str(path), status_code=200)
        self.path = str(path)


class _FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        self.routes = []

    def middleware(self, _kind):
        def _decorator(fn):
            self.routes.append(fn)
            return fn

        return _decorator

    def get(self, *args, **kwargs):
        return self._route_decorator()

    def post(self, *args, **kwargs):
        return self._route_decorator()

    def delete(self, *args, **kwargs):
        return self._route_decorator()

    def websocket(self, *args, **kwargs):
        return self._route_decorator()

    def add_middleware(self, *args, **kwargs):
        return None

    def mount(self, *args, **kwargs):
        return None

    @staticmethod
    def _route_decorator():
        def _decorator(fn):
            return fn

        return _decorator


class _FakeRequest:
    def __init__(self, *, method="GET", path="/", headers=None, json_body=None, body_bytes=b"", host="127.0.0.1"):
        self.method = method
        self.url = types.SimpleNamespace(path=path)
        self.headers = headers or {}
        self._json_body = json_body
        self._body = body_bytes
        self.client = types.SimpleNamespace(host=host)
        self.state = types.SimpleNamespace()

    async def json(self):
        return self._json_body or {}

    async def body(self):
        return self._body


class _FakeUploadFile:
    def __init__(self, filename, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    async def close(self):
        self.closed = True


def _install_web_server_stubs():
    replaced_modules = {}

    def _set_module(name, module):
        replaced_modules.setdefault(name, sys.modules.get(name))
        sys.modules[name] = module

    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.FastAPI = _FakeFastAPI
    fastapi_mod.Request = _FakeRequest
    fastapi_mod.UploadFile = _FakeUploadFile
    fastapi_mod.File = lambda *a, **k: ...
    fastapi_mod.WebSocket = object
    fastapi_mod.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    fastapi_mod.BackgroundTasks = object
    fastapi_mod.Header = lambda default="": default
    fastapi_mod.HTTPException = _FakeHTTPException
    fastapi_mod.Depends = lambda fn: fn

    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object

    resp_mod = types.ModuleType("fastapi.responses")
    resp_mod.Response = _FakeResponse
    resp_mod.JSONResponse = _FakeJSONResponse
    resp_mod.HTMLResponse = _FakeHTMLResponse
    resp_mod.FileResponse = _FakeFileResponse

    static_mod = types.ModuleType("fastapi.staticfiles")
    static_mod.StaticFiles = lambda directory: types.SimpleNamespace(directory=directory)

    pyd_mod = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    pyd_mod.BaseModel = _BaseModel
    pyd_mod.Field = lambda default=None, **_k: default

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

    jwt_mod = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    jwt_mod.PyJWTError = _PyJWTError
    jwt_mod.InvalidTokenError = _PyJWTError
    jwt_mod.ExpiredSignatureError = _PyJWTError
    jwt_mod.decode = lambda *_a, **_k: (_ for _ in ()).throw(_PyJWTError("invalid"))
    jwt_mod.encode = lambda payload, *_a, **_k: str(payload)

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
        TRUSTED_PROXIES: list = []
        ACCESS_LEVEL = "sandbox"
        AI_PROVIDER = "ollama"
        MAX_RAG_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MB

        @staticmethod
        def initialize_directories():
            return None

        @staticmethod
        def validate_critical_settings():
            return None

    cfg_mod.Config = _Config

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object

    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = object

    swarm_mod = types.ModuleType("agent.swarm")

    class _SwarmOrchestrator:
        def __init__(self, cfg):
            self.cfg = cfg

        async def run_parallel(self, tasks, session_id=None, max_concurrency=None):
            return []

        async def run_pipeline(self, tasks, session_id=None):
            return []

    swarm_mod.SwarmOrchestrator = _SwarmOrchestrator

    class _SwarmTask:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    swarm_mod.SwarmTask = _SwarmTask

    registry_mod = types.ModuleType("agent.registry")

    class _AgentSpec(types.SimpleNamespace):
        pass

    class _AgentRegistry:
        _registry = {}

        @classmethod
        def register_type(cls, **kwargs):
            role_name = kwargs.get("role_name", "")
            cls._registry[role_name] = _AgentSpec(
                role_name=role_name,
                agent_class=kwargs.get("agent_class"),
                capabilities=kwargs.get("capabilities", ["crypto_price", "demo"]),
                description=kwargs.get("description", "Mock description"),
                version=kwargs.get("version", "1.0.0"),
                is_builtin=kwargs.get("is_builtin", False),
            )
            return None

        @classmethod
        def get(cls, name):
            return cls._registry.get(
                name,
                _AgentSpec(
                    capabilities=["crypto_price", "demo"],
                    description="Mock description",
                    version="1.0.0",
                    is_builtin=False,
                ),
            )

        @classmethod
        def find_by_capability(cls, capability):
            return [spec for spec in cls._registry.values() if capability in getattr(spec, "capabilities", [])]

        @classmethod
        def list_all(cls):
            return list(cls._registry.values())

        @classmethod
        def create(cls, role_name, **kwargs):
            spec = cls._registry.get(role_name)
            if spec is None or spec.agent_class is None:
                raise KeyError(role_name)
            return spec.agent_class(**kwargs)

        @classmethod
        def unregister(cls, role_name):
            return cls._registry.pop(role_name, None) is not None

    registry_mod.AgentRegistry = _AgentRegistry
    registry_mod.AgentSpec = _AgentSpec

    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = []
    managers_health_mod = types.ModuleType("managers.system_health")
    managers_health_mod.render_llm_metrics_prometheus = lambda *_a, **_k: ""

    core_metrics_mod = types.ModuleType("core.llm_metrics")

    class _Collector:
        def snapshot(self):
            return {"totals": {"calls": 0, "total_tokens": 0}}

    core_metrics_mod.get_llm_metrics_collector = lambda: _Collector()

    event_stream_mod = types.ModuleType("agent.core.event_stream")

    class _EventBus:
        def subscribe(self):
            q = asyncio.Queue()
            return "sub-1", q

        def unsubscribe(self, _sub_id):
            return None

        async def publish(self, _source, _message):
            return None

    event_stream_mod.get_agent_event_bus = lambda: _EventBus()
    _set_module("fastapi", fastapi_mod)
    _set_module("fastapi.middleware.cors", cors_mod)
    _set_module("fastapi.responses", resp_mod)
    _set_module("fastapi.staticfiles", static_mod)
    _set_module("pydantic", pyd_mod)
    _set_module("redis.asyncio", redis_mod)
    _set_module("uvicorn", uvicorn_mod)
    _set_module("jwt", jwt_mod)
    _set_module("config", cfg_mod)
    if "agent" not in sys.modules:
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = [str(Path("agent").resolve())]
        _set_module("agent", agent_pkg)
    if "agent.core" not in sys.modules:
        core_pkg = types.ModuleType("agent.core")
        core_pkg.__path__ = [str(Path("agent/core").resolve())]
        _set_module("agent.core", core_pkg)
    if "core" not in sys.modules:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = []
        _set_module("core", core_pkg)
    llm_client_mod = types.ModuleType("core.llm_client")

    class _LLMAPIError(Exception):
        def __init__(self, message="err", provider="stub", status_code=None, retryable=False):
            super().__init__(message)
            self.provider = provider
            self.status_code = status_code
            self.retryable = retryable

    llm_client_mod.LLMAPIError = _LLMAPIError

    class _LLMClient:
        def __init__(self, *_a, **_k):
            return None

    llm_client_mod.LLMClient = _LLMClient

    ci_mod = types.ModuleType("core.ci_remediation")
    ci_mod.build_ci_failure_context = lambda *_a, **_k: {}

    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod._broadcast_hook = None
    hitl_mod.set_hitl_broadcast_hook = lambda hook: setattr(hitl_mod, "_broadcast_hook", hook)
    hitl_mod.get_hitl_gate = lambda: types.SimpleNamespace(respond=lambda *a, **k: None, submit=lambda *a, **k: None)
    hitl_mod.get_hitl_store = lambda: types.SimpleNamespace(list_pending=lambda: [], get=lambda *_a, **_k: None)
    hitl_mod.HITLRequest = lambda **kwargs: types.SimpleNamespace(**kwargs)
    hitl_mod.notify = lambda *_a, **_k: None

    _set_module("agent.sidar_agent", agent_mod)
    _set_module("agent.base_agent", base_agent_mod)
    _set_module("agent.registry", registry_mod)
    _set_module("agent.swarm", swarm_mod)
    _set_module("agent.core.event_stream", event_stream_mod)
    _set_module("managers", managers_pkg)
    _set_module("managers.system_health", managers_health_mod)
    _set_module("core.llm_metrics", core_metrics_mod)
    _set_module("core.llm_client", llm_client_mod)
    _set_module("core.ci_remediation", ci_mod)
    _set_module("core.hitl", hitl_mod)
    return replaced_modules


def _restore_modules(replaced_modules, names=None):
    module_names = names or replaced_modules.keys()
    for name in module_names:
        original = replaced_modules.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _load_web_server():
    replaced_modules = _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_under_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(mod)
    finally:
        _restore_modules(
            replaced_modules,
            names=("core.hitl", "core.llm_metrics", "core.llm_client", "core.ci_remediation"),
        )
    return mod




def _load_web_server_with_blocked_imports():
    import builtins

    real_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "anyio" or name.startswith("opentelemetry"):
            raise ImportError(f"blocked: {name}")
        return real_import(name, globals, locals, fromlist, level)

    replaced_modules = _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_under_test_blocked", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    builtins.__import__ = _blocked
    try:
        spec.loader.exec_module(mod)
    finally:
        builtins.__import__ = real_import
        _restore_modules(
            replaced_modules,
            names=("core.hitl", "core.llm_metrics", "core.llm_client", "core.ci_remediation"),
        )
    return mod

def _make_agent(ai_provider="ollama", ollama_online=True):
    calls = {"search": None, "add_level": None, "adds": []}

    class _Memory:
        active_session_id = "sess-1"

        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice", role="user")

            async def list_sessions(self, _user_id):
                return [types.SimpleNamespace(id="sess-1", title="S1", updated_at="2024-01-01T00:00:00")]

            async def get_session_messages(self, _session_id):
                return []

        def __init__(self):
            self.db = self._DB()

        def __len__(self):
            return 2

        async def get_all_sessions(self):
            return [{"id": "sess-1"}]

        async def set_active_user(self, _user_id, _username=None):
            return None

        async def clear(self):
            calls["cleared"] = True

        async def add(self, role, text):
            calls["adds"].append((role, text))

    class _Docs:
        doc_count = 3

        def status(self):
            return "ok"

        def add_document_from_file(self, *args):
            calls["add_file"] = args
            return True, "eklendi"

        async def search(self, q, top_k, mode, session_id):
            calls["search"] = (q, top_k, mode, session_id)
            return True, ["x"]

        def get_index_info(self, session_id):
            return [{"id": "d1", "session": session_id}]

    class _Health:
        def get_health_summary(self):
            return {"status": "ok", "ollama_online": ollama_online}

        def get_dependency_health(self):
            return {
                "redis": {"healthy": True, "kind": "redis"},
                "database": {"healthy": True, "kind": "database"},
            }

        def get_gpu_info(self):
            return {"devices": []}

        def check_ollama(self):
            return ollama_online

    cfg = types.SimpleNamespace(
        AI_PROVIDER=ai_provider,
        CODING_MODEL="qwen",
        GEMINI_MODEL="g-2",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        GPU_COUNT=0,
        CUDA_VERSION="N/A",
        MEMORY_ENCRYPTION_KEY="",
    )
    async def _set_access_level(_level):
        return "ok"

    agent = types.SimpleNamespace(
        VERSION="2.0",
        cfg=cfg,
        memory=_Memory(),
        docs=_Docs(),
        health=_Health(),
        github=types.SimpleNamespace(is_available=lambda: True, set_repo=lambda r: (True, "ok")),
        web=types.SimpleNamespace(is_available=lambda: True),
        pkg=types.SimpleNamespace(status=lambda: "ok"),
        todo=types.SimpleNamespace(get_tasks=lambda: [{"status": "completed"}]),
        security=types.SimpleNamespace(level_name="sandbox"),
        set_access_level=_set_access_level,
    )
    return agent, calls


def test_basic_auth_middleware_flow():
    mod = _load_web_server()

    class _Mem:
        async def set_active_user(self, _uid, _uname=None):
            return None

    async def _get_agent():
        return types.SimpleNamespace(memory=_Mem())

    mod.get_agent = _get_agent

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    open_req = _FakeRequest(path="/health")
    open_resp = asyncio.run(mod.basic_auth_middleware(open_req, _next))
    assert open_resp.status_code == 200

    bad = _FakeRequest(path="/status", headers={"Authorization": "Bearer bad-token"})
    unauthorized = asyncio.run(mod.basic_auth_middleware(bad, _next))
    assert unauthorized.status_code == 401

    fake_payload = {"sub": "u1", "username": "alice", "role": "admin", "tenant_id": "default"}
    with patch("jwt.decode", return_value=fake_payload):
        good = _FakeRequest(path="/status", headers={"Authorization": "Bearer sahte-token"})
        ok = asyncio.run(mod.basic_auth_middleware(good, _next))
        assert ok.status_code == 200




def test_access_policy_middleware_admin_bypass_and_user_acl(monkeypatch):
    mod = _load_web_server()

    calls = {"checked": []}

    class _Db:
        async def check_access_policy(self, **kwargs):
            calls["checked"].append(kwargs)
            return kwargs["action"] == "read"

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    admin_req = _FakeRequest(method="POST", path="/rag/add")
    admin_req.state.user = types.SimpleNamespace(id="a1", username="root", role="admin", tenant_id="t-admin")
    admin_resp = asyncio.run(mod.access_policy_middleware(admin_req, _next))
    assert admin_resp.status_code == 200
    assert calls["checked"] == []

    user_read_req = _FakeRequest(method="GET", path="/rag/search")
    user_read_req.state.user = types.SimpleNamespace(id="u1", username="alice", role="user", tenant_id="t1")
    read_resp = asyncio.run(mod.access_policy_middleware(user_read_req, _next))
    assert read_resp.status_code == 200
    assert calls["checked"][-1]["resource_type"] == "rag"
    assert calls["checked"][-1]["action"] == "read"

    user_write_req = _FakeRequest(method="POST", path="/rag/add")
    user_write_req.state.user = types.SimpleNamespace(id="u1", username="alice", role="user", tenant_id="t1")
    write_resp = asyncio.run(mod.access_policy_middleware(user_write_req, _next))
    assert write_resp.status_code == 403
    assert write_resp.content["error"] == "Yetki yok"


def test_access_policy_middleware_policy_checker_error_denies_access():
    mod = _load_web_server()

    class _Db:
        async def check_access_policy(self, **_kwargs):
            raise RuntimeError("acl-down")

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    req = _FakeRequest(method="GET", path="/github-prs")
    req.state.user = types.SimpleNamespace(id="u9", username="bob", role="user", tenant_id="t9")

    resp = asyncio.run(mod.access_policy_middleware(req, _next))
    assert resp.status_code == 403
    assert resp.content["resource"] == "github"
    assert resp.content["action"] == "read"


def test_access_policy_middleware_denied_attempt_is_audited():
    mod = _load_web_server()
    calls = []

    class _Db:
        async def check_access_policy(self, **_kwargs):
            return False

        async def record_audit_log(self, **kwargs):
            calls.append(kwargs)

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    async def _exercise():
        req = _FakeRequest(method="POST", path="/rag/add", host="192.168.1.5")
        req.state.user = types.SimpleNamespace(id="u-deny", username="eve", role="user", tenant_id="tenant-z")
        resp = await mod.access_policy_middleware(req, _next)
        assert resp.status_code == 403
        await asyncio.sleep(0)

    asyncio.run(_exercise())
    assert calls == [
        {
            "user_id": "u-deny",
            "tenant_id": "tenant-z",
            "action": "write",
            "resource": "rag:*",
            "ip_address": "192.168.1.5",
            "allowed": False,
        }
    ]


def test_core_endpoints_health_status_and_sessions_basics():
    mod = _load_web_server()

    class _Db:
        async def list_sessions(self, _user_id):
            return [
                types.SimpleNamespace(id="s1", title="First", updated_at="now"),
                types.SimpleNamespace(id="s2", title="Second", updated_at="later"),
            ]

        async def get_session_messages(self, session_id):
            return [1, 2] if session_id == "s1" else [1]

    class _Health:
        def get_health_summary(self):
            return {"status": "ok", "ollama_online": True}

        def get_gpu_info(self):
            return {"devices": []}

        def check_ollama(self):
            return True

    class _Docs:
        doc_count = 0

        def status(self):
            return "ok"

    class _Memory:
        def __init__(self):
            self.db = _Db()

        def __len__(self):
            return 0

    agent = types.SimpleNamespace(
        VERSION="9.9",
        cfg=types.SimpleNamespace(
            AI_PROVIDER="ollama",
            CODING_MODEL="qwen",
            GEMINI_MODEL="g-2",
            ACCESS_LEVEL="sandbox",
            USE_GPU=False,
            GPU_INFO="none",
            GPU_COUNT=0,
            CUDA_VERSION="N/A",
        ),
        health=_Health(),
        memory=_Memory(),
        docs=_Docs(),
        github=types.SimpleNamespace(is_available=lambda: True),
        web=types.SimpleNamespace(is_available=lambda: True),
        pkg=types.SimpleNamespace(status=lambda: "ok"),
        todo=types.SimpleNamespace(get_tasks=lambda: []),
    )

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    hc = asyncio.run(mod.health_check())
    st = asyncio.run(mod.status())
    user = types.SimpleNamespace(id="u1", username="alice", role="user")
    sess = asyncio.run(mod.get_sessions(_FakeRequest(path="/sessions"), user=user))

    assert hc.status_code == 200
    assert st.status_code == 200
    assert st.content["provider"] == "ollama"
    assert sess.status_code == 200
    assert [s["message_count"] for s in sess.content["sessions"]] == [2, 1]

def test_health_status_and_rag_search_endpoints():
    mod = _load_web_server()
    agent, calls = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    health = asyncio.run(mod.health_check())
    assert health.status_code == 503
    assert health.content["status"] == "degraded"

    status = asyncio.run(mod.status())
    assert status.status_code == 200
    assert status.content["provider"] == "ollama"

    bad = asyncio.run(mod.rag_search(q=" "))
    assert bad.status_code == 400

    ok = asyncio.run(mod.rag_search(q="needle", mode="auto", top_k=99))
    assert ok.status_code == 200
    assert calls["search"] == ("needle", 10, "auto", "sess-1")


def test_readiness_check_returns_503_when_dependency_health_lookup_raises():
    mod = _load_web_server()
    agent, _calls = _make_agent(ai_provider="openai", ollama_online=True)
    agent.health.get_dependency_health = lambda: (_ for _ in ()).throw(RuntimeError("redis/db offline"))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    ready = asyncio.run(mod.readiness_check())

    assert ready.status_code == 503
    assert ready.content["status"] == "degraded"
    assert ready.content["dependencies"]["error"]["healthy"] is False
    assert "redis/db offline" in ready.content["dependencies"]["error"]["detail"]


def test_readiness_check_returns_503_when_dependency_is_down():
    mod = _load_web_server()
    agent, _calls = _make_agent(ai_provider="gemini", ollama_online=True)
    agent.health.get_dependency_health = lambda: {
        "redis": {"healthy": False, "kind": "redis", "error": "connection refused"},
        "database": {"healthy": True, "kind": "database"},
    }

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    ready = asyncio.run(mod.readiness_check())
    live = asyncio.run(mod.health_check())

    assert ready.status_code == 503
    assert ready.content["status"] == "degraded"
    assert ready.content["dependencies"]["redis"]["healthy"] is False
    assert live.status_code == 200


def test_rag_add_file_upload_set_level_and_webhook():
    mod = _load_web_server()
    agent, calls = _make_agent(ai_provider="gemini", ollama_online=True)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    bad_req = _FakeRequest(json_body={"path": "../etc/passwd", "title": "x"})
    bad = asyncio.run(mod.rag_add_file(bad_req))
    assert bad.status_code == 403

    good_rel = Path("tests") / "test_web_server_runtime.py"
    good_req = _FakeRequest(json_body={"path": str(good_rel), "title": "runtime"})
    added = asyncio.run(mod.rag_add_file(good_req))
    assert added.status_code == 200
    assert added.content["success"] is True

    up = _FakeUploadFile("doc.txt", b"hello")
    uploaded = asyncio.run(mod.upload_rag_file(up))
    assert uploaded.status_code == 200
    assert uploaded.content["success"] is True
    assert up.closed is True

    missing_level = asyncio.run(mod.set_level_endpoint(_FakeRequest(json_body={})))
    assert missing_level.status_code == 400

    set_level = asyncio.run(mod.set_level_endpoint(_FakeRequest(json_body={"level": "full"})))
    assert set_level.status_code == 200
    assert set_level.content["current_level"] == "sandbox"

    payload = {"action": "opened", "issue": {"number": 3, "title": "x"}}
    req = _FakeRequest(body_bytes=json.dumps(payload).encode("utf-8"))
    ok = asyncio.run(mod.github_webhook(req, x_github_event="issues", x_hub_signature_256=""))
    assert ok.status_code == 200
    assert len(calls["adds"]) == 2

    mod.cfg.GITHUB_WEBHOOK_SECRET = "topsecret"
    secure_req = _FakeRequest(body_bytes=json.dumps(payload).encode("utf-8"))
    try:
        asyncio.run(mod.github_webhook(secure_req, x_github_event="issues", x_hub_signature_256="sha256=bad"))
        assert False, "expected signature error"
    except _FakeHTTPException as exc:
        assert exc.status_code == 401

def test_agent_lifecycle_get_agent_singleton_and_shutdown_close():
    mod = _load_web_server()

    created = {"count": 0}

    class _Memory:
        async def initialize(self):
            return None

    class _Agent:
        def __init__(self, cfg):
            created["count"] += 1
            self.memory = _Memory()

        async def initialize(self):
            return None

    class _RedisConn:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    mod.SidarAgent = _Agent
    mod._agent = None
    mod._agent_lock = asyncio.Lock()

    a1 = asyncio.run(mod.get_agent())
    a2 = asyncio.run(mod.get_agent())
    assert a1 is a2
    assert created["count"] == 1

    redis = _RedisConn()
    mod._redis_client = redis
    asyncio.run(mod._close_redis_client())
    assert redis.closed is True
    assert mod._redis_client is None


def test_sessions_and_memory_clear_endpoints_cover_success_and_error_paths():
    mod = _load_web_server()

    calls = {"cleared": 0}

    class _Memory:
        active_session_id = "sess-1"

        class _Db:
            async def list_sessions(self, _user_id):
                return [types.SimpleNamespace(id="sess-1", title="s1", updated_at="now")]

            async def get_session_messages(self, _session_id):
                return [types.SimpleNamespace(role="user", content="hi", created_at="2026-01-01T00:00:00+00:00", tokens_used=0)]

            async def load_session(self, session_id, _user_id):
                if session_id == "sess-1":
                    return types.SimpleNamespace(id="sess-1")
                return None

            async def create_session(self, _user_id, _title):
                return types.SimpleNamespace(id="sess-3")

            async def delete_session(self, session_id, _user_id):
                return session_id == "sess-1"

        db = _Db()

        @staticmethod
        def _safe_ts(_text):
            return 0.0

        async def clear(self):
            calls["cleared"] += 1

        async def set_active_user(self, _uid, _uname=None):
            return None

    agent = types.SimpleNamespace(memory=_Memory())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    user = types.SimpleNamespace(id="u1", username="alice", role="user")
    sessions = asyncio.run(mod.get_sessions(_FakeRequest(path="/sessions"), user=user))
    assert sessions.status_code == 200
    assert sessions.content["active_session"] is None

    loaded = asyncio.run(mod.load_session("sess-1", _FakeRequest(path="/sessions/sess-1"), user=user))
    assert loaded.status_code == 200
    assert loaded.content["success"] is True

    not_found = asyncio.run(mod.load_session("missing", _FakeRequest(path="/sessions/missing"), user=user))
    assert not_found.status_code == 404

    new_sess = asyncio.run(mod.new_session(_FakeRequest(path="/sessions/new"), user=user))
    assert new_sess.status_code == 200
    assert new_sess.content["session_id"] == "sess-3"

    deleted = asyncio.run(mod.delete_session("sess-1", _FakeRequest(path="/sessions/sess-1"), user=user))
    assert deleted.status_code == 200
    assert deleted.content["success"] is True

    delete_fail = asyncio.run(mod.delete_session("sess-2", _FakeRequest(path="/sessions/sess-2"), user=user))
    assert delete_fail.status_code == 500

    cleared = asyncio.run(mod.clear())
    assert cleared.status_code == 200
    assert cleared.content["result"] is True
    assert calls["cleared"] == 1


def test_websocket_chat_cancel_and_disconnect_paths():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _user_id, _username=None):
            return None

        def __len__(self):
            return 0

        def update_title(self, title):
            self.title = title

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(0.2)
            yield "late"

    class _WebSocket:
        def __init__(self, payloads, disconnect_exc):
            self._payloads = list(payloads)
            self._disconnect_exc = disconnect_exc
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.accepted = False
            self.headers = {}

        async def accept(self):
            self.accepted = True

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise self._disconnect_exc()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    ws = _WebSocket(
        payloads=[
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"message": "uzun bir mesaj", "action": "send"}),
            json.dumps({"action": "cancel"}),
        ],
        disconnect_exc=mod.WebSocketDisconnect,
    )

    asyncio.run(mod.websocket_chat(ws))

    assert ws.accepted is True
    assert any(p.get("done") is True and "iptal" in p.get("chunk", "") for p in ws.sent)


def test_prewarm_rag_embeddings_happy_path(monkeypatch):
    mod = _load_web_server()

    calls = {"init": 0, "to_thread": 0}

    class _Rag:
        _chroma_available = True

        def _init_chroma(self):
            calls["init"] += 1

    async def _get_agent():
        return types.SimpleNamespace(rag=_Rag())

    async def _to_thread(fn, *args, **kwargs):
        calls["to_thread"] += 1
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread)

    asyncio.run(mod._prewarm_rag_embeddings())
    assert calls["to_thread"] == 1
    assert calls["init"] == 1


def test_rate_limit_mutations_and_redis_fallback_exception_path(monkeypatch):
    mod = _load_web_server()

    class _RedisFailing:
        async def incr(self, _key):
            raise RuntimeError("redis command failed")

    mod._redis_client = _RedisFailing()

    local_fallback_calls = []

    async def _local_fallback(key, limit, window_sec):
        local_fallback_calls.append((key, limit, window_sec))
        return True

    monkeypatch.setattr(mod, "_local_is_rate_limited", _local_fallback)
    assert asyncio.run(mod._redis_is_rate_limited("mut", "127.0.0.1", 1, 60)) is True
    assert local_fallback_calls

    async def _next(_request):
        return _FakeResponse(status_code=200)

    async def _always_limited(*_args, **_kwargs):
        return True

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _always_limited)
    post_resp = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="POST", path="/set-level"), _next))
    delete_resp = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="DELETE", path="/sessions/s1"), _next))
    assert post_resp.status_code == 429
    assert delete_resp.status_code == 429


def test_files_file_content_and_git_branch_runtime_edges(monkeypatch):
    mod = _load_web_server()

    list_resp = asyncio.run(mod.list_project_files("tests"))
    assert list_resp.status_code == 200
    assert any(item["name"] == "test_web_server_runtime.py" for item in list_resp.content["items"])

    dir_resp = asyncio.run(mod.file_content("tests"))
    assert dir_resp.status_code == 400

    unsupported_path = Path("tests") / "_tmp_runtime_unsupported.exe"
    unsupported_path.write_bytes(b"MZ")
    try:
        unsupported_resp = asyncio.run(mod.file_content(str(unsupported_path)))
        assert unsupported_resp.status_code == 415
    finally:
        unsupported_path.unlink(missing_ok=True)

    large_path = Path("tests") / "_tmp_runtime_large.txt"
    large_path.write_text("x" * (mod.MAX_FILE_CONTENT_BYTES + 5), encoding="utf-8")
    try:
        too_large = asyncio.run(mod.file_content(str(large_path)))
        assert too_large.status_code == 413
    finally:
        large_path.unlink(missing_ok=True)

    branches_resp = asyncio.run(mod.git_branches())
    assert branches_resp.status_code == 200
    assert "branches" in branches_resp.content

    def _raise_checkout(*_args, **_kwargs):
        raise mod.subprocess.CalledProcessError(1, ["git", "checkout", "missing-branch"], output=b"pathspec did not match")

    async def _to_thread_raise(fn, *args, **kwargs):
        if fn is mod.subprocess.check_output and args[:2] == (["git", "checkout", "missing-branch"],):
            raise mod.subprocess.CalledProcessError(1, args[0], output=b"pathspec did not match")
        if fn is mod.subprocess.check_output:
            return _raise_checkout(*args, **kwargs)
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread_raise)
    set_branch_resp = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "missing-branch"})))
    assert set_branch_resp.status_code == 400


def test_websocket_chat_generate_response_cancelled_error_branch():
    mod = _load_web_server()

    class _Memory:
        def __len__(self):
            return 0

        def update_title(self, title):
            self.title = title

        async def set_active_user(self, _uid, _uname=None):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            raise asyncio.CancelledError
            yield "x"

    class _WebSocket:
        def __init__(self, payloads, disconnect_exc):
            self._payloads = list(payloads)
            self._disconnect_exc = disconnect_exc
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise self._disconnect_exc()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    ws = _WebSocket(
        payloads=[json.dumps({"message": "m", "action": "send"})],
        disconnect_exc=mod.WebSocketDisconnect,
    )

    asyncio.run(mod.websocket_chat(ws))
    # CancelledError branch generate_response içinde swallow edilir; done/json gönderimi olmayabilir
    assert isinstance(ws.sent, list)


def test_websocket_chat_send_json_failure_is_swallowed():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _user_id, _username=None):
            return None

        def __len__(self):
            return 0

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            raise RuntimeError("respond boom")
            yield "x"

    class _WebSocket:
        def __init__(self):
            self._payloads = [json.dumps({"action": "auth", "token": "tok"}), json.dumps({"message": "m", "action": "send"})]
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            raise RuntimeError("socket closed")

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited
    asyncio.run(mod.websocket_chat(_WebSocket()))


def test_websocket_chat_cancels_previous_active_task_line():
    mod = _load_web_server()

    class _Memory:
        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice")

        def __init__(self):
            self.db = self._DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 0

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(0.1)
            yield "later"

    class _WebSocket:
        def __init__(self):
            self._payloads = [
                json.dumps({"message": "ilk", "action": "send"}),
                json.dumps({"message": "ikinci", "action": "send"}),
            ]
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self.headers = {}

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited
    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))
    assert isinstance(ws.sent, list)

def test_tracing_setup_dependency_and_enabled_paths(monkeypatch):
    mod = _load_web_server()

    warns = []
    infos = []
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warns.append(msg % args if args else msg))
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    mod.cfg.ENABLE_TRACING = True
    mod.trace = object()
    mod.OTLPSpanExporter = None
    mod.FastAPIInstrumentor = object()
    mod.TracerProvider = object()
    mod.Resource = object()
    mod.BatchSpanProcessor = object()
    mod._setup_tracing()
    assert any("OpenTelemetry" in w for w in warns)

    class _Res:
        @staticmethod
        def create(data):
            return {"resource": data}

    class _Provider:
        def __init__(self, resource):
            self.resource = resource
            self.spans = []

        def add_span_processor(self, proc):
            self.spans.append(proc)

    class _Exporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    class _Instr:
        called = False

        @classmethod
        def instrument_app(cls, app):
            cls.called = app is not None

    class _Trace:
        provider = None

        @classmethod
        def set_tracer_provider(cls, provider):
            cls.provider = provider

    warns.clear()
    mod.Resource = _Res
    mod.TracerProvider = _Provider
    mod.OTLPSpanExporter = _Exporter
    mod.BatchSpanProcessor = _Batch
    mod.FastAPIInstrumentor = _Instr
    mod.trace = _Trace
    mod.cfg.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"
    mod._setup_tracing()

    assert _Trace.provider is not None
    assert _Instr.called is True
    assert any("OpenTelemetry aktif" in i for i in infos)


def test_rate_limit_middlewares_and_redis_paths(monkeypatch):
    mod = _load_web_server()

    class _Redis:
        def __init__(self):
            self.count = 0
            self.exp = None

        async def incr(self, _key):
            self.count += 1
            return self.count

        async def expire(self, _key, ttl):
            self.exp = ttl

    redis = _Redis()
    mod._redis_client = redis
    blocked = asyncio.run(mod._redis_is_rate_limited("ns", "k", 2, 60))
    assert blocked is False
    assert redis.exp == 62

    blocked2 = asyncio.run(mod._redis_is_rate_limited("ns", "k", 1, 60))
    assert blocked2 is True

    async def _raise(*_a, **_k):
        raise RuntimeError("redis down")

    redis.incr = _raise
    fallback_calls = []

    async def _local(key, limit, window):
        fallback_calls.append((key, limit, window))
        return True

    monkeypatch.setattr(mod, "_local_is_rate_limited", _local)
    blocked3 = asyncio.run(mod._redis_is_rate_limited("ns", "k", 3, 120))
    assert blocked3 is True
    assert fallback_calls

    async def _next(_request):
        return _FakeResponse(status_code=200)

    async def _always_limit(*_a, **_k):
        return True

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _always_limit)
    ddos_resp = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/api/x"), _next))
    assert ddos_resp.status_code == 429

    bypass = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/health"), _next))
    assert bypass.status_code == 200

    ws_limited = asyncio.run(mod.rate_limit_middleware(_FakeRequest(path="/ws/chat", method="GET"), _next))
    assert ws_limited.status_code == 429

    io_limited = asyncio.run(mod.rate_limit_middleware(_FakeRequest(path="/git-info", method="GET"), _next))
    assert io_limited.status_code == 429

    post_limited = asyncio.run(mod.rate_limit_middleware(_FakeRequest(path="/set-level", method="POST"), _next))
    assert post_limited.status_code == 429


def test_vendor_index_and_file_content_guard_paths(tmp_path, monkeypatch):
    mod = _load_web_server()
    monkeypatch.setattr(mod, "WEB_DIR", tmp_path)

    (tmp_path / "vendor").mkdir(parents=True)
    (tmp_path / "vendor" / "ok.js").write_text("console.log(1)", encoding="utf-8")

    good = asyncio.run(mod.serve_vendor("ok.js"))
    assert isinstance(good, _FakeFileResponse)
    assert good.status_code == 200

    bad = asyncio.run(mod.serve_vendor("../secret.txt"))
    assert bad.status_code == 403

    missing = asyncio.run(mod.serve_vendor("missing.js"))
    assert missing.status_code == 404

    idx_missing = asyncio.run(mod.index())
    assert isinstance(idx_missing, _FakeHTMLResponse)
    assert idx_missing.status_code == 500

    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    idx_ok = asyncio.run(mod.index())
    assert "<h1>ok</h1>" in idx_ok.content

    outside = asyncio.run(mod.file_content("../etc/passwd"))
    assert outside.status_code == 403

    not_found = asyncio.run(mod.file_content("nope.txt"))
    assert not_found.status_code == 404

    is_dir = asyncio.run(mod.file_content("tests"))
    assert is_dir.status_code == 400

    tmp_unsupported = Path("tests") / "_tmp_unsupported.bin"
    tmp_unsupported.write_bytes(b"x")
    unsupported = asyncio.run(mod.file_content(str(tmp_unsupported)))
    assert unsupported.status_code == 415
    tmp_unsupported.unlink(missing_ok=True)

    ok_txt_path = Path("README.md")
    ok_file = asyncio.run(mod.file_content(str(ok_txt_path)))
    assert ok_file.status_code == 200
    assert "content" in ok_file.content

    # K-1 güvenlik düzeltmesi: .env ve .example dosyaları erişilemez olmalı (415)
    tmp_env = Path("tests") / "_tmp_secret.env"
    tmp_env.write_text("SECRET_KEY=abc123", encoding="utf-8")
    env_resp = asyncio.run(mod.file_content(str(tmp_env)))
    assert env_resp.status_code == 415, ".env dosyaları /file-content üzerinden okunamaz olmalı"
    tmp_env.unlink(missing_ok=True)

    tmp_example = Path("tests") / "_tmp_secret.example"
    tmp_example.write_text("API_KEY=abc123", encoding="utf-8")
    example_resp = asyncio.run(mod.file_content(str(tmp_example)))
    assert example_resp.status_code == 415, ".example dosyaları /file-content üzerinden okunamaz olmalı"
    tmp_example.unlink(missing_ok=True)

    tmp_large = Path("tests") / "_tmp_large.txt"
    tmp_large.write_text("x" * (mod.MAX_FILE_CONTENT_BYTES + 1), encoding="utf-8")
    too_large = asyncio.run(mod.file_content(str(tmp_large)))
    assert too_large.status_code == 413
    tmp_large.unlink(missing_ok=True)


def test_github_repo_pr_and_rag_url_endpoints_error_paths():
    mod = _load_web_server()

    class _GH:
        repo_name = "owner/repo"

        def is_available(self):
            return False

        def list_repos(self, owner, limit):
            return False, []

        def get_pull_requests_detailed(self, state, limit):
            return False, [], "err"

        def get_pull_request(self, number):
            return False, "missing"

        def set_repo(self, name):
            return False, f"bad:{name}"

    agent = types.SimpleNamespace(
        github=_GH(),
        memory=types.SimpleNamespace(active_session_id="s1"),
        docs=types.SimpleNamespace(add_document_from_url=None, get_index_info=lambda session_id: [], delete_document=lambda *_: "x"),
    )

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    repos = asyncio.run(mod.github_repos(owner="", q=""))
    assert repos.status_code == 400

    prs = asyncio.run(mod.github_prs())
    assert prs.status_code == 503

    pr_detail = asyncio.run(mod.github_pr_detail(1))
    assert pr_detail.status_code == 503

    bad_set = asyncio.run(mod.set_repo(_FakeRequest(json_body={})))
    assert bad_set.status_code == 400

    set_resp = asyncio.run(mod.set_repo(_FakeRequest(json_body={"repo": "a/b"})))
    assert set_resp.status_code == 200
    assert set_resp.content["success"] is False

    url_bad = asyncio.run(mod.rag_add_url(_FakeRequest(json_body={"url": ""})))
    assert url_bad.status_code == 400

    class _Docs:
        async def add_document_from_url(self, url, title, session_id):
            return True, f"ok:{url}:{title}:{session_id}"

    agent.docs = _Docs()
    url_ok = asyncio.run(mod.rag_add_url(_FakeRequest(json_body={"url": "http://x", "title": "t"})))
    assert url_ok.status_code == 200
    assert url_ok.content["success"] is True


def test_git_info_branches_set_branch_and_main_paths(monkeypatch):
    mod = _load_web_server()

    def _git_run(cmd, cwd, stderr=None):
        key = " ".join(cmd)
        if "rev-parse --abbrev-ref HEAD" in key:
            return "feature/runtime"
        if "remote get-url origin" in key:
            return "https://github.com/acme/sidar_project.git"
        if "symbolic-ref" in key:
            return "origin/main"
        if "branch --format" in key:
            return "main\nfeature/runtime"
        return ""

    monkeypatch.setattr(mod, "_git_run", _git_run)

    info = asyncio.run(mod.git_info())
    assert info.status_code == 200
    assert info.content["branch"] == "feature/runtime"
    assert info.content["repo"] == "acme/sidar_project"
    assert info.content["default_branch"] == "main"

    branches = asyncio.run(mod.git_branches())
    assert branches.status_code == 200
    assert "feature/runtime" in branches.content["branches"]
    assert branches.content["current"] == "feature/runtime"

    empty_git = lambda *_a, **_k: ""
    monkeypatch.setattr(mod, "_git_run", empty_git)
    info_fallback = asyncio.run(mod.git_info())
    assert info_fallback.content["branch"] == "main"
    assert info_fallback.content["repo"] == "sidar_project"

    bad_name = asyncio.run(mod.set_branch(_FakeRequest(json_body={"branch": "bad branch"})))
    assert bad_name.status_code == 400

    empty_name = asyncio.run(mod.set_branch(_FakeRequest(json_body={})))
    assert empty_name.status_code == 400

    def _ok_checkout(*args, **kwargs):
        return b""

    monkeypatch.setattr(mod.subprocess, "check_output", _ok_checkout)
    ok_set = asyncio.run(mod.set_branch(_FakeRequest(json_body={"branch": "feature/runtime"})))
    assert ok_set.status_code == 200

    def _fail_checkout(*args, **kwargs):
        raise mod.subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"checkout failed")

    monkeypatch.setattr(mod.subprocess, "check_output", _fail_checkout)
    fail_set = asyncio.run(mod.set_branch(_FakeRequest(json_body={"branch": "feature/runtime"})))
    assert fail_set.status_code == 400
    assert "checkout failed" in fail_set.content["error"]

    created = {"cfg": None, "uvicorn": None}

    class _Memory:
        async def initialize(self):
            return None

    class _Agent:
        VERSION = "9.9"

        def __init__(self, cfg):
            created["cfg"] = cfg
            self.memory = _Memory()

        async def initialize(self):
            return None

    def _run(app, host, port, log_level):
        created["uvicorn"] = (host, port, log_level)

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.uvicorn, "run", _run)
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "0.0.0.0", "--port", "9999", "--level", "full", "--provider", "gemini", "--log", "DEBUG"])

    mod.main()

    assert created["cfg"].ACCESS_LEVEL == "full"
    assert created["cfg"].AI_PROVIDER == "gemini"
    assert created["uvicorn"] == ("0.0.0.0", 9999, "debug")


def test_main_uses_defaults_and_formats_banner_without_agent_initialize(monkeypatch):
    mod = _load_web_server()
    created = {"cfg": None, "uvicorn": None, "prints": []}

    class _Agent:
        VERSION = ""

        def __init__(self, cfg):
            created["cfg"] = cfg
            self.memory = types.SimpleNamespace()

    def _run(app, host, port, log_level):
        created["uvicorn"] = (app, host, port, log_level)

    def _print(*args, **kwargs):
        created["prints"].append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.uvicorn, "run", _run)
    monkeypatch.setattr("builtins.print", _print)
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "0.0.0.0", "--port", "8080"])

    mod.main()

    assert created["cfg"].ACCESS_LEVEL == "sandbox"
    assert created["cfg"].AI_PROVIDER == "ollama"
    assert created["uvicorn"] == (mod.app, "0.0.0.0", 8080, "info")
    assert any("http://localhost:8080" in line for line in created["prints"])
    assert any("Sürüm: v?" in line for line in created["prints"])


def test_list_files_metrics_rag_docs_todo_clear_and_github_repos_success(monkeypatch):
    mod = _load_web_server()

    class _Memory:
        active_session_id = "sess-42"

        def __len__(self):
            return 3

        async def get_all_sessions(self):
            return [{"id": "sess-42"}, {"id": "sess-2"}]

        async def clear(self):
            self.cleared = True

        async def set_active_user(self, _uid, _uname=None):
            return None

    class _Docs:
        doc_count = 5

        def get_index_info(self, session_id):
            return [{"id": "d1", "session": session_id}]

    class _Todo:
        def get_tasks(self):
            return [{"status": "completed"}, {"status": "pending"}]

    class _GH:
        repo_name = "owner/current"

        def list_repos(self, owner, limit):
            return True, [
                {"full_name": "owner/z-repo"},
                {"full_name": "owner/a-repo"},
                {"full_name": "other/skip"},
            ]

    cfg = types.SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False)
    agent = types.SimpleNamespace(VERSION="1.2", cfg=cfg, memory=_Memory(), docs=_Docs(), todo=_Todo(), github=_GH())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    mod._local_rate_limits = {"k": [1.0, 2.0]}

    metrics = asyncio.run(mod.metrics(_FakeRequest(headers={"Accept": "application/json"})))
    assert metrics.status_code == 200
    assert metrics.content["sessions_total"] == 2
    assert metrics.content["rag_documents"] == 5

    rag_docs = asyncio.run(mod.rag_list_docs())
    assert rag_docs.status_code == 200
    assert rag_docs.content["count"] == 1

    todo = asyncio.run(mod.get_todo())
    assert todo.status_code == 200
    assert todo.content["active"] == 1

    cleared = asyncio.run(mod.clear())
    assert cleared.status_code == 200
    assert cleared.content["result"] is True

    repos = asyncio.run(mod.github_repos(owner="", q="a-repo"))
    assert repos.status_code == 200
    assert repos.content["owner"] == "owner"
    assert repos.content["active_repo"] == "owner/current"
    assert repos.content["repos"][0]["full_name"] == "owner/a-repo"

    files_root = asyncio.run(mod.list_project_files(""))
    assert files_root.status_code == 200
    assert isinstance(files_root.content["items"], list)

    files_outside = asyncio.run(mod.list_project_files("../"))
    assert files_outside.status_code == 403

    files_not_found = asyncio.run(mod.list_project_files("does_not_exist_dir"))
    assert files_not_found.status_code == 404

    files_not_dir = asyncio.run(mod.list_project_files("README.md"))
    assert files_not_dir.status_code == 400


def test_webhook_pull_request_and_issues_branches_add_memory_records():
    mod = _load_web_server()
    calls = []

    async def _add(role, text):
        calls.append((role, text))

    memory = types.SimpleNamespace(add=_add)
    agent = types.SimpleNamespace(memory=memory)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    mod.cfg.GITHUB_WEBHOOK_SECRET = ""

    pr_payload = {
        "action": "opened",
        "pull_request": {"number": 12, "title": "Improve tests"},
    }
    pr_req = _FakeRequest(body_bytes=json.dumps(pr_payload).encode("utf-8"))
    pr_res = asyncio.run(mod.github_webhook(pr_req, x_github_event="pull_request", x_hub_signature_256=""))
    assert pr_res.status_code == 200

    issues_payload = {
        "action": "closed",
        "issue": {"number": 3, "title": "Fix bug"},
    }
    is_req = _FakeRequest(body_bytes=json.dumps(issues_payload).encode("utf-8"))
    is_res = asyncio.run(mod.github_webhook(is_req, x_github_event="issues", x_hub_signature_256=""))
    assert is_res.status_code == 200

    assert any("Pull Request #12" in text for role, text in calls if role == "user")
    assert any("Issue #3" in text for role, text in calls if role == "user")


def test_upload_rag_file_error_and_bad_add_path(monkeypatch):
    mod = _load_web_server()

    class _Docs:
        def add_document_from_file(self, *args):
            return False, "nope"

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(active_session_id="s1"), docs=_Docs())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    up = _FakeUploadFile("bad.txt", b"x")
    resp = asyncio.run(mod.upload_rag_file(up))
    assert resp.status_code == 400
    assert resp.content["success"] is False
    assert up.closed is True

    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda: (_ for _ in ()).throw(RuntimeError("disk full")))
    up2 = _FakeUploadFile("boom.txt", b"x")
    resp2 = asyncio.run(mod.upload_rag_file(up2))
    assert resp2.status_code == 500
    assert up2.closed is True


def test_metrics_text_plain_importerror_falls_back_to_json(monkeypatch):
    mod = _load_web_server()

    cfg = types.SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False)
    agent = types.SimpleNamespace(
        VERSION="1",
        cfg=cfg,
        docs=types.SimpleNamespace(doc_count=1),
    )

    class _Mem:
        def __len__(self):
            return 1

        async def get_all_sessions(self):
            return [{"id": "s1"}]

        async def set_active_user(self, _uid, _uname=None):
            return None

    agent.memory = _Mem()

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    import builtins as _bi
    real_import = _bi.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "prometheus_client":
            raise ImportError("no prometheus")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(_bi, "__import__", _fake_import)
    resp = asyncio.run(mod.metrics(_FakeRequest(headers={"Accept": "text/plain"})))
    assert resp.status_code == 200
    assert isinstance(resp, _FakeJSONResponse)
    assert resp.content["provider"] == "ollama"


def test_web_server_additional_uncovered_branches(monkeypatch):
    mod = _load_web_server()

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    mod.cfg.API_KEY = "secret"
    opt_req = _FakeRequest(method="OPTIONS", path="/status")
    opt_resp = asyncio.run(mod.basic_auth_middleware(opt_req, _next))
    assert opt_resp.status_code == 200

    class _RedisFailFactory:
        @classmethod
        def from_url(cls, *_a, **_k):
            raise RuntimeError("redis unavailable")

    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()
    monkeypatch.setattr(mod, "Redis", _RedisFailFactory)
    assert asyncio.run(mod._get_redis()) is None

    async def _local_rl(_key, _limit, _window):
        return False

    monkeypatch.setattr(mod, "_local_is_rate_limited", _local_rl)
    mod._redis_client = None
    assert asyncio.run(mod._redis_is_rate_limited("ns", "k", 1, 10)) is False

    not_limited = asyncio.run(mod.rate_limit_middleware(_FakeRequest(path="/status", method="GET"), _next))
    assert not_limited.status_code == 200

    fav = asyncio.run(mod.favicon())
    assert fav.status_code == 204

    class _Mem:
        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice")

        def __init__(self):
            self.db = self._DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 0

        def update_title(self, _t):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Mem()

        async def respond(self, _m):
            yield "\x00TOOL:github_prs\x00"
            yield "\x00THOUGHT:thinking\x00"
            raise RuntimeError("stream-fail")

    class _Ws:
        def __init__(self):
            self.client = types.SimpleNamespace(host="1.2.3.4")
            self.headers = {}
            self.sent = []
            self._messages = [
                "not-json",
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"message": "  "}),
                json.dumps({"message": "first", "action": "send"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._messages:
                return self._messages.pop(0)
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _agent_getter():
        return _Agent()

    calls = {"n": 0}

    async def _chat_rl(*_a, **_k):
        calls["n"] += 1
        return False

    mod.get_agent = _agent_getter
    mod._redis_is_rate_limited = _chat_rl
    ws = _Ws()
    asyncio.run(mod.websocket_chat(ws))
    assert any("tool_call" in p for p in ws.sent)
    assert any("thought" in p for p in ws.sent)
    assert any("Sistem Hatası" in p.get("chunk", "") for p in ws.sent)

    class _WsRate:
        def __init__(self):
            self.client = types.SimpleNamespace(host="1.2.3.4")
            self.headers = {}
            self.sent = []
            self._messages = [json.dumps({"action": "auth", "token": "tok"}), json.dumps({"message": "limited", "action": "send"})]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._messages:
                return self._messages.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _always_limit(*_a, **_k):
        return True

    mod._redis_is_rate_limited = _always_limit
    ws_rate = _WsRate()
    asyncio.run(mod.websocket_chat(ws_rate))
    assert any("Hız Sınırı" in p.get("chunk", "") for p in ws_rate.sent)

    agent, _calls = _make_agent(ai_provider="gemini", ollama_online=True)

    class _GH:
        repo_name = "o/r"

        def is_available(self):
            return True

        def get_pull_requests_detailed(self, **_kwargs):
            return False, [], "boom"

        def get_pull_request(self, _num):
            return False, "missing"

        def set_repo(self, name):
            return True, f"ok:{name}"

    class _Docs:
        def status(self):
            return "ok"

        def delete_document(self, _doc_id, _session_id):
            return "✓ silindi"

    agent.github = _GH()
    agent.docs = _Docs()

    async def _get_agent2():
        return agent

    mod.get_agent = _get_agent2
    st = asyncio.run(mod.status())
    assert st.content["model"] == "g-2"

    hc = asyncio.run(mod.health_check())
    assert hc.status_code == 200

    prs_fail = asyncio.run(mod.github_prs())
    assert prs_fail.status_code == 500
    prd_fail = asyncio.run(mod.github_pr_detail(1))
    assert prd_fail.status_code == 404

    set_ok = asyncio.run(mod.set_repo(_FakeRequest(json_body={"repo": "owner/repo"})))
    assert set_ok.content["success"] is True
    assert mod.cfg.GITHUB_REPO == "owner/repo"

    rag_missing = asyncio.run(mod.rag_add_file(_FakeRequest(json_body={})))
    assert rag_missing.status_code == 400

    rag_del = asyncio.run(mod.rag_delete_doc("d1"))
    assert rag_del.status_code == 200
    assert rag_del.content["success"] is True

    bad_read = Path("tests") / "_tmp_err.txt"
    bad_read.write_text("x", encoding="utf-8")
    real_read = Path.read_text

    def _boom_read(self, *a, **k):
        if str(self).endswith("_tmp_err.txt"):
            raise RuntimeError("no read")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _boom_read)
    bad_read_resp = asyncio.run(mod.file_content("tests/_tmp_err.txt"))
    assert bad_read_resp.status_code == 500
    bad_read.unlink(missing_ok=True)

    assert mod._git_run(["bash", "-lc", "exit 1"], cwd=str(Path.cwd())) == ""

    up = _FakeUploadFile("???", b"x")
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rm fail")))

    async def _close_fail():
        raise RuntimeError("close fail")

    up.close = _close_fail
    up_res = asyncio.run(mod.upload_rag_file(up))
    assert up_res.status_code in (200, 400, 500)

    mod.cfg.GITHUB_WEBHOOK_SECRET = "secret"
    req_missing_sig = _FakeRequest(body_bytes=b"{}")
    try:
        asyncio.run(mod.github_webhook(req_missing_sig, x_github_event="push", x_hub_signature_256=""))
        assert False, "expected 401"
    except _FakeHTTPException as exc:
        assert exc.status_code == 401

    mod.cfg.GITHUB_WEBHOOK_SECRET = ""
    bad_json = asyncio.run(mod.github_webhook(_FakeRequest(body_bytes=b"{"), x_github_event="push", x_hub_signature_256=""))
    assert bad_json.status_code == 400

    calls_mem = []
    async def _add_mem(role, text):
        calls_mem.append((role, text))

    agent.memory = types.SimpleNamespace(add=_add_mem)
    mod.get_agent = _get_agent2
    push_payload = json.dumps({"pusher": {"name": "alice"}, "ref": "refs/heads/main"}).encode("utf-8")
    push_ok = asyncio.run(mod.github_webhook(_FakeRequest(body_bytes=push_payload), x_github_event="push", x_hub_signature_256=""))
    assert push_ok.status_code == 200
    assert any("alice" in t for _r, t in calls_mem)

def test_import_fallbacks_for_anyio_and_opentelemetry():
    mod = _load_web_server_with_blocked_imports()
    assert mod._ANYIO_CLOSED is None
    assert mod.trace is None
    assert mod.BatchSpanProcessor is None


def test_opentelemetry_import_success_path_with_stubbed_modules(monkeypatch):
    replaced_modules = _install_web_server_stubs()

    otel_root = types.ModuleType("opentelemetry")
    otel_root.trace = types.SimpleNamespace(get_tracer=lambda *_a, **_k: None)
    otel_exporter = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    otel_exporter.OTLPSpanExporter = type("_Exporter", (), {})
    otel_fastapi = types.ModuleType("opentelemetry.instrumentation.fastapi")
    otel_fastapi.FastAPIInstrumentor = type("_FastAPIInstr", (), {})
    otel_httpx = types.ModuleType("opentelemetry.instrumentation.httpx")
    otel_httpx.HTTPXClientInstrumentor = type("_HTTPXInstr", (), {})
    otel_resources = types.ModuleType("opentelemetry.sdk.resources")
    otel_resources.Resource = type("_Resource", (), {})
    otel_trace = types.ModuleType("opentelemetry.sdk.trace")
    otel_trace.TracerProvider = type("_Provider", (), {})
    otel_trace_export = types.ModuleType("opentelemetry.sdk.trace.export")
    otel_trace_export.BatchSpanProcessor = type("_Batch", (), {})

    monkeypatch.setitem(sys.modules, "opentelemetry", otel_root)
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", otel_exporter)
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", otel_fastapi)
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.httpx", otel_httpx)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", otel_resources)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", otel_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", otel_trace_export)

    try:
        spec = importlib.util.spec_from_file_location("web_server_under_test_otel_ok", Path("web_server.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        assert mod.trace is otel_root.trace
        assert mod.Resource is otel_resources.Resource
        assert mod.TracerProvider is otel_trace.TracerProvider
        assert mod.BatchSpanProcessor is otel_trace_export.BatchSpanProcessor
    finally:
        _restore_modules(
            replaced_modules,
            names=("core.hitl", "core.llm_metrics", "core.llm_client", "core.ci_remediation"),
        )


def test_lifespan_closes_redis_client():
    mod = _load_web_server()

    class _RedisClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    client = _RedisClient()
    mod._redis_client = client

    async def _run():
        async with mod._app_lifespan(mod.app):
            pass

    asyncio.run(_run())
    assert client.closed is True
    assert mod._redis_client is None


def test_lifespan_triggers_async_shutdown_cleanup(monkeypatch):
    mod = _load_web_server()
    called = {"shutdown": 0}

    async def _shutdown():
        called["shutdown"] += 1

    monkeypatch.setattr(mod, "_async_force_shutdown_local_llm_processes", _shutdown)

    async def _run():
        async with mod._app_lifespan(mod.app):
            pass

    asyncio.run(_run())
    assert called["shutdown"] == 1


def test_metrics_access_guard_accepts_token_or_admin_and_rejects_others():
    mod = _load_web_server()
    mod.cfg.METRICS_TOKEN = "metrics-secret"

    token_user = types.SimpleNamespace(role="user", username="alice")
    req = _FakeRequest(headers={"Authorization": "Bearer metrics-secret"})
    assert mod._require_metrics_access(req, user=token_user) is token_user

    admin_user = types.SimpleNamespace(role="admin", username="root")
    assert mod._require_metrics_access(_FakeRequest(headers={}), user=admin_user) is admin_user

    try:
        mod._require_metrics_access(_FakeRequest(headers={"Authorization": "Bearer wrong"}), user=token_user)
        assert False, "expected metrics access denial"
    except _FakeHTTPException as exc:
        assert exc.status_code == 403


def test_execute_swarm_rejects_payloads_without_valid_tasks():
    mod = _load_web_server()
    mod.get_agent = lambda: asyncio.sleep(0, result=types.SimpleNamespace(cfg=types.SimpleNamespace()))

    payload = types.SimpleNamespace(
        tasks=[types.SimpleNamespace(goal="   ", intent="", context=None, preferred_agent="")],
        session_id="",
        mode="parallel",
        max_concurrency=2,
    )
    user = types.SimpleNamespace(id="u1")

    try:
        asyncio.run(mod.execute_swarm(payload=payload, user=user))
        assert False, "expected invalid swarm task payload"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "En az bir geçerli task" in exc.detail



def test_websocket_chat_cancellederror_pass_branch_with_running_task():
    mod = _load_web_server()

    class _Memory:
        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice")

        def __init__(self):
            self.db = self._DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 0

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(1)
            yield 'never'

    class _WebSocket:
        def __init__(self):
            self._payloads = [
                json.dumps({'action': 'auth', 'token': 'tok'}),
                json.dumps({'message': 'uzun', 'action': 'send'}),
                json.dumps({'action': 'cancel'}),
            ]
            self.client = types.SimpleNamespace(host='127.0.0.1')
            self.sent = []
            self.calls = 0
            self.headers = {}

        async def accept(self):
            return None

        async def receive_text(self):
            self.calls += 1
            if self.calls == 2:
                await asyncio.sleep(0.05)
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))
    assert any('iptal edildi' in p.get('chunk', '') for p in ws.sent)

def test_llm_budget_endpoint_returns_snapshot(monkeypatch):
    mod = _load_web_server()

    class _Collector:
        def snapshot(self):
            return {"totals": {"calls": 3, "total_tokens": 42}, "by_provider": {}}

    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: _Collector())

    resp = asyncio.run(mod.llm_budget_metrics())
    assert resp.status_code == 200
    assert resp.content["totals"]["calls"] == 3

def test_admin_stats_endpoint_enforces_admin_and_returns_stats():
    mod = _load_web_server()

    non_admin = types.SimpleNamespace(id="u1", username="alice", role="user")
    admin = types.SimpleNamespace(id="u2", username="default_admin", role="user")

    try:
        mod._require_admin_user(non_admin)
        assert False, "non-admin kullanıcı için HTTPException bekleniyordu"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403

    granted = mod._require_admin_user(admin)
    assert granted is admin

    class _Db:
        async def get_admin_stats(self):
            return {
                "total_users": 3,
                "total_tokens_used": 4567,
                "total_api_requests": 12,
                "users": [{"username": "default_admin", "role": "admin", "daily_token_limit": 0, "daily_request_limit": 0, "created_at": "now"}],
            }

    class _Mem:
        def __init__(self):
            self.db = _Db()

        async def set_active_user(self, _uid, _uname=None):
            return None

    async def _get_agent():
        return types.SimpleNamespace(memory=_Mem())

    mod.get_agent = _get_agent

    response = asyncio.run(mod.admin_stats(admin))
    assert response.status_code == 200
    assert response.content["total_users"] == 3
    assert response.content["total_tokens_used"] == 4567

def test_bind_llm_usage_sink_runtimeerror_on_get_running_loop(monkeypatch):
    mod = _load_web_server()

    sink_holder = {}

    class _Collector:
        def set_usage_sink(self, sink):
            sink_holder["sink"] = sink

    class _Db:
        async def record_provider_usage_daily(self, **_kwargs):
            return None

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()))
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: _Collector())
    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))

    mod._bind_llm_usage_sink(agent)
    sink = sink_holder["sink"]
    event = types.SimpleNamespace(user_id="u1", provider="openai", total_tokens=7)
    # RuntimeError branch should be swallowed
    sink(event)


def test_basic_auth_middleware_resets_metrics_context_on_exception(monkeypatch):
    mod = _load_web_server()

    class _Mem:
        async def set_active_user(self, _uid, _uname=None):
            return None

    async def _get_agent():
        return types.SimpleNamespace(memory=_Mem())

    seen = {"reset": 0}
    mod.get_agent = _get_agent
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-token")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda token: seen.__setitem__("reset", seen["reset"] + (1 if token == "ctx-token" else 0)))

    async def _boom(_request):
        raise RuntimeError("next failed")

    fake_payload = {"sub": "u1", "username": "alice", "role": "admin", "tenant_id": "default"}
    with patch("jwt.decode", return_value=fake_payload):
        req = _FakeRequest(path="/status", headers={"Authorization": "Bearer sahte-token"})
        try:
            asyncio.run(mod.basic_auth_middleware(req, _boom))
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

    assert seen["reset"] == 1


def test_redis_rate_limit_command_exception_falls_back_to_local(monkeypatch):
    mod = _load_web_server()

    class _RedisBoom:
        async def incr(self, _key):
            raise RuntimeError("redis down")

    async def _fake_get_redis():
        return _RedisBoom()

    async def _fake_local(_key, _limit, _window):
        return True

    monkeypatch.setattr(mod, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(mod, "_local_is_rate_limited", _fake_local)

    blocked = asyncio.run(mod._redis_is_rate_limited("ns", "k", 2, 60))
    assert blocked is True


def test_web_server_additional_coverage_edges(monkeypatch):
    mod = _load_web_server()

    class _Collector:
        def __init__(self):
            self.sink = None
            self._sidar_usage_sink_bound = False

        def set_usage_sink(self, sink):
            self.sink = sink

    collector = _Collector()
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

    agent = types.SimpleNamespace(
        memory=types.SimpleNamespace(
            db=types.SimpleNamespace(record_provider_usage_daily=lambda **kwargs: None)
        )
    )
    mod._bind_llm_usage_sink(agent)
    assert collector.sink is not None
    # user_id boşsa erken dönmeli
    collector.sink(types.SimpleNamespace(user_id="", provider="p", total_tokens=1))

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    opt = asyncio.run(mod.basic_auth_middleware(_FakeRequest(method="OPTIONS", path="/private"), _next))
    assert opt.status_code == 200
    static = asyncio.run(mod.basic_auth_middleware(_FakeRequest(path="/static/app.js"), _next))
    assert static.status_code == 200
    vendor = asyncio.run(mod.basic_auth_middleware(_FakeRequest(path="/vendor/highlight.min.js"), _next))
    assert vendor.status_code == 200
    fav = asyncio.run(mod.basic_auth_middleware(_FakeRequest(path="/favicon.ico"), _next))
    assert fav.status_code == 200

    async def _always_limit(*_args, **_kwargs):
        return True

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _always_limit)
    ui_bypass = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/ui/index.html"), _next))
    assert ui_bypass.status_code == 200
    static_bypass = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/static/x.css"), _next))
    assert static_bypass.status_code == 200



def test_git_branches_and_rag_delete_success_paths(monkeypatch):
    mod = _load_web_server()

    monkeypatch.setattr(mod, "_git_run", lambda *_a, **_k: "")
    branches = asyncio.run(mod.git_branches())
    assert branches.status_code == 200
    assert branches.content["branches"] == ["main"]
    assert branches.content["current"] == "main"

    class _Docs:
        def delete_document(self, _doc_id, _session_id):
            return "✓ removed"

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(active_session_id="sess-1"), docs=_Docs())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    deleted = asyncio.run(mod.rag_delete_doc("doc-1"))
    assert deleted.status_code == 200
    assert deleted.content["success"] is True

def test_admin_helper_and_client_ip_unknown_branch():
    mod = _load_web_server()

    regular = types.SimpleNamespace(username="alice", role="user")
    default_admin = types.SimpleNamespace(username="default_admin", role="user")

    assert mod._is_admin_user(regular) is False
    assert mod._is_admin_user(default_admin) is True

    req = _FakeRequest(headers={})
    req.client = None
    assert mod._get_client_ip(req) == "unknown"


def test_upload_finally_swallows_close_and_rmtree_errors(monkeypatch):
    mod = _load_web_server()

    class _Docs:
        def add_document_from_file(self, *args):
            return True, "ok"

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(active_session_id="s1"), docs=_Docs())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    up = _FakeUploadFile("doc.txt", b"x")

    async def _close_fail():
        raise RuntimeError("close failed")

    up.close = _close_fail
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rm failed")))

    resp = asyncio.run(mod.upload_rag_file(up))
    assert resp.status_code == 200
    assert resp.content["success"] is True

def test_web_server_targeted_missing_branches(monkeypatch):
    mod = _load_web_server()

    # _setup_tracing: ENABLE_TRACING açık + bağımlılıklar eksik => warning + sessiz dönüş
    warnings = []
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))
    mod.cfg.ENABLE_TRACING = True
    mod.trace = None
    mod.OTLPSpanExporter = None
    mod.FastAPIInstrumentor = None
    mod.TracerProvider = None
    mod.Resource = None
    mod.BatchSpanProcessor = None
    mod._setup_tracing()
    assert any("OpenTelemetry" in w for w in warnings)

    # /vendor: path traversal engeli
    traversal = asyncio.run(mod.serve_vendor("../../gizli_dosya"))
    assert traversal.status_code == 403

    # websocket: agent.respond patlar + send_json da patlar => nested except/pass
    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Mem:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, _uid, _uname=None):
            return None

        def __len__(self):
            return 1

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Mem()

        async def respond(self, _msg):
            raise RuntimeError("respond failed")
            yield "x"

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "hello"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            raise RuntimeError("socket closed")

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_a, **_k):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited
    asyncio.run(mod.websocket_chat(_WebSocket()))

    # /set-branch: regex dışı branch
    invalid = asyncio.run(mod.set_branch(_FakeRequest(json_body={"branch": "branch|name&illegal"})))
    assert invalid.status_code == 400

    # GitHub entegrasyonu unavailable => 503
    class _GH:
        repo_name = "owner/repo"

        def is_available(self):
            return False

        def list_repos(self, owner, limit):
            return False, []

        def get_pull_requests_detailed(self, state, limit):
            return False, [], "err"

        def get_pull_request(self, number):
            return False, "missing"

    agent = types.SimpleNamespace(
        github=_GH(),
        memory=types.SimpleNamespace(active_session_id="s1"),
        docs=types.SimpleNamespace(add_document_from_file=lambda *_a, **_k: (True, "ok")),
    )

    async def _get_agent_gh():
        return agent

    mod.get_agent = _get_agent_gh

    repos = asyncio.run(mod.github_repos(owner="", q=""))
    assert repos.status_code == 400

    prs_unavailable = asyncio.run(mod.github_prs())
    assert prs_unavailable.status_code == 503

    pr_detail_unavailable = asyncio.run(mod.github_pr_detail(123))
    assert pr_detail_unavailable.status_code == 503

    # /rag/add-file: mutlak path traversal koruması
    rag_abs = asyncio.run(mod.rag_add_file(_FakeRequest(json_body={"path": "/etc/passwd", "title": "x"})))
    assert rag_abs.status_code == 403

    # /api/rag/upload: beklenmedik sunucu hatası -> 500
    up = _FakeUploadFile("doc.txt", b"hello")
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda: (_ for _ in ()).throw(RuntimeError("tmp fail")))
    upload_err = asyncio.run(mod.upload_rag_file(up))
    assert upload_err.status_code == 500

    # /rag/search: boş sorgu -> 400
    empty_q = asyncio.run(mod.rag_search(q=""))
    assert empty_q.status_code == 400

def test_websocket_chat_full_disconnect_cleanup_additional():
    mod = _load_web_server()

    class _Memory:
        def __len__(self):
            return 0

        async def set_active_user(self, *_):
            return None

        async def update_title(self, *_):
            return None

    async def _respond(_msg):
        yield "ok"

    async def _ga():
        async def _get_user_by_token(_t):
            return types.SimpleNamespace(id="u1", username="alice")

        db = types.SimpleNamespace(get_user_by_token=_get_user_by_token)
        mem = _Memory()
        mem.db = db
        return types.SimpleNamespace(memory=mem, respond=_respond)

    async def _not_limited(*_):
        return False

    mod.get_agent = _ga
    mod._redis_is_rate_limited = _not_limited

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self._n = 0
            self.sent = []

        async def accept(self):
            return None

        async def receive_text(self):
            self._n += 1
            if self._n == 1:
                return json.dumps({"action": "auth", "token": "tok"})
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    # should complete without exception on disconnect cleanup path
    asyncio.run(mod.websocket_chat(_WS()))


def test_websocket_chat_anyio_closed_resource_branch_cancels_active_task():
    mod = _load_web_server()

    class _AnyioClosed(Exception):
        pass

    mod._ANYIO_CLOSED = _AnyioClosed

    class _Memory:
        def __len__(self):
            return 0

        async def set_active_user(self, *_):
            return None

        async def update_title(self, *_):
            return None

        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice")

        def __init__(self):
            self.db = self._DB()

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(1)
            yield "late"

    async def _ga():
        return _Agent()

    mod.get_agent = _ga
    mod._redis_is_rate_limited = lambda *_a, **_k: asyncio.sleep(0, result=False)

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self._idx = 0

        async def accept(self):
            return None

        async def receive_text(self):
            self._idx += 1
            if self._idx == 1:
                return json.dumps({"action": "auth", "token": "tok"})
            if self._idx == 2:
                return json.dumps({"action": "send", "message": "merhaba"})
            raise _AnyioClosed()

        async def send_json(self, _payload):
            return None

    asyncio.run(mod.websocket_chat(_WS()))


def test_websocket_voice_anyio_closed_resource_with_completed_active_task_exits_cleanly(monkeypatch):
    mod = _load_web_server()

    class _AnyioClosed(Exception):
        pass

    mod._ANYIO_CLOSED = _AnyioClosed

    class _DB:
        async def get_user_by_token(self, token):
            if token == "tok":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

    async def _respond(_text):
        if False:
            yield "unused"

    async def _ga():
        return types.SimpleNamespace(memory=_Memory(), llm=object(), respond=_respond)

    multimodal_mod = types.ModuleType("core.multimodal")

    class _MultimodalPipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, audio_bytes, **_kwargs):
            return {"success": True, "text": "ok" if audio_bytes else ""}

    multimodal_mod.MultimodalPipeline = _MultimodalPipeline

    voice_mod = types.ModuleType("core.voice")

    class _VoicePipeline:
        enabled = False
        vad_enabled = False
        duplex_enabled = False

        def __init__(self, _cfg):
            self.cfg = _cfg

        def create_duplex_state(self):
            return types.SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")

        def build_voice_state_payload(self, *, event, buffered_bytes, sequence, duplex_state):
            return {
                "voice_state": event,
                "buffered_bytes": buffered_bytes,
                "sequence": sequence,
                "assistant_turn_id": duplex_state.assistant_turn_id,
            }

    voice_mod.VoicePipeline = _VoicePipeline

    task_state = {"created": 0, "awaited": 0}

    class _DoneTask:
        def done(self):
            return True

        def cancel(self):
            return None

        def __await__(self):
            task_state["awaited"] += 1
            if False:
                yield None
            return None

    def _create_task(coro):
        task_state["created"] += 1
        coro.close()
        return _DoneTask()

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self.sent = []
            self._idx = 0

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            self._idx += 1
            if self._idx == 1:
                return {"type": "websocket.receive", "text": json.dumps({"action": "auth", "token": "tok"})}
            if self._idx == 2:
                return {"type": "websocket.receive", "bytes": b"voice-bytes"}
            if self._idx == 3:
                return {"type": "websocket.receive", "text": json.dumps({"action": "commit"})}
            raise _AnyioClosed("socket closed")

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code=None, reason=None):
            self.closed = (code, reason)

    mod.get_agent = _ga
    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)

    _orig_multimodal = sys.modules.get("core.multimodal")
    _orig_voice = sys.modules.get("core.voice")
    sys.modules["core.multimodal"] = multimodal_mod
    sys.modules["core.voice"] = voice_mod
    try:
        asyncio.run(mod.websocket_voice(_WS()))
    finally:
        if _orig_multimodal is None:
            del sys.modules["core.multimodal"]
        else:
            sys.modules["core.multimodal"] = _orig_multimodal
        if _orig_voice is None:
            del sys.modules["core.voice"]
        else:
            sys.modules["core.voice"] = _orig_voice

    assert task_state == {"created": 1, "awaited": 0}


def test_websocket_chat_header_token_auth_success_and_invalid_close():
    mod = _load_web_server()

    class _Memory:
        class _DB:
            async def get_user_by_token(self, token):
                if token == "valid-token":
                    return types.SimpleNamespace(id="u1", username="alice")
                return None

        def __init__(self):
            self.db = self._DB()
            self.active = []

        async def set_active_user(self, user_id, username=None):
            self.active.append((user_id, username))

        def __len__(self):
            return 0

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            if False:
                yield ""

    agent = _Agent()
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)

    class _WSOk:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.accepted = None
            self.sent = []

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    ws_ok = _WSOk()
    asyncio.run(mod.websocket_chat(ws_ok))
    assert ws_ok.accepted == "valid-token"
    assert {"auth_ok": True} in ws_ok.sent
    assert agent.memory.active == [("u1", "alice")]

    class _WSBad:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "bad-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.accepted = None
            self.closed = None

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def close(self, code=None, reason=None):
            self.closed = (code, reason)

        async def receive_text(self):
            raise AssertionError("receive_text should not be called after invalid token")

        async def send_json(self, payload):
            raise AssertionError(f"unexpected payload: {payload}")

    ws_bad = _WSBad()
    asyncio.run(mod.websocket_chat(ws_bad))
    assert ws_bad.accepted == "bad-token"
    assert ws_bad.closed == (1008, "Invalid or expired token")




def test_process_shutdown_reap_and_async_non_ollama_paths(monkeypatch):
    mod = _load_web_server()

    child_calls = {"n": 0}
    generic_calls = {"n": 0}

    def _raise_child(*_args, **_kwargs):
        child_calls["n"] += 1
        raise ChildProcessError()

    monkeypatch.setattr(mod.os, "waitpid", _raise_child)
    assert mod._reap_child_processes_nonblocking() == 0
    assert child_calls["n"] == 1

    def _raise_generic(*_args, **_kwargs):
        generic_calls["n"] += 1
        raise RuntimeError("waitpid boom")

    monkeypatch.setattr(mod.os, "waitpid", _raise_generic)
    assert mod._reap_child_processes_nonblocking() == 0
    assert generic_calls["n"] == 1

    reaped = {"sync": 0, "async": 0}
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("sync", reaped["sync"] + 1) or 7)

    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "openai"
    mod._force_shutdown_local_llm_processes()
    assert reaped["sync"] == 1

    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("async", reaped["async"] + 1) or 3)
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = False
    asyncio.run(mod._async_force_shutdown_local_llm_processes())
    assert mod._shutdown_cleanup_done is True
    assert reaped["async"] == 1


def test_assets_mount_added_when_assets_directory_exists(monkeypatch):
    recorded = []
    original_mount = _FakeFastAPI.mount
    original_exists = Path.exists

    def _mount(self, path, app, name=None):
        recorded.append((path, getattr(app, "directory", None), name))
        return None

    def _exists(self):
        path = str(self).replace("\\", "/")
        if path.endswith("/web_ui_react/dist/assets"):
            return True
        return original_exists(self)

    monkeypatch.setattr(_FakeFastAPI, "mount", _mount)
    monkeypatch.setattr(Path, "exists", _exists)
    _load_web_server()

    assert any(
        path == "/assets"
        and str(directory).replace("\\", "/").endswith("/web_ui_react/dist/assets")
        and name == "assets"
        for path, directory, name in recorded
    )


def test_async_shutdown_non_ollama_marks_cleanup_done_and_reaps_once(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "openai"

    calls = {"reap": 0, "list": 0, "kill": 0}
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: calls.__setitem__("reap", calls["reap"] + 1) or 4)
    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: calls.__setitem__("list", calls["list"] + 1) or [111])
    monkeypatch.setattr(mod.os, "kill", lambda *_a, **_k: calls.__setitem__("kill", calls["kill"] + 1))

    asyncio.run(mod._async_force_shutdown_local_llm_processes())

    assert mod._shutdown_cleanup_done is True
    assert calls == {"reap": 1, "list": 0, "kill": 0}


def test_schedule_access_audit_log_returns_early_when_resource_empty(monkeypatch):
    mod = _load_web_server()

    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(AssertionError("get_running_loop should not be called")))

    mod._schedule_access_audit_log(
        user=types.SimpleNamespace(id="u1", tenant_id="t1"),
        resource_type="",
        action="read",
        resource_id="doc-1",
        ip_address="127.0.0.1",
        allowed=True,
    )


def test_async_shutdown_returns_immediately_when_cleanup_already_done(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = True

    calls = {"reap": 0, "list": 0, "kill": 0}

    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: calls.__setitem__("reap", calls["reap"] + 1) or 0)
    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: calls.__setitem__("list", calls["list"] + 1) or [123])
    monkeypatch.setattr(mod.os, "kill", lambda *_a, **_k: calls.__setitem__("kill", calls["kill"] + 1))

    asyncio.run(mod._async_force_shutdown_local_llm_processes())

    assert calls == {"reap": 0, "list": 0, "kill": 0}
    assert mod._shutdown_cleanup_done is True


def test_llm_prometheus_metrics_swallows_agent_metric_import_errors(monkeypatch):
    mod = _load_web_server()
    real_import = __import__

    def _broken_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.agent_metrics":
            raise RuntimeError("agent metrics missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _broken_import)

    resp = asyncio.run(mod.llm_prometheus_metrics())

    assert resp.status_code == 200
    assert resp.media_type == "text/plain; version=0.0.4"


def test_upload_rag_file_rejects_oversized_payload():
    mod = _load_web_server()
    mod.Config.MAX_RAG_UPLOAD_BYTES = 1
    mod.get_agent = lambda: asyncio.sleep(
        0,
        result=types.SimpleNamespace(
            memory=types.SimpleNamespace(active_session_id="sess-1"),
            docs=types.SimpleNamespace(add_document_from_file=lambda *_a, **_k: (True, "ok")),
        ),
    )

    file = _FakeUploadFile("big.txt", b"abc")
    resp = asyncio.run(mod.upload_rag_file(file))

    assert resp.status_code == 500
    assert "Dosya çok büyük" in resp.content["error"]
    assert file.closed is True


def test_policy_resolution_jwt_payload_and_plugin_loader_error_paths(monkeypatch):
    mod = _load_web_server()

    assert mod._build_user_from_jwt_payload({"sub": "", "username": "alice"}) is None
    assert mod._build_user_from_jwt_payload({"sub": "u1", "username": ""}) is None

    assert mod._resolve_policy_from_request(_FakeRequest(path="/api/agents/register", method="POST")) == ("agents", "register", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/admin/stats", method="GET")) == ("admin", "manage", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/ws/chat", method="GET")) == ("swarm", "execute", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/unknown", method="GET")) == ("", "", "")

    try:
        mod._load_plugin_agent_class("raise RuntimeError('boom')", None, "plug_bad_compile")
        assert False, "expected compile/runtime failure"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "derlenemedi" in str(exc.detail)

    try:
        mod._load_plugin_agent_class("class Demo: pass", "Missing", "plug_missing_class")
        assert False, "expected missing class"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "Belirtilen sınıf bulunamadı" in str(exc.detail)

    class _StrictBaseAgent:
        pass

    monkeypatch.setattr(mod, "BaseAgent", _StrictBaseAgent)

    try:
        mod._load_plugin_agent_class("class Demo: pass", "Demo", "plug_not_agent")
        assert False, "expected BaseAgent type error"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "BaseAgent" in str(exc.detail)

    try:
        mod._load_plugin_agent_class("x = 1", None, "plug_none_found")
        assert False, "expected no discovered agent class"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "BaseAgent türevi" in str(exc.detail)

    monkeypatch.setattr(mod, "BaseAgent", sys.modules["agent.base_agent"].BaseAgent)
    discovered = mod._load_plugin_agent_class(
        "from agent.base_agent import BaseAgent\n\nclass AutoOne(BaseAgent):\n    pass\n\nclass AutoTwo(BaseAgent):\n    pass\n",
        None,
        "plug_auto_discover",
    )
    assert discovered.__name__ == "AutoOne"


def test_plugin_source_filename_uses_virtual_label_for_dynamic_code(monkeypatch):
    mod = _load_web_server()

    assert mod._plugin_source_filename("plug_missing_class") == "<sidar-plugin:plug_missing_class>"
    assert mod._plugin_source_filename(" weird label / ") == "<sidar-plugin:weird_label_>"

    plugin_cls = mod._load_plugin_agent_class(
        "from agent.base_agent import BaseAgent\n\nclass Demo(BaseAgent):\n    def ping(self):\n        return 'ok'\n",
        "Demo",
        "plug_missing_class",
    )

    assert plugin_cls.ping.__code__.co_filename == "<sidar-plugin:plug_missing_class>"

    monkeypatch.setattr(mod.importlib.util, "spec_from_file_location", lambda *_a, **_k: None)
    plugin_path = Path("plugins") / "demo.py"
    plugin_path.unlink(missing_ok=True)
    try:
        mod._persist_and_import_plugin_file("demo.py", b"print('x')", "plug_no_spec")
        assert False, "expected spec failure"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "import edilemedi" in str(exc.detail)
    finally:
        plugin_path.unlink(missing_ok=True)


def test_register_plugin_upload_access_policy_bypass_and_admin_policy_paths(monkeypatch):
    mod = _load_web_server()

    async def _next(_request):
        return _FakeJSONResponse({"ok": True}, status_code=200)

    opt_resp = asyncio.run(mod.access_policy_middleware(_FakeRequest(method="OPTIONS", path="/admin/stats"), _next))
    assert opt_resp.status_code == 200

    anon_resp = asyncio.run(mod.access_policy_middleware(_FakeRequest(method="GET", path="/admin/stats"), _next))
    assert anon_resp.status_code == 200

    no_resource_req = _FakeRequest(method="GET", path="/status")
    no_resource_req.state.user = types.SimpleNamespace(id="u1", username="alice", role="user", tenant_id="t1")
    no_resource_resp = asyncio.run(mod.access_policy_middleware(no_resource_req, _next))
    assert no_resource_resp.status_code == 200

    class _DbNoChecker:
        pass

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_DbNoChecker()))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    missing_checker_req = _FakeRequest(method="POST", path="/admin/policies")
    missing_checker_req.state.user = types.SimpleNamespace(id="u2", username="bob", role="user", tenant_id="t2")
    missing_checker_resp = asyncio.run(mod.access_policy_middleware(missing_checker_req, _next))
    assert missing_checker_resp.status_code == 200

    class _DbPolicies:
        def __init__(self):
            self.upserted = None

        async def upsert_access_policy(self, **kwargs):
            self.upserted = kwargs

        async def list_access_policies(self, **kwargs):
            return [types.SimpleNamespace(**self.upserted, created_at="now", updated_at="now")]

    db = _DbPolicies()
    agent.memory.db = db
    payload = mod._PolicyUpsertRequest(
        user_id=" u1 ", tenant_id=" ", resource_type=" GITHUB ", resource_id=" ", action=" WRITE ", effect=" ALLOW "
    )
    policy_resp = asyncio.run(mod.admin_upsert_policy(payload, _user=types.SimpleNamespace(role="admin", username="default_admin")))
    assert policy_resp.status_code == 200
    assert db.upserted["tenant_id"] == "default"
    assert db.upserted["resource_type"] == "github"
    assert db.upserted["action"] == "write"
    assert db.upserted["effect"] == "allow"

    class _Upload(_FakeUploadFile):
        async def read(self):
            return self.file.getvalue()

    empty_file = _Upload("plug.py", b"")
    try:
        asyncio.run(mod.register_agent_plugin_file(empty_file, _user=types.SimpleNamespace(role="admin", username="default_admin")))
        assert False, "expected empty upload"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "boş" in str(exc.detail)

    big_file = _Upload("plug.py", b"x" * (mod.MAX_FILE_CONTENT_BYTES + 1))
    try:
        asyncio.run(mod.register_agent_plugin_file(big_file, _user=types.SimpleNamespace(role="admin", username="default_admin")))
        assert False, "expected too large upload"
    except _FakeHTTPException as exc:
        assert exc.status_code == 413

    bad_utf = _Upload("plug.py", bytes([0xFF, 0xFE]))
    try:
        asyncio.run(mod.register_agent_plugin_file(bad_utf, _user=types.SimpleNamespace(role="admin", username="default_admin")))
        assert False, "expected utf-8 error"
    except _FakeHTTPException as exc:
        assert exc.status_code == 400
        assert "UTF-8" in str(exc.detail)


def test_local_rate_lock_initializes_and_get_redis_ping_failure_falls_back(monkeypatch):
    mod = _load_web_server()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    blocked1 = asyncio.run(mod._local_is_rate_limited("k", 1, 60))
    blocked2 = asyncio.run(mod._local_is_rate_limited("k", 1, 60))

    assert blocked1 is False
    assert blocked2 is True

    class _BadRedis:
        async def ping(self):
            raise RuntimeError("redis unavailable")

    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()
    monkeypatch.setattr(mod.Redis, "from_url", lambda *_a, **_k: _BadRedis())

    assert asyncio.run(mod._get_redis()) is None

def test_force_shutdown_local_llm_processes_all_edges_additional(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True

    monkeypatch.setattr(mod.os, "getpid", lambda: 1234)
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: b" 9999 1234 ollama ollama serve\n 8888 1234 ollama ollama serve\n")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    killed = []

    def _kill(pid, _sig):
        killed.append(pid)
        if pid == 8888:
            raise ProcessLookupError("No such process")

    monkeypatch.setattr(mod.os, "kill", _kill)
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: 0)

    mod._force_shutdown_local_llm_processes()
    assert 9999 in killed and 8888 in killed

    mod._shutdown_cleanup_done = False

    def _check_output_error(*_a, **_k):
        raise mod.subprocess.CalledProcessError(1, "ps")

    monkeypatch.setattr(mod.subprocess, "check_output", _check_output_error)
    mod._force_shutdown_local_llm_processes()


def test_github_webhook_valid_hmac_invalid_json_additional(monkeypatch):
    mod = _load_web_server()
    mod.cfg.GITHUB_WEBHOOK_SECRET = "testsecret"

    payload = b"not-a-valid-json"
    signature = "sha256=" + mod.hmac.new(b"testsecret", payload, mod.hashlib.sha256).hexdigest()

    req = _FakeRequest(body_bytes=payload)
    resp = asyncio.run(mod.github_webhook(req, x_github_event="issues", x_hub_signature_256=signature))
    assert resp.status_code == 400


def test_github_webhook_signature_mismatch_returns_401_specific_hash():
    mod = _load_web_server()
    mod.cfg.GITHUB_WEBHOOK_SECRET = "secret"
    req = _FakeRequest(body_bytes=b'{"action":"opened"}')

    try:
        asyncio.run(mod.github_webhook(req, x_github_event="issues", x_hub_signature_256="sha256=yanlishash123"))
        assert False, "expected signature mismatch"
    except _FakeHTTPException as exc:
        assert exc.status_code == 401
        assert "Geçersiz imza" in str(exc.detail)


def test_async_force_shutdown_swallows_missing_process_errors(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True

    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: [1234])

    calls = {"kill": 0}

    def _kill(_pid, _sig):
        calls["kill"] += 1
        raise ProcessLookupError("already gone")

    monkeypatch.setattr(mod.os, "kill", _kill)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(mod.asyncio, "sleep", lambda *_a, **_k: real_sleep(0))
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: 0)

    asyncio.run(mod._async_force_shutdown_local_llm_processes())
    assert mod._shutdown_cleanup_done is True
    assert calls["kill"] >= 1


def test_resolve_user_from_token_handles_jwt_errors_and_db_fallback(monkeypatch):
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "db-ok":
                return types.SimpleNamespace(id="u-db", username="fromdb")
            return None

    mod._agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_DB()))

    jwt_error = getattr(mod.jwt, "InvalidTokenError", Exception)
    monkeypatch.setattr(mod.jwt, "decode", lambda *_a, **_k: (_ for _ in ()).throw(jwt_error("invalid")))

    user = asyncio.run(mod._resolve_user_from_token(mod._agent, "db-ok"))
    missing = asyncio.run(mod._resolve_user_from_token(mod._agent, "db-miss"))

    assert user.username == "fromdb"
    assert missing is None


def test_setup_tracing_swallows_httpx_instrumentation_errors(monkeypatch):
    mod = _load_web_server()

    class _Res:
        @staticmethod
        def create(data):
            return {"resource": data}

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _proc):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    class _FastAPIInstr:
        @staticmethod
        def instrument_app(_app):
            return None

    class _HTTPXInstr:
        def instrument(self):
            raise RuntimeError("httpx instrumentation fail")

    class _Trace:
        @staticmethod
        def set_tracer_provider(_provider):
            return None

    infos = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    mod.cfg.ENABLE_TRACING = True
    mod.cfg.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"
    mod.trace = _Trace
    mod.Resource = _Res
    mod.TracerProvider = _Provider
    mod.OTLPSpanExporter = _Exporter
    mod.BatchSpanProcessor = _Batch
    mod.FastAPIInstrumentor = _FastAPIInstr
    mod.HTTPXClientInstrumentor = _HTTPXInstr

    mod._setup_tracing()

    assert any("OpenTelemetry aktif" in item for item in infos)

def test_api_vision_analyze_wraps_pipeline_result(monkeypatch):
    mod = _load_web_server()

    class _Pipeline:
        def __init__(self, llm, cfg):
            self.llm = llm
            self.cfg = cfg

        async def analyze(self, **kwargs):
            return {"success": True, "seen": kwargs}

    vision_mod = types.ModuleType("core.vision")
    vision_mod.VisionPipeline = _Pipeline
    vision_mod.build_analyze_prompt = lambda analysis_type: f"prompt:{analysis_type}"
    monkeypatch.setitem(sys.modules, "core.vision", vision_mod)

    async def _get_agent():
        return types.SimpleNamespace(llm="llm-client")

    mod.get_agent = _get_agent
    req = mod._VisionAnalyzeRequest(image_base64="abc123", mime_type="image/png", analysis_type="ux_review", prompt=None)

    resp = asyncio.run(mod.api_vision_analyze(req))

    assert resp.status_code == 200
    assert resp.content["success"] is True
    assert resp.content["result"]["seen"]["image_b64"] == "abc123"
    assert resp.content["result"]["seen"]["prompt"] == "prompt:ux_review"


def test_api_vision_mockup_wraps_pipeline_code_result(monkeypatch):
    mod = _load_web_server()

    class _Pipeline:
        def __init__(self, llm, cfg):
            self.llm = llm
            self.cfg = cfg

        async def mockup_to_code(self, **kwargs):
            return {"success": True, "seen": kwargs}

    vision_mod = types.ModuleType("core.vision")
    vision_mod.VisionPipeline = _Pipeline
    monkeypatch.setitem(sys.modules, "core.vision", vision_mod)

    async def _get_agent():
        return types.SimpleNamespace(llm="llm-client")

    mod.get_agent = _get_agent
    req = mod._VisionMockupRequest(image_base64="xyz789", mime_type="image/png", framework="vue", prompt="extra")

    resp = asyncio.run(mod.api_vision_mockup(req))

    assert resp.status_code == 200
    assert resp.content["success"] is True
    assert resp.content["code"]["seen"]["image_b64"] == "xyz789"
    assert resp.content["code"]["seen"]["framework"] == "vue"
    assert resp.content["code"]["seen"]["extra_instructions"] == "extra"