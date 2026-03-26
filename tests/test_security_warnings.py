"""
Güvenlik uyarıları ve rate limit Redis fallback testleri.

1. MEMORY_ENCRYPTION_KEY boş geçildiğinde validate_critical_settings()
   logger.critical() çağırmalı (JWT_SECRET_KEY için uygulanan YN3-D-1 ile aynı pattern).

2. Rate limiting: Redis backend erişilemez olduğunda _redis_is_rate_limited()
   yerel fallback'e geçmeli; ne hata fırlatmalı ne de isteği yanlış değerlendirmeli.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


# ─── Stub'lar: kırık bağımlılıkları test sırasında maskele ───────────────

def _ensure_stubs():
    """jwt ve pydantic gibi ortamda kırık olan modülleri sys.modules'e yerleştir."""
    if "jwt" not in sys.modules:
        jwt_stub = types.ModuleType("jwt")
        jwt_stub.encode = lambda payload, key, algorithm="HS256": "stub-token"
        jwt_stub.decode = lambda token, key, algorithms=None: {}
        jwt_stub.PyJWTError = type("PyJWTError", (Exception,), {})
        jwt_stub.DecodeError = type("DecodeError", (Exception,), {})
        jwt_stub.ExpiredSignatureError = type("ExpiredSignatureError", (Exception,), {})
        sys.modules["jwt"] = jwt_stub

    if "pydantic" not in sys.modules:
        pydantic_stub = types.ModuleType("pydantic")
        pydantic_stub.BaseModel = object
        pydantic_stub.Field = lambda *a, **k: None
        sys.modules["pydantic"] = pydantic_stub


# ─── Config modülü yükleyici ──────────────────────────────────────────────

def _load_config():
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        spec = importlib.util.spec_from_file_location(
            "config_security_test", Path("config.py")
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


def _prepare_config_for_validate(cfg_mod):
    """validate_critical_settings() için minimum ön koşulları hazırlar."""
    cfg_mod.Config._hardware_loaded = True
    cfg_mod.Config.initialize_directories = classmethod(lambda cls: None)
    cfg_mod.Config.AI_PROVIDER = "ollama"
    cfg_mod.Config.GEMINI_API_KEY = "irrelevant"
    cfg_mod.Config.OPENAI_API_KEY = "irrelevant"
    cfg_mod.Config.ANTHROPIC_API_KEY = "irrelevant"
    cfg_mod.Config.LITELLM_GATEWAY_URL = "http://localhost:4000"
    cfg_mod.Config.OLLAMA_URL = "http://localhost:11434/api"


# ─── Web server modülü yükleyici (redis fallback testleri için) ──────────

class _FakeRequest:
    def __init__(self):
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.headers = {}
        self.url = types.SimpleNamespace(path="/")
        self.method = "GET"
        self.state = types.SimpleNamespace()


class _FakeFastAPI:
    def __init__(self, *a, **k): pass
    def get(self, *a, **k): return lambda fn: fn
    def post(self, *a, **k): return lambda fn: fn
    def delete(self, *a, **k): return lambda fn: fn
    def websocket(self, *a, **k): return lambda fn: fn
    def middleware(self, *a, **k): return lambda fn: fn
    def on_event(self, *a, **k): return lambda fn: fn
    def add_middleware(self, *a, **k): pass
    def mount(self, *a, **k): pass


def _load_web_server_standalone():
    """Web server'ı tüm bağımlılıkları stublanmış olarak yükler."""
    _ensure_stubs()

    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.FastAPI = _FakeFastAPI
    fastapi_mod.Request = _FakeRequest
    fastapi_mod.UploadFile = object
    fastapi_mod.File = lambda *a, **k: ...
    fastapi_mod.WebSocket = object
    fastapi_mod.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    fastapi_mod.BackgroundTasks = object
    fastapi_mod.Header = lambda default="": default
    fastapi_mod.HTTPException = type("HTTPException", (Exception,), {
        "__init__": lambda self, status_code=500, detail="": None
    })
    fastapi_mod.Depends = lambda fn: fn

    cors_mod = types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object

    resp_mod = types.ModuleType("fastapi.responses")
    resp_mod.Response = object
    resp_mod.JSONResponse = object
    resp_mod.HTMLResponse = object
    resp_mod.FileResponse = object

    static_mod = types.ModuleType("fastapi.staticfiles")
    static_mod.StaticFiles = lambda directory="": types.SimpleNamespace()

    class _Redis:
        @classmethod
        def from_url(cls, *a, **k):
            return cls()
        async def ping(self):
            return True
        async def incr(self, key):
            return 1
        async def expire(self, key, ttl):
            pass

    redis_mod = types.ModuleType("redis.asyncio")
    redis_mod.Redis = _Redis

    uvicorn_mod = types.ModuleType("uvicorn")
    uvicorn_mod.run = lambda *a, **k: None

    cfg_mod = types.ModuleType("config")

    class _Config:
        API_KEY = ""
        ENABLE_TRACING = False
        OTEL_EXPORTER_ENDPOINT = ""
        OTEL_SERVICE_NAME = "sidar-test"
        RATE_LIMIT_CHAT = 5
        RATE_LIMIT_MUTATIONS = 5
        RATE_LIMIT_GET_IO = 5
        RATE_LIMIT_WINDOW = 60
        REDIS_URL = "redis://localhost:6379/0"
        WEB_HOST = "127.0.0.1"
        WEB_PORT = 7860
        GITHUB_WEBHOOK_SECRET = ""
        GITHUB_REPO = ""
        JWT_SECRET_KEY = "test-secret"
        JWT_ALGORITHM = "HS256"
        JWT_TTL_DAYS = 7
        MEMORY_ENCRYPTION_KEY = ""

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Config

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object

    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = object

    contracts_mod = types.ModuleType("agent.core.contracts")

    class _Envelope(types.SimpleNamespace):
        protocol_version = "1.0"

        def to_prompt(self):
            return "stub-envelope"

    class _Result(types.SimpleNamespace):
        protocol_version = "1.0"

    class _ExternalTrigger(types.SimpleNamespace):
        trigger_id = "trigger-1"
        source = "stub"
        event_name = "stub"
        payload = {}
        meta = {}
        correlation_id = "corr-1"

        def to_prompt(self):
            return "stub-trigger"

    class _ActionFeedback(types.SimpleNamespace):
        def to_prompt(self):
            return "stub-feedback"

    contracts_mod.ActionFeedback = _ActionFeedback
    contracts_mod.ExternalTrigger = _ExternalTrigger
    contracts_mod.FederationTaskEnvelope = _Envelope
    contracts_mod.FederationTaskResult = _Result
    contracts_mod.LEGACY_FEDERATION_PROTOCOL_V1 = "1.0"
    contracts_mod.derive_correlation_id = lambda *_a, **_k: "corr-1"
    contracts_mod.normalize_federation_protocol = lambda value=None: value or "1.0"

    registry_mod = types.ModuleType("agent.registry")

    class _AgentRegistry:
        @classmethod
        def list_all(cls):
            return []

        @classmethod
        def register_type(cls, **_kwargs):
            return None

        @classmethod
        def unregister(cls, *_args, **_kwargs):
            return False

        @classmethod
        def get(cls, *_args, **_kwargs):
            return None

        @classmethod
        def find_by_capability(cls, *_args, **_kwargs):
            return []

    registry_mod.AgentRegistry = _AgentRegistry

    swarm_mod = types.ModuleType("agent.swarm")

    class _SwarmOrchestrator:
        def __init__(self, *_args, **_kwargs):
            return None

    class _SwarmTask:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    swarm_mod.SwarmOrchestrator = _SwarmOrchestrator
    swarm_mod.SwarmTask = _SwarmTask

    core_metrics_mod = types.ModuleType("core.llm_metrics")

    class _Collector:
        def snapshot(self):
            return {"totals": {"calls": 0, "total_tokens": 0}}

    core_metrics_mod.get_llm_metrics_collector = lambda: _Collector()
    core_metrics_mod.set_current_metrics_user_id = lambda *_a, **_k: None
    core_metrics_mod.reset_current_metrics_user_id = lambda *_a, **_k: None

    event_stream_mod = types.ModuleType("agent.core.event_stream")

    class _EventBus:
        def subscribe(self):
            return "sub-1", asyncio.Queue()
        def unsubscribe(self, _sub_id): pass
        async def publish(self, _source, _message): pass

    event_stream_mod.get_agent_event_bus = lambda: _EventBus()

    llm_client_mod = types.ModuleType("core.llm_client")
    llm_client_mod.LLMAPIError = type("LLMAPIError", (Exception,), {})
    llm_client_mod.LLMClient = type("LLMClient", (), {})

    ci_mod = types.ModuleType("core.ci_remediation")
    ci_mod.build_ci_failure_context = lambda *_a, **_k: {}

    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_gate = lambda: types.SimpleNamespace(respond=lambda *a, **k: None, submit=lambda *a, **k: None)
    hitl_mod.get_hitl_store = lambda: types.SimpleNamespace(list_pending=lambda: [], get=lambda *_a, **_k: None)
    hitl_mod.set_hitl_broadcast_hook = lambda *_a, **_k: None

    # managers.system_health stub
    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = []
    managers_health_mod = types.ModuleType("managers.system_health")
    managers_health_mod.render_llm_metrics_prometheus = lambda *a, **k: ""

    # httpx stub (managers/package_info.py imports it)
    httpx_stub = types.SimpleNamespace(
        Timeout=type("Timeout", (), {"__init__": lambda s, t, connect=None: None}),
        ConnectError=type("ConnectError", (Exception,), {}),
        AsyncClient=None,
        Client=type("Client", (), {
            "__init__": lambda s, timeout=None: None,
            "__enter__": lambda s: s,
            "__exit__": lambda s, *a: False,
            "get": lambda s, u: types.SimpleNamespace(status_code=200),
        }),
    )

    to_install = {
        "fastapi": fastapi_mod,
        "fastapi.middleware.cors": cors_mod,
        "fastapi.responses": resp_mod,
        "fastapi.staticfiles": static_mod,
        "redis.asyncio": redis_mod,
        "uvicorn": uvicorn_mod,
        "config": cfg_mod,
        "agent.sidar_agent": agent_mod,
        "agent.base_agent": base_agent_mod,
        "agent.core.contracts": contracts_mod,
        "agent.core.event_stream": event_stream_mod,
        "agent.registry": registry_mod,
        "agent.swarm": swarm_mod,
        "core.llm_metrics": core_metrics_mod,
        "core.llm_client": llm_client_mod,
        "core.ci_remediation": ci_mod,
        "core.hitl": hitl_mod,
        "managers": managers_pkg,
        "managers.system_health": managers_health_mod,
        "httpx": httpx_stub,
    }

    for pkg_name in ("agent", "agent.core", "core"):
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [str(Path(pkg_name.replace(".", "/")).resolve())] if Path(pkg_name.replace(".", "/")).exists() else []
            to_install[pkg_name] = pkg

    saved = {k: sys.modules.get(k) for k in to_install}
    for k, v in to_install.items():
        sys.modules[k] = v

    try:
        spec = importlib.util.spec_from_file_location(
            "web_server_security_test", Path("web_server.py")
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ══════════════════════════════════════════════════════════════════════════
# MEMORY_ENCRYPTION_KEY CRITICAL uyarı testleri
# ══════════════════════════════════════════════════════════════════════════

def _httpx_stub():
    """Ollama bağlantı çağrısını engellemek için httpx stubs."""
    return types.SimpleNamespace(
        Client=type("C", (), {
            "__init__": lambda s, timeout: None,
            "__enter__": lambda s: s,
            "__exit__": lambda s, *a: False,
            "get": lambda s, u: types.SimpleNamespace(status_code=200),
        })
    )


def test_memory_encryption_key_missing_logs_critical(monkeypatch):
    """MEMORY_ENCRYPTION_KEY boş olduğunda logger.critical() çağrılmalı."""
    cfg_mod = _load_config()
    _prepare_config_for_validate(cfg_mod)

    criticals = []
    monkeypatch.setattr(cfg_mod.logger, "critical",
                        lambda msg, *a: criticals.append(msg % a if a else msg))
    monkeypatch.setitem(sys.modules, "httpx", _httpx_stub())

    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    cfg_mod.Config.validate_critical_settings()

    assert any("MEMORY_ENCRYPTION_KEY" in msg for msg in criticals), (
        "MEMORY_ENCRYPTION_KEY boş olduğunda logger.critical() çağrılmadı.\n"
        f"Yakalanan critical mesajları: {criticals}"
    )


def test_memory_encryption_key_missing_message_mentions_fernet(monkeypatch):
    """CRITICAL mesajı Fernet anahtar üretim talimatını içermeli."""
    cfg_mod = _load_config()
    _prepare_config_for_validate(cfg_mod)

    criticals = []
    monkeypatch.setattr(cfg_mod.logger, "critical",
                        lambda msg, *a: criticals.append(msg % a if a else msg))
    monkeypatch.setitem(sys.modules, "httpx", _httpx_stub())

    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    cfg_mod.Config.validate_critical_settings()

    full = " ".join(criticals)
    assert "Fernet" in full, f"CRITICAL mesajı Fernet yönlendirmesi içermeli: {full}"


def test_memory_encryption_key_present_no_critical(monkeypatch):
    """Geçerli MEMORY_ENCRYPTION_KEY varken CRITICAL uyarısı verilmemeli."""
    cfg_mod = _load_config()
    _prepare_config_for_validate(cfg_mod)

    criticals = []
    monkeypatch.setattr(cfg_mod.logger, "critical",
                        lambda msg, *a: criticals.append(msg % a if a else msg))
    monkeypatch.setitem(sys.modules, "httpx", _httpx_stub())

    # Geçerli Fernet anahtarı; Fernet'i stubla — cryptography paketi olmadan çalışsın
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleTE="
    fernet_cls = type("Fernet", (), {"__init__": lambda s, k: None})
    monkeypatch.setitem(sys.modules, "cryptography.fernet",
                        types.SimpleNamespace(Fernet=fernet_cls))

    cfg_mod.Config.validate_critical_settings()

    mem_criticals = [m for m in criticals if "MEMORY_ENCRYPTION_KEY" in m]
    assert not mem_criticals, (
        f"Geçerli anahtar varken CRITICAL uyarısı gelmemeli: {mem_criticals}"
    )


def test_memory_encryption_key_missing_still_returns_true(monkeypatch):
    """
    Şifreleme anahtarının yokluğu is_valid'i False yapmaz —
    uyarı verilir ama sistem çalışmaya devam eder (JWT pattern ile tutarlı).
    """
    cfg_mod = _load_config()
    _prepare_config_for_validate(cfg_mod)

    monkeypatch.setattr(cfg_mod.logger, "critical", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "httpx", _httpx_stub())

    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    result = cfg_mod.Config.validate_critical_settings()

    assert result is True, (
        "MEMORY_ENCRYPTION_KEY yokluğu is_valid=False yapmamalı; yalnızca CRITICAL loglar."
    )


# ══════════════════════════════════════════════════════════════════════════
# Rate limit — Redis yokluğunda graceful fallback testleri
# ══════════════════════════════════════════════════════════════════════════

def test_redis_unavailable_falls_back_to_local(monkeypatch):
    """_get_redis() None döndürdüğünde _redis_is_rate_limited() yerel fallback kullanır."""
    mod = _load_web_server_standalone()
    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    async def _no_redis():
        return None

    monkeypatch.setattr(mod, "_get_redis", _no_redis)

    result = asyncio.run(mod._redis_is_rate_limited("ns", "192.0.2.10", 100, 60))
    assert isinstance(result, bool), "Sonuç bool olmalı"


def test_redis_unavailable_does_not_raise(monkeypatch):
    """Redis None iken _redis_is_rate_limited() hata fırlatmaz."""
    mod = _load_web_server_standalone()
    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    async def _no_redis():
        return None

    monkeypatch.setattr(mod, "_get_redis", _no_redis)

    try:
        asyncio.run(mod._redis_is_rate_limited("ddos", "1.2.3.4", 50, 60))
    except Exception as exc:
        raise AssertionError(
            f"_redis_is_rate_limited Redis yokken hata fırlattı: {exc}"
        ) from exc


def test_redis_exception_mid_call_falls_back_to_local(monkeypatch):
    """Redis.incr() hata fırlatırsa yerel fallback devreye girer; sonuç bool döner."""
    mod = _load_web_server_standalone()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    class _BrokenRedis:
        async def incr(self, key):
            raise ConnectionError("redis down")
        async def expire(self, key, ttl):
            pass

    async def _broken_redis():
        return _BrokenRedis()

    monkeypatch.setattr(mod, "_get_redis", _broken_redis)

    result = asyncio.run(mod._redis_is_rate_limited("chat", "5.6.7.8", 10, 60))
    assert isinstance(result, bool)


def test_redis_exception_mid_call_logs_warning(monkeypatch):
    """Redis hatasında logger.warning() çağrılmalı."""
    mod = _load_web_server_standalone()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    class _BrokenRedis:
        async def incr(self, key):
            raise ConnectionError("redis unavailable")
        async def expire(self, key, ttl):
            pass

    async def _broken_redis():
        return _BrokenRedis()

    monkeypatch.setattr(mod, "_get_redis", _broken_redis)

    warnings_logged = []
    monkeypatch.setattr(mod.logger, "warning",
                        lambda msg, *a: warnings_logged.append(msg % a if a else msg))

    asyncio.run(mod._redis_is_rate_limited("mut", "9.9.9.9", 10, 60))

    assert any(
        "fallback" in w.lower() or "redis" in w.lower()
        for w in warnings_logged
    ), f"Redis hatasında warning logu bekleniyor: {warnings_logged}"


def test_redis_fallback_still_counts_requests(monkeypatch):
    """Redis yokken yerel sayaç çalışır; limiti doldurunca True döner."""
    mod = _load_web_server_standalone()
    mod._local_rate_lock = asyncio.Lock()
    mod._local_rate_limits.clear()

    async def _no_redis():
        return None

    monkeypatch.setattr(mod, "_get_redis", _no_redis)

    limit = 3
    ip = "10.0.0.1"

    results = []
    for _ in range(limit + 1):
        results.append(asyncio.run(mod._redis_is_rate_limited("test-ns", ip, limit, 60)))

    assert results[0] is False, f"İlk istek geçmeli: {results}"
    assert results[-1] is True, f"Limit aşıldıktan sonra blok bekleniyor: {results}"


def test_get_redis_connection_failure_returns_none(monkeypatch):
    """Redis ping başarısız olursa _get_redis() None döner ve warning loglar."""
    mod = _load_web_server_standalone()
    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()

    warnings_logged = []
    monkeypatch.setattr(mod.logger, "warning",
                        lambda msg, *a: warnings_logged.append(msg % a if a else msg))

    class _FailRedis:
        @classmethod
        def from_url(cls, *a, **k):
            return cls()
        async def ping(self):
            raise ConnectionRefusedError("redis not running")

    monkeypatch.setattr(mod.Redis, "from_url", lambda *a, **k: _FailRedis())

    result = asyncio.run(mod._get_redis())

    assert result is None, "Bağlantı hatasında _get_redis() None döndürmeli"
    assert any(
        "redis" in w.lower() or "fallback" in w.lower()
        for w in warnings_logged
    ), f"Bağlantı hatasında warning logu bekleniyor: {warnings_logged}"