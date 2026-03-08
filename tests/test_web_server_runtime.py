import asyncio
import base64
import importlib.util
import io
import json
import sys
import types
from pathlib import Path


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

    def on_event(self, *args, **kwargs):
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

    async def json(self):
        return self._json_body or {}

    async def body(self):
        return self._body


class _FakeUploadFile:
    def __init__(self, filename, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)
        self.closed = False

    async def close(self):
        self.closed = True


def _install_web_server_stubs():
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

    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object

    resp_mod = types.ModuleType("fastapi.responses")
    resp_mod.Response = _FakeResponse
    resp_mod.JSONResponse = _FakeJSONResponse
    resp_mod.HTMLResponse = _FakeHTMLResponse
    resp_mod.FileResponse = _FakeFileResponse

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

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Config

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object

    sys.modules["fastapi"] = fastapi_mod
    sys.modules["fastapi.middleware.cors"] = cors_mod
    sys.modules["fastapi.responses"] = resp_mod
    sys.modules["fastapi.staticfiles"] = static_mod
    sys.modules["redis.asyncio"] = redis_mod
    sys.modules["uvicorn"] = uvicorn_mod
    sys.modules["config"] = cfg_mod
    if "agent" not in sys.modules:
        sys.modules["agent"] = types.ModuleType("agent")
    sys.modules["agent.sidar_agent"] = agent_mod


def _load_web_server():
    _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_under_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _make_agent(ai_provider="ollama", ollama_online=True):
    calls = {"search": None, "add_level": None, "adds": []}

    class _Memory:
        active_session_id = "sess-1"

        def __len__(self):
            return 2

        def get_all_sessions(self):
            return [{"id": "sess-1"}]

        def clear(self):
            calls["cleared"] = True

        def add(self, role, text):
            calls["adds"].append((role, text))

    class _Docs:
        doc_count = 3

        def status(self):
            return "ok"

        def add_document_from_file(self, *args):
            calls["add_file"] = args
            return True, "eklendi"

        def search(self, q, top_k, mode, session_id):
            calls["search"] = (q, top_k, mode, session_id)
            return True, ["x"]

        def get_index_info(self, session_id):
            return [{"id": "d1", "session": session_id}]

    class _Health:
        def get_health_summary(self):
            return {"status": "ok", "ollama_online": ollama_online}

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
        set_access_level=lambda lvl: f"set:{lvl}",
    )
    return agent, calls


def test_basic_auth_middleware_flow():
    mod = _load_web_server()

    async def _next(_request):
        return _FakeResponse("ok", status_code=200)

    req = _FakeRequest(path="/status")
    resp = asyncio.run(mod.basic_auth_middleware(req, _next))
    assert resp.status_code == 200

    mod.cfg.API_KEY = "secret"
    bad = _FakeRequest(path="/status", headers={"Authorization": "Basic xxx"})
    unauthorized = asyncio.run(mod.basic_auth_middleware(bad, _next))
    assert unauthorized.status_code == 401

    good_token = base64.b64encode(b"user:secret").decode("utf-8")
    good = _FakeRequest(path="/status", headers={"Authorization": f"Basic {good_token}"})
    ok = asyncio.run(mod.basic_auth_middleware(good, _next))
    assert ok.status_code == 200


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
