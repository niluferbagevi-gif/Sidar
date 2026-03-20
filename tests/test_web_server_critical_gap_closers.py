import subprocess
import asyncio
import importlib.util
import sys
import types
from pathlib import Path


def _load_web_server_module():
    fastapi_mod = types.ModuleType("fastapi")

    class _FastAPI:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def middleware(self, _kind):
            def _dec(fn):
                return fn

            return _dec

        def get(self, *args, **kwargs):
            return self.middleware("http")

        post = delete = websocket = get

        def add_middleware(self, *args, **kwargs):
            return None

        def mount(self, *args, **kwargs):
            return None

    fastapi_mod.FastAPI = _FastAPI
    fastapi_mod.Request = object
    fastapi_mod.UploadFile = object
    fastapi_mod.File = lambda *a, **k: ...
    fastapi_mod.WebSocket = object
    fastapi_mod.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    fastapi_mod.BackgroundTasks = object
    fastapi_mod.Header = lambda default="": default
    fastapi_mod.HTTPException = type("HTTPException", (Exception,), {})
    fastapi_mod.Depends = lambda fn: fn

    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object

    resp_mod = types.ModuleType("fastapi.responses")
    resp_mod.FileResponse = object
    resp_mod.HTMLResponse = object
    resp_mod.JSONResponse = lambda *a, **k: types.SimpleNamespace(content=k.get("content", a[0] if a else None), status_code=k.get("status_code", 200), media_type=k.get("media_type"))
    resp_mod.Response = object

    static_mod = types.ModuleType("fastapi.staticfiles")
    static_mod.StaticFiles = lambda directory: types.SimpleNamespace(directory=directory)

    redis_mod = types.ModuleType("redis.asyncio")
    class _Redis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()
        async def ping(self):
            return True
    redis_mod.Redis = _Redis

    cfg_mod = types.ModuleType("config")
    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_FORCE_KILL_ON_SHUTDOWN = True
        RATE_LIMIT_CHAT = 5
        RATE_LIMIT_MUTATIONS = 5
        RATE_LIMIT_GET_IO = 5
        RATE_LIMIT_WINDOW = 60
        REDIS_URL = "redis://localhost:6379/0"
        JWT_SECRET_KEY = ""
        JWT_ALGORITHM = "HS256"
        @staticmethod
        def initialize_directories():
            return None
    cfg_mod.Config = _Config


    pyd_mod = types.ModuleType("pydantic")
    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    pyd_mod.BaseModel = _BaseModel
    pyd_mod.Field = lambda default=None, **_k: default

    jwt_mod = types.ModuleType("jwt")
    class _PyJWTError(Exception):
        pass
    jwt_mod.PyJWTError = _PyJWTError
    jwt_mod.decode = lambda *_a, **_k: (_ for _ in ()).throw(_PyJWTError("bad"))
    jwt_mod.encode = lambda payload, *_a, **_k: str(payload)

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object
    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = object
    reg_mod = types.ModuleType("agent.registry")
    reg_mod.AgentRegistry = object
    swarm_mod = types.ModuleType("agent.swarm")
    swarm_mod.SwarmOrchestrator = object
    swarm_mod.SwarmTask = object

    event_mod = types.ModuleType("agent.core.event_stream")
    event_mod.get_agent_event_bus = lambda: types.SimpleNamespace(subscribe=lambda: ("sub", asyncio.Queue()), unsubscribe=lambda _sid: None)

    m_health = types.ModuleType("managers.system_health")
    m_health.render_llm_metrics_prometheus = lambda: ""

    llm_metrics = types.ModuleType("core.llm_metrics")
    llm_metrics.get_llm_metrics_collector = lambda: types.SimpleNamespace()
    llm_metrics.set_current_metrics_user_id = lambda _u: None
    llm_metrics.reset_current_metrics_user_id = lambda _t: None

    llm_client = types.ModuleType("core.llm_client")
    llm_client.LLMAPIError = type("LLMAPIError", (Exception,), {})
    ci_mod = types.ModuleType("core.ci_remediation")
    ci_mod.build_ci_failure_context = lambda *_a, **_k: {}
    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_gate = lambda: types.SimpleNamespace()
    hitl_mod.get_hitl_store = lambda: types.SimpleNamespace()
    hitl_mod.set_hitl_broadcast_hook = lambda _hook: None

    uvicorn_mod = types.ModuleType("uvicorn")
    uvicorn_mod.run = lambda *a, **k: None

    sys.modules.update({
        "fastapi": fastapi_mod,
        "fastapi.middleware.cors": cors_mod,
        "fastapi.responses": resp_mod,
        "fastapi.staticfiles": static_mod,
        "redis.asyncio": redis_mod,
        "config": cfg_mod,
        "pydantic": pyd_mod,
        "jwt": jwt_mod,
        "agent.sidar_agent": agent_mod,
        "agent.base_agent": base_agent_mod,
        "agent.registry": reg_mod,
        "agent.swarm": swarm_mod,
        "agent.core.event_stream": event_mod,
        "managers.system_health": m_health,
        "core.llm_metrics": llm_metrics,
        "core.llm_client": llm_client,
        "core.ci_remediation": ci_mod,
        "core.hitl": hitl_mod,
        "uvicorn": uvicorn_mod,
    })

    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(Path("agent").resolve())]
        sys.modules["agent"] = pkg
    if "agent.core" not in sys.modules:
        pkg = types.ModuleType("agent.core")
        pkg.__path__ = [str(Path("agent/core").resolve())]
        sys.modules["agent.core"] = pkg
    if "core" not in sys.modules:
        pkg = types.ModuleType("core")
        pkg.__path__ = []
        sys.modules["core"] = pkg

    spec = importlib.util.spec_from_file_location("web_server_critical_under_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_shutdown_and_subprocess_parse_edges(monkeypatch):
    mod = _load_web_server_module()
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "ps")))
    assert mod._list_child_ollama_pids() == []

    monkeypatch.setattr(mod.os, "getpid", lambda: 7)
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: b"bad\n 10 xx ollama ollama\n 11 7 ollama ollama serve\n")
    assert mod._list_child_ollama_pids() == [11]


def test_shutdown_pid_discovery_prefers_psutil_and_skips_ps_on_windows(monkeypatch):
    mod = _load_web_server_module()

    class _Child:
        def __init__(self, pid, name, cmdline):
            self.pid = pid
            self._name = name
            self._cmdline = cmdline

        def name(self):
            return self._name

        def cmdline(self):
            return self._cmdline

    class _Process:
        def __init__(self, pid):
            assert pid == 77

        def children(self, recursive=False):
            assert recursive is False
            return [
                _Child(41, "ollama", ["ollama", "serve"]),
                _Child(42, "python", ["python", "worker.py"]),
            ]

    fake_psutil = types.SimpleNamespace(Process=_Process)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(mod.os, "getpid", lambda: 77)
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ps fallback should not run")))
    assert mod._list_child_ollama_pids() == [41]

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ps should not run on Windows")))
    assert mod._list_child_ollama_pids() == []


def test_async_shutdown_swallows_oserror_and_marks_done(monkeypatch):
    mod = _load_web_server_module()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True
    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: [1])

    orig_sleep = asyncio.sleep

    async def _fast_sleep(*_a, **_k):
        await orig_sleep(0)

    monkeypatch.setattr(mod.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(mod.os, "kill", lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")))
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: 0)

    asyncio.run(mod._async_force_shutdown_local_llm_processes())
    assert mod._shutdown_cleanup_done is True


def test_redis_rate_limit_rediserror_fallback(monkeypatch):
    mod = _load_web_server_module()

    class _RedisErr(Exception):
        pass

    class _R:
        async def incr(self, _key):
            raise _RedisErr("x")

    async def _get():
        return _R()

    async def _local(*_a, **_k):
        return True

    monkeypatch.setattr(mod, "_get_redis", _get)
    monkeypatch.setattr(mod, "_local_is_rate_limited", _local)
    assert asyncio.run(mod._redis_is_rate_limited("chat", "ip", 1, 60)) is True


def test_prewarm_timeout_error_path(monkeypatch):
    mod = _load_web_server_module()

    class _Rag:
        _chroma_available = True
        def _init_chroma(self):
            raise TimeoutError("timeout")

    async def _ga():
        return types.SimpleNamespace(rag=_Rag())

    async def _to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod, "get_agent", _ga)
    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread)
    asyncio.run(mod._prewarm_rag_embeddings())
