"""
Prompt Registry API endpoint testleri:
  GET  /admin/prompts          → list_prompts
  GET  /admin/prompts/active   → get_active_prompt
  POST /admin/prompts          → upsert_prompt
  POST /admin/prompts/activate → activate_prompt

Test stratejisi: web_server.py dinamik yükleme + bağımlılık enjeksiyonu.
_require_admin_user bağımlılığı doğrudan admin kullanıcı nesnesi geçilerek atlanır.
"""

import asyncio
import importlib.util
import io
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Stub sınıfları (web_server_runtime.py örüntüsü) ─────────────────────

class _FakeResponse:
    def __init__(self, content=None, status_code=200, **_kw):
        self.content = content
        self.status_code = status_code


class _FakeJSONResponse(_FakeResponse):
    pass


class _FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeFastAPI:
    def __init__(self, *a, **kw): pass
    def get(self, *a, **kw): return lambda fn: fn
    def post(self, *a, **kw): return lambda fn: fn
    def delete(self, *a, **kw): return lambda fn: fn
    def put(self, *a, **kw): return lambda fn: fn
    def websocket(self, *a, **kw): return lambda fn: fn
    def middleware(self, *a, **kw): return lambda fn: fn
    def add_middleware(self, *a, **kw): return None
    def mount(self, *a, **kw): return None
    def on_event(self, *a, **kw): return lambda fn: fn


class _FakeRequest:
    def __init__(self, *, path="/", headers=None):
        self.url = SimpleNamespace(path=path)
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace()

    async def json(self): return {}
    async def body(self): return b""


def _install_stubs():
    # ── jwt stub ──────────────────────────────────────────────────────────
    jwt_stub = types.ModuleType("jwt")
    jwt_stub.encode = lambda payload, key, algorithm="HS256": "stub-token"
    jwt_stub.decode = lambda token, key, algorithms=None: {}
    jwt_stub.PyJWTError = type("PyJWTError", (Exception,), {})
    jwt_stub.DecodeError = type("DecodeError", (Exception,), {})
    jwt_stub.ExpiredSignatureError = type("ExpiredSignatureError", (Exception,), {})
    sys.modules["jwt"] = jwt_stub

    # ── pydantic stub ─────────────────────────────────────────────────────
    pydantic_stub = types.ModuleType("pydantic")
    pydantic_stub.BaseModel = object
    pydantic_stub.Field = lambda *a, **k: None
    sys.modules["pydantic"] = pydantic_stub

    # ── managers.system_health stub ───────────────────────────────────────
    mgr_pkg = types.ModuleType("managers")
    mgr_pkg.__path__ = []
    sys.modules.setdefault("managers", mgr_pkg)
    sh_stub = types.ModuleType("managers.system_health")
    sh_stub.render_llm_metrics_prometheus = lambda col: ""
    sys.modules["managers.system_health"] = sh_stub

    # ── core / llm_metrics stub (dotenv zincirini kırar) ──────────────────
    if "core" not in sys.modules:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = []
        sys.modules["core"] = core_pkg

    class _MetricsCol:
        def snapshot(self): return {"totals": {}}

    core_metrics_mod2 = types.ModuleType("core.llm_metrics")
    core_metrics_mod2.get_current_metrics_user_id = lambda: None
    core_metrics_mod2.get_llm_metrics_collector = lambda: _MetricsCol()
    sys.modules["core.llm_metrics"] = core_metrics_mod2

    # ── fastapi stub ──────────────────────────────────────────────────────
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.FastAPI = _FakeFastAPI
    fastapi_mod.Request = _FakeRequest
    fastapi_mod.UploadFile = object
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
    resp_mod.HTMLResponse = _FakeResponse
    resp_mod.FileResponse = _FakeResponse

    static_mod = types.ModuleType("fastapi.staticfiles")
    static_mod.StaticFiles = lambda directory: SimpleNamespace(directory=directory)

    redis_mod = types.ModuleType("redis.asyncio")
    class _Redis:
        @classmethod
        def from_url(cls, *a, **kw): return cls()
        async def ping(self): return True
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
        def initialize_directories(): return None
    cfg_mod.Config = _Config

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object

    metrics_mod = types.ModuleType("core.llm_metrics")
    class _Col:
        def snapshot(self): return {"totals": {"calls": 0, "total_tokens": 0}}
    metrics_mod.get_llm_metrics_collector = lambda: _Col()

    es_mod = types.ModuleType("agent.core.event_stream")
    class _Bus:
        def subscribe(self):
            return "sub-x", asyncio.Queue()
        def unsubscribe(self, _): return None
        async def publish(self, *a): return None
    es_mod.get_agent_event_bus = lambda: _Bus()

    llm_mod = types.ModuleType("core.llm_client")
    class _LLMAPIError(Exception):
        def __init__(self, msg="err", provider="stub", status_code=None, retryable=False):
            super().__init__(msg)
            self.provider = provider
            self.status_code = status_code
            self.retryable = retryable
    llm_mod.LLMAPIError = _LLMAPIError
    llm_mod.LLMClient = object

    sys.modules["fastapi"] = fastapi_mod
    sys.modules["fastapi.middleware.cors"] = cors_mod
    sys.modules["fastapi.responses"] = resp_mod
    sys.modules["fastapi.staticfiles"] = static_mod
    sys.modules["redis.asyncio"] = redis_mod
    sys.modules["uvicorn"] = uvicorn_mod
    sys.modules["config"] = cfg_mod
    sys.modules["agent.sidar_agent"] = agent_mod
    sys.modules["core.llm_metrics"] = metrics_mod
    sys.modules["core.llm_client"] = llm_mod
    sys.modules["agent.core.event_stream"] = es_mod

    for pkg, path in [("agent", "agent"), ("agent.core", "agent/core"), ("core", "core")]:
        if pkg not in sys.modules:
            m = types.ModuleType(pkg)
            m.__path__ = [str(Path(path).resolve())]
            sys.modules[pkg] = m


def _load_ws():
    _install_stubs()
    spec = importlib.util.spec_from_file_location("ws_prompt_registry_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# ─── Test yardımcıları ──────────────────────────────────────────────────────

_ADMIN_USER = SimpleNamespace(id="admin-1", username="admin", role="admin")


def _make_prompt(
    id=1,
    role_name="system",
    prompt_text="Sen yardımcı bir asistansın.",
    version=1,
    is_active=True,
    created_at="2026-01-01T00:00:00",
    updated_at="2026-01-01T00:00:00",
):
    return SimpleNamespace(
        id=id,
        role_name=role_name,
        prompt_text=prompt_text,
        version=version,
        is_active=is_active,
        created_at=created_at,
        updated_at=updated_at,
    )


def _make_agent_with_db(**db_methods):
    """db_methods: her anahtar async callable."""
    class _DB:
        pass

    db = _DB()
    for name, fn in db_methods.items():
        setattr(db, name, fn)

    return SimpleNamespace(
        memory=SimpleNamespace(db=db),
        system_prompt="",
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/prompts
# ══════════════════════════════════════════════════════════════════════════════

def test_list_prompts_returns_all(monkeypatch):
    """Rol filtresi olmadan tüm prompt kayıtları döndürülmeli."""
    mod = _load_ws()
    prompts = [_make_prompt(id=1, role_name="system"), _make_prompt(id=2, role_name="coder")]

    async def _list_prompts(role_name=None):
        return prompts

    agent = _make_agent_with_db(list_prompts=_list_prompts)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    result = asyncio.run(mod.admin_list_prompts(role_name="", _user=_ADMIN_USER))
    assert isinstance(result, _FakeJSONResponse)
    items = result.content["items"]
    assert len(items) == 2
    assert items[0]["id"] == 1
    assert items[1]["role_name"] == "coder"


def test_list_prompts_filtered_by_role(monkeypatch):
    """role_name parametresi DB'ye geçirilmeli; yalnızca eşleşen kayıtlar dönmeli."""
    mod = _load_ws()
    received_role: list = []

    async def _list_prompts(role_name=None):
        received_role.append(role_name)
        return [_make_prompt(id=3, role_name="researcher")]

    agent = _make_agent_with_db(list_prompts=_list_prompts)
    mod.get_agent = lambda: asyncio.coroutine(lambda: agent)()

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    result = asyncio.run(mod.admin_list_prompts(role_name="researcher", _user=_ADMIN_USER))
    assert received_role[0] == "researcher"
    assert result.content["items"][0]["role_name"] == "researcher"


def test_list_prompts_empty_returns_empty_list():
    """Kayıt yoksa boş items listesi döndürülmeli."""
    mod = _load_ws()

    async def _list_prompts(role_name=None):
        return []

    agent = _make_agent_with_db(list_prompts=_list_prompts)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    result = asyncio.run(mod.admin_list_prompts(role_name="", _user=_ADMIN_USER))
    assert result.content["items"] == []


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/prompts/active
# ══════════════════════════════════════════════════════════════════════════════

def test_active_prompt_found():
    """Aktif prompt mevcut olduğunda serileştirilmiş kayıt dönmeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=5, role_name="system", is_active=True)

    async def _get_active_prompt(role_name):
        return prompt

    agent = _make_agent_with_db(get_active_prompt=_get_active_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    result = asyncio.run(mod.admin_active_prompt(role_name="system", _user=_ADMIN_USER))
    assert result.content["id"] == 5
    assert result.content["is_active"] is True
    assert result.content["role_name"] == "system"


def test_active_prompt_not_found_raises_404():
    """Aktif prompt yoksa 404 HTTPException fırlatılmalı."""
    mod = _load_ws()

    async def _get_active_prompt(role_name):
        return None

    agent = _make_agent_with_db(get_active_prompt=_get_active_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(mod.admin_active_prompt(role_name="nonexistent", _user=_ADMIN_USER))

    assert exc_info.value.status_code == 404


def test_active_prompt_default_role_is_system():
    """role_name varsayılanı 'system' olmalı."""
    mod = _load_ws()
    received: list = []

    async def _get_active_prompt(role_name):
        received.append(role_name)
        return _make_prompt()

    agent = _make_agent_with_db(get_active_prompt=_get_active_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    asyncio.run(mod.admin_active_prompt(_user=_ADMIN_USER))
    assert received[0] == "system"


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/prompts
# ══════════════════════════════════════════════════════════════════════════════

def test_upsert_prompt_success():
    """Geçerli payload ile upsert başarılı olmalı; serileştirilmiş kayıt dönmeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=10, role_name="coder", prompt_text="Kod yaz.")

    async def _upsert_prompt(role_name, prompt_text, activate):
        return prompt

    agent = _make_agent_with_db(upsert_prompt=_upsert_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="coder", prompt_text="Kod yaz.", activate=True)
    result = asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert result.content["id"] == 10
    assert result.content["role_name"] == "coder"
    assert result.content["prompt_text"] == "Kod yaz."


def test_upsert_system_prompt_updates_agent_system_prompt():
    """role_name='system' ve is_active=True iken agent.system_prompt güncellenmeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=11, role_name="system", prompt_text="Yeni sistem promptu.", is_active=True)

    async def _upsert_prompt(role_name, prompt_text, activate):
        return prompt

    agent = _make_agent_with_db(upsert_prompt=_upsert_prompt)
    agent.system_prompt = "eski prompt"

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="system", prompt_text="Yeni sistem promptu.", activate=True)
    asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert agent.system_prompt == "Yeni sistem promptu."


def test_upsert_system_prompt_not_active_does_not_update_agent():
    """role_name='system' ama is_active=False iken agent.system_prompt değişmemeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=12, role_name="system", prompt_text="Taslak prompt.", is_active=False)

    async def _upsert_prompt(role_name, prompt_text, activate):
        return prompt

    agent = _make_agent_with_db(upsert_prompt=_upsert_prompt)
    agent.system_prompt = "mevcut sistem promptu"

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="system", prompt_text="Taslak prompt.", activate=False)
    asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert agent.system_prompt == "mevcut sistem promptu"


def test_upsert_prompt_empty_role_name_raises_400():
    """role_name boş geçildiğinde 400 HTTPException fırlatılmalı."""
    mod = _load_ws()

    async def _get_agent():
        return _make_agent_with_db()

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="  ", prompt_text="Bir şey.", activate=True)
    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert exc_info.value.status_code == 400


def test_upsert_prompt_empty_text_raises_400():
    """prompt_text boş geçildiğinde 400 HTTPException fırlatılmalı."""
    mod = _load_ws()

    async def _get_agent():
        return _make_agent_with_db()

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="system", prompt_text="  ", activate=True)
    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert exc_info.value.status_code == 400


def test_upsert_prompt_role_name_lowercased():
    """role_name büyük harfle gelse de küçük harfe çevrilmeli."""
    mod = _load_ws()
    received: list = []

    async def _upsert_prompt(role_name, prompt_text, activate):
        received.append(role_name)
        return _make_prompt(role_name=role_name)

    agent = _make_agent_with_db(upsert_prompt=_upsert_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(role_name="CODER", prompt_text="Kod yaz.", activate=False)
    asyncio.run(mod.admin_upsert_prompt(payload=payload, _user=_ADMIN_USER))

    assert received[0] == "coder"


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/prompts/activate
# ══════════════════════════════════════════════════════════════════════════════

def test_activate_prompt_success():
    """Mevcut prompt etkinleştirilince serileştirilmiş kayıt dönmeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=7, role_name="coder", is_active=True)

    async def _activate_prompt(prompt_id):
        return prompt

    agent = _make_agent_with_db(activate_prompt=_activate_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(prompt_id=7)
    result = asyncio.run(mod.admin_activate_prompt(payload=payload, _user=_ADMIN_USER))

    assert result.content["id"] == 7
    assert result.content["is_active"] is True


def test_activate_prompt_not_found_raises_404():
    """prompt_id bulunamazsa 404 HTTPException fırlatılmalı."""
    mod = _load_ws()

    async def _activate_prompt(prompt_id):
        return None

    agent = _make_agent_with_db(activate_prompt=_activate_prompt)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(prompt_id=999)
    with pytest.raises(_FakeHTTPException) as exc_info:
        asyncio.run(mod.admin_activate_prompt(payload=payload, _user=_ADMIN_USER))

    assert exc_info.value.status_code == 404


def test_activate_system_prompt_updates_agent():
    """Etkinleştirilen prompt role_name='system' ise agent.system_prompt güncellenmeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=8, role_name="system", prompt_text="Aktif sistem promptu.")

    async def _activate_prompt(prompt_id):
        return prompt

    agent = _make_agent_with_db(activate_prompt=_activate_prompt)
    agent.system_prompt = "eski"

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(prompt_id=8)
    asyncio.run(mod.admin_activate_prompt(payload=payload, _user=_ADMIN_USER))

    assert agent.system_prompt == "Aktif sistem promptu."


def test_activate_non_system_prompt_does_not_change_system_prompt():
    """role_name != 'system' ise agent.system_prompt değişmemeli."""
    mod = _load_ws()
    prompt = _make_prompt(id=9, role_name="researcher", prompt_text="Araştır.")

    async def _activate_prompt(prompt_id):
        return prompt

    agent = _make_agent_with_db(activate_prompt=_activate_prompt)
    agent.system_prompt = "sistem promptu sabit kalmalı"

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    payload = SimpleNamespace(prompt_id=9)
    asyncio.run(mod.admin_activate_prompt(payload=payload, _user=_ADMIN_USER))

    assert agent.system_prompt == "sistem promptu sabit kalmalı"


# ─── _serialize_prompt yardımcı fonksiyon testleri ──────────────────────────

def test_serialize_prompt_all_fields():
    """_serialize_prompt tüm alanları doğru tiplerle serileştirmeli."""
    mod = _load_ws()
    record = _make_prompt(id=42, role_name="system", prompt_text="Test.", version=3, is_active=True)
    out = mod._serialize_prompt(record)

    assert out["id"] == 42
    assert out["role_name"] == "system"
    assert out["prompt_text"] == "Test."
    assert out["version"] == 3
    assert out["is_active"] is True
    assert isinstance(out["created_at"], str)
    assert isinstance(out["updated_at"], str)


def test_serialize_prompt_numeric_type_coercion():
    """_serialize_prompt id ve version alanlarını int'e dönüştürmeli."""
    mod = _load_ws()
    record = SimpleNamespace(
        id="99",            # string olarak gelirse int yapmalı
        role_name="coder",
        prompt_text="x",
        version="2",
        is_active=1,        # int→bool
        created_at=None,
        updated_at=None,
    )
    out = mod._serialize_prompt(record)
    assert out["id"] == 99
    assert isinstance(out["id"], int)
    assert out["version"] == 2
    assert isinstance(out["is_active"], bool)