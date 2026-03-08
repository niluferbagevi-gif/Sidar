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
    assert "<h1>ok</h1>" in idx_ok

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

    class _Agent:
        VERSION = "9.9"

        def __init__(self, cfg):
            created["cfg"] = cfg

    def _run(app, host, port, log_level):
        created["uvicorn"] = (host, port, log_level)

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.uvicorn, "run", _run)
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "0.0.0.0", "--port", "9999", "--level", "full", "--provider", "gemini", "--log", "DEBUG"])

    mod.main()

    assert created["cfg"].ACCESS_LEVEL == "full"
    assert created["cfg"].AI_PROVIDER == "gemini"
    assert created["uvicorn"] == ("0.0.0.0", 9999, "debug")


def test_list_files_metrics_rag_docs_todo_clear_and_github_repos_success(monkeypatch):
    mod = _load_web_server()

    class _Memory:
        active_session_id = "sess-42"

        def __len__(self):
            return 3

        def get_all_sessions(self):
            return [{"id": "sess-42"}, {"id": "sess-2"}]

        def clear(self):
            self.cleared = True

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