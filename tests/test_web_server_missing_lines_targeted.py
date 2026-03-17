import asyncio
import importlib.util
import io
import sys
import types
from pathlib import Path


class _FakeResponse:
    def __init__(self, content=None, status_code=200, headers=None, media_type=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.media_type = media_type


class _FakeRequest:
    def __init__(self, *, method="GET", path="/", headers=None, host="127.0.0.1"):
        self.method = method
        self.url = types.SimpleNamespace(path=path)
        self.headers = headers or {}
        self.client = types.SimpleNamespace(host=host)
        self.state = types.SimpleNamespace()


class _FakeUploadFile:
    def __init__(self, filename, data: bytes):
        self.filename = filename
        self._data = data
        self.closed = False

    async def read(self):
        return self._data

    async def close(self):
        self.closed = True


def _install_web_server_stubs():
    fastapi_mod = types.ModuleType("fastapi")

    class _FakeFastAPI:
        def __init__(self, *args, **kwargs):
            return None

        def middleware(self, _kind):
            return lambda fn: fn

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def delete(self, *args, **kwargs):
            return lambda fn: fn

        def websocket(self, *args, **kwargs):
            return lambda fn: fn

        def add_middleware(self, *args, **kwargs):
            return None

        def mount(self, *args, **kwargs):
            return None

    fastapi_mod.FastAPI = _FakeFastAPI
    fastapi_mod.Request = _FakeRequest
    fastapi_mod.UploadFile = _FakeUploadFile
    fastapi_mod.File = lambda *a, **k: ...
    fastapi_mod.WebSocket = object
    fastapi_mod.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    fastapi_mod.BackgroundTasks = object
    fastapi_mod.Header = lambda default="": default

    class _HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi_mod.HTTPException = _HTTPException
    fastapi_mod.Depends = lambda fn: fn

    sys.modules["fastapi"] = fastapi_mod
    sys.modules["fastapi.middleware.cors"] = types.SimpleNamespace(CORSMiddleware=object)
    sys.modules["fastapi.responses"] = types.SimpleNamespace(
        Response=_FakeResponse,
        JSONResponse=_FakeResponse,
        HTMLResponse=_FakeResponse,
        FileResponse=_FakeResponse,
    )
    sys.modules["fastapi.staticfiles"] = types.SimpleNamespace(StaticFiles=lambda directory: types.SimpleNamespace(directory=directory))
    sys.modules["uvicorn"] = types.SimpleNamespace(run=lambda *a, **k: None)
    sys.modules["jwt"] = types.SimpleNamespace(decode=lambda *a, **k: {}, encode=lambda *a, **k: "tok", PyJWTError=Exception)
    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    sys.modules["pydantic"] = types.SimpleNamespace(BaseModel=_BaseModel, Field=lambda default=None, **_k: default)
    sys.modules["redis.asyncio"] = types.SimpleNamespace(Redis=type("R", (), {"from_url": classmethod(lambda cls, *a, **k: cls()), "ping": lambda self: None}))

    cfg_mod = types.ModuleType("config")

    class _Cfg:
        ENABLE_TRACING = False
        OTEL_EXPORTER_ENDPOINT = ""
        RATE_LIMIT_CHAT = 5
        RATE_LIMIT_MUTATIONS = 5
        RATE_LIMIT_GET_IO = 5
        RATE_LIMIT_WINDOW = 60
        REDIS_URL = "redis://localhost:6379/0"

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod

    if "agent" not in sys.modules:
        p = types.ModuleType("agent")
        p.__path__ = [str(Path("agent").resolve())]
        sys.modules["agent"] = p
    if "agent.core" not in sys.modules:
        p2 = types.ModuleType("agent.core")
        p2.__path__ = [str(Path("agent/core").resolve())]
        sys.modules["agent.core"] = p2

    sys.modules["agent.sidar_agent"] = types.SimpleNamespace(SidarAgent=object)
    sys.modules["agent.core.event_stream"] = types.SimpleNamespace(get_agent_event_bus=lambda: types.SimpleNamespace(subscribe=lambda: ("1", asyncio.Queue()), unsubscribe=lambda _id: None))
    sys.modules["managers.system_health"] = types.SimpleNamespace(render_llm_metrics_prometheus=lambda *_a, **_k: "")
    sys.modules["core.llm_metrics"] = types.SimpleNamespace(get_llm_metrics_collector=lambda: types.SimpleNamespace(), set_current_metrics_user_id=lambda _u: None, reset_current_metrics_user_id=lambda _t: None)
    sys.modules["core.llm_client"] = types.SimpleNamespace(LLMAPIError=type("LLMAPIError", (Exception,), {}), LLMClient=object)


def _load_web_server():
    _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_target", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_targeted_web_server_branches(monkeypatch):
    mod = _load_web_server()

    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ps fail")))
    assert mod._list_child_ollama_pids() == []
    monkeypatch.setattr(mod.os, "waitpid", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wait fail")))
    assert mod._reap_child_processes_nonblocking() == 0

    mod._shutdown_cleanup_done = True
    mod._force_shutdown_local_llm_processes()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "gemini"
    asyncio.run(mod._async_force_shutdown_local_llm_processes())

    assert mod._build_user_from_jwt_payload({"sub": "", "username": ""}) is None
    assert mod._resolve_policy_from_request(_FakeRequest(path="/api/agents/register")) == ("agents", "register", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/admin/x")) == ("admin", "manage", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/ws/chat")) == ("swarm", "execute", "*")
    assert mod._resolve_policy_from_request(_FakeRequest(path="/x")) == ("", "", "")

    rec = types.SimpleNamespace(id=1, user_id="u", tenant_id="t", resource_type="rag", resource_id="*", action="read", effect="allow", created_at="c", updated_at="u")
    assert mod._serialize_policy(rec)["id"] == 1
    assert mod._sanitize_capabilities([]) == []

    try:
        mod._load_plugin_agent_class("raise RuntimeError('x')", None, "m")
        assert False
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    try:
        mod._load_plugin_agent_class("class A: pass", "A", "m")
        assert False
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    try:
        mod._load_plugin_agent_class("x=1", None, "m")
        assert False
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400

    empty = _FakeUploadFile("x.py", b"")
    try:
        asyncio.run(mod.register_agent_plugin_file(file=empty, _user=object()))
        assert False
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400

    class _Task:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    created = {"task": None}

    def _fake_create_task(coro):
        coro.close()
        created["task"] = _Task()
        return created["task"]

    async def _rl(*_a, **_k):
        return False

    async def _resolve(*_a, **_k):
        return types.SimpleNamespace(id="u1", username="alice")

    monkeypatch.setattr(mod.asyncio, "create_task", _fake_create_task)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _rl)
    monkeypatch.setattr(mod, "_resolve_user_from_token", _resolve)

    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_a):
            return None

    async def _agent():
        return types.SimpleNamespace(memory=_Memory(), respond=lambda _m: iter(()))

    mod.get_agent = _agent

    class _Closed(Exception):
        pass

    mod._ANYIO_CLOSED = _Closed

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.msgs = ['{"action":"auth","token":"t"}', '{"message":"hello"}']

        async def accept(self):
            return None

        async def receive_text(self):
            if self.msgs:
                return self.msgs.pop(0)
            raise _Closed("closed")

        async def send_json(self, _data):
            return None

    asyncio.run(mod.websocket_chat(_WS()))
    assert created["task"] and created["task"].cancelled is True