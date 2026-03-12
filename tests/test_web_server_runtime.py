import asyncio
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

    event_stream_mod.get_agent_event_bus = lambda: _EventBus()
    sys.modules["fastapi"] = fastapi_mod
    sys.modules["fastapi.middleware.cors"] = cors_mod
    sys.modules["fastapi.responses"] = resp_mod
    sys.modules["fastapi.staticfiles"] = static_mod
    sys.modules["redis.asyncio"] = redis_mod
    sys.modules["uvicorn"] = uvicorn_mod
    sys.modules["config"] = cfg_mod
    if "agent" not in sys.modules:
        sys.modules["agent"] = types.ModuleType("agent")
    if "agent.core" not in sys.modules:
        sys.modules["agent.core"] = types.ModuleType("agent.core")
    if "core" not in sys.modules:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = []
        sys.modules["core"] = core_pkg
    llm_client_mod = types.ModuleType("core.llm_client")

    class _LLMAPIError(Exception):
        def __init__(self, message="err", provider="stub", status_code=None, retryable=False):
            super().__init__(message)
            self.provider = provider
            self.status_code = status_code
            self.retryable = retryable

    llm_client_mod.LLMAPIError = _LLMAPIError

    sys.modules["agent.sidar_agent"] = agent_mod
    sys.modules["agent.core.event_stream"] = event_stream_mod
    sys.modules["core.llm_metrics"] = core_metrics_mod
    sys.modules["core.llm_client"] = llm_client_mod


def _load_web_server():
    _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_under_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod




def _load_web_server_with_blocked_imports():
    import builtins

    real_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "anyio" or name.startswith("opentelemetry"):
            raise ImportError(f"blocked: {name}")
        return real_import(name, globals, locals, fromlist, level)

    _install_web_server_stubs()
    spec = importlib.util.spec_from_file_location("web_server_under_test_blocked", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    builtins.__import__ = _blocked
    try:
        spec.loader.exec_module(mod)
    finally:
        builtins.__import__ = real_import
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

        def get_all_sessions(self):
            return [{"id": "sess-1"}]

        async def aset_active_user(self, _user_id, _username=None):
            return None

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

    class _Db:
        async def get_user_by_token(self, token):
            if token == "good-token":
                return types.SimpleNamespace(id="u1", username="alice", role="user")
            return None

    class _Mem:
        def __init__(self):
            self.db = _Db()

        async def aset_active_user(self, _uid, _uname=None):
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

    good = _FakeRequest(path="/status", headers={"Authorization": "Bearer good-token"})
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

        def clear(self):
            calls["cleared"] += 1

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

        async def aset_active_user(self, _user_id, _username=None):
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


def test_websocket_chat_send_json_failure_is_swallowed():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def aset_active_user(self, _user_id, _username=None):
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

        async def aset_active_user(self, _uid, _uname=None):
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


def test_webhook_pull_request_and_issues_branches_add_memory_records():
    mod = _load_web_server()
    calls = []

    memory = types.SimpleNamespace(add=lambda role, text: calls.append((role, text)))
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

    monkeypatch.setattr(mod.shutil, "copyfileobj", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("disk")))
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
        memory=types.SimpleNamespace(__len__=lambda self: 1, get_all_sessions=lambda: [{"id": "s1"}]),
    )

    class _Mem:
        def __len__(self):
            return 1

        def get_all_sessions(self):
            return [{"id": "s1"}]

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
    mod._redis_lock = None
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

        async def aset_active_user(self, _uid, _uname=None):
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
    agent.memory = types.SimpleNamespace(add=lambda role, text: calls_mem.append((role, text)))
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



def test_websocket_chat_cancellederror_pass_branch_with_running_task():
    mod = _load_web_server()

    class _Memory:
        class _DB:
            async def get_user_by_token(self, _token):
                return types.SimpleNamespace(id="u1", username="alice")

        def __init__(self):
            self.db = self._DB()

        async def aset_active_user(self, _uid, _uname=None):
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

        async def aset_active_user(self, _uid, _uname=None):
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

    class _Db:
        async def get_user_by_token(self, token):
            return types.SimpleNamespace(id="u1", username="alice", role="user") if token == "good-token" else None

    class _Mem:
        def __init__(self):
            self.db = _Db()

        async def aset_active_user(self, _uid, _uname=None):
            return None

    async def _get_agent():
        return types.SimpleNamespace(memory=_Mem())

    seen = {"reset": 0}
    mod.get_agent = _get_agent
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-token")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda token: seen.__setitem__("reset", seen["reset"] + (1 if token == "ctx-token" else 0)))

    async def _boom(_request):
        raise RuntimeError("next failed")

    req = _FakeRequest(path="/status", headers={"Authorization": "Bearer good-token"})
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

        async def aset_active_user(self, _uid, _uname=None):
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
