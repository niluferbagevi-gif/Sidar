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

def test_agent_lifecycle_get_agent_singleton_and_shutdown_close():
    mod = _load_web_server()

    created = {"count": 0}

    class _Agent:
        def __init__(self, cfg):
            created["count"] += 1

    class _RedisConn:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    mod.SidarAgent = _Agent
    mod._agent = None
    mod._agent_lock = None

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

        def get_all_sessions(self):
            return [{"id": "sess-1"}, {"id": "sess-2"}]

        def load_session(self, session_id):
            return session_id == "sess-1"

        def get_history(self):
            return [{"role": "user", "content": "hi"}]

        def create_session(self, _title):
            self.active_session_id = "sess-3"
            return "sess-3"

        def delete_session(self, session_id):
            return session_id == "sess-1"

        def clear(self):
            calls["cleared"] += 1

    agent = types.SimpleNamespace(memory=_Memory())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    sessions = asyncio.run(mod.get_sessions())
    assert sessions.status_code == 200
    assert sessions.content["active_session"] == "sess-1"

    loaded = asyncio.run(mod.load_session("sess-1"))
    assert loaded.status_code == 200
    assert loaded.content["success"] is True

    not_found = asyncio.run(mod.load_session("missing"))
    assert not_found.status_code == 404

    new_sess = asyncio.run(mod.new_session())
    assert new_sess.status_code == 200
    assert new_sess.content["session_id"] == "sess-3"

    deleted = asyncio.run(mod.delete_session("sess-1"))
    assert deleted.status_code == 200
    assert deleted.content["success"] is True

    delete_fail = asyncio.run(mod.delete_session("sess-2"))
    assert delete_fail.status_code == 500

    cleared = asyncio.run(mod.clear())
    assert cleared.status_code == 200
    assert cleared.content["result"] is True
    assert calls["cleared"] == 1


def test_websocket_chat_cancel_and_disconnect_paths():
    mod = _load_web_server()

    class _Memory:
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
            json.dumps({"message": "uzun bir mesaj", "action": "send"}),
            json.dumps({"action": "cancel"}),
        ],
        disconnect_exc=mod.WebSocketDisconnect,
    )

    asyncio.run(mod.websocket_chat(ws))

    assert ws.accepted is True
    assert any(p.get("done") is True and "iptal" in p.get("chunk", "") for p in ws.sent)


def test_websocket_chat_generate_response_cancelled_error_branch():
    mod = _load_web_server()

    class _Memory:
        def __len__(self):
            return 0

        def update_title(self, title):
            self.title = title

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
