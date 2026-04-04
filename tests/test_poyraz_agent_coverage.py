from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx

if "redis.asyncio" not in sys.modules:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")

    class Redis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    fake_redis_asyncio.Redis = Redis
    fake_redis = types.ModuleType("redis")
    fake_redis_exceptions = types.ModuleType("redis.exceptions")

    class ResponseError(Exception):
        pass

    fake_redis_exceptions.ResponseError = ResponseError
    fake_redis.asyncio = fake_redis_asyncio
    fake_redis.exceptions = fake_redis_exceptions
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio
    sys.modules["redis.exceptions"] = fake_redis_exceptions

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.social_media_manager", "SocialMediaManager"),
    ("core.rag", "DocumentStore"),
]:
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        _mod.__dict__[_class_name] = type(_class_name, (), {})
        sys.modules[_mod_name] = _mod

_poyraz_spec = importlib.util.spec_from_file_location(
    "poyraz_agent_direct",
    Path(__file__).resolve().parents[1] / "agent/roles/poyraz_agent.py",
)
_poyraz_mod = importlib.util.module_from_spec(_poyraz_spec)
assert _poyraz_spec and _poyraz_spec.loader
_poyraz_spec.loader.exec_module(_poyraz_mod)
PoyrazAgent = _poyraz_mod.PoyrazAgent


class _SocialStub:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, object]] = []

    async def publish_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.ok, "sent"


def test_tool_publish_social_parses_pipe_payload() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.social = _SocialStub(ok=True)

    result = asyncio.run(
        agent._tool_publish_social("instagram|||Yeni ürün|||@sidar|||https://img|||https://link")
    )

    assert result.startswith("[SOCIAL:PUBLISHED]")
    assert agent.social.calls[0]["platform"] == "instagram"
    assert agent.social.calls[0]["destination"] == "@sidar"


def test_tool_publish_social_handles_json_payload_and_error() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.social = _SocialStub(ok=False)

    payload = json.dumps(
        {
            "platform": "facebook",
            "text": "Merhaba",
            "destination": "page-id",
            "media_url": "",
            "link_url": "https://example.com",
        }
    )
    result = asyncio.run(agent._tool_publish_social(payload))

    assert result.startswith("[SOCIAL:ERROR]")
    assert agent.social.calls[0]["platform"] == "facebook"


def test_run_task_routes_publish_social_and_blank_prompt_warning() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _fake_call_tool(name: str, arg: str) -> str:
        return f"{name}:{arg}"

    async def _fake_generate(prompt: str, mode: str) -> str:
        return f"{mode}:{prompt}"

    agent.call_tool = _fake_call_tool
    agent._generate_marketing_output = _fake_generate

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş pazarlama görevi verildi."
    assert asyncio.run(agent.run_task("publish_social|instagram|||metin")) == "publish_social:instagram|||metin"
    assert asyncio.run(agent.run_task("seo_audit|teknik seo")) == "seo_audit:teknik seo"


def test_generate_campaign_copy_persists_asset_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    persisted: dict[str, object] = {}

    class _Payload:
        channels = ["instagram", "facebook"]
        campaign_name = "Yaz Kampanyası"
        objective = "Lead"
        audience = "SMB"
        offer = "%20 indirim"
        tone = "samimi"
        call_to_action = "Hemen dene"
        store_asset = True
        campaign_id = 42
        tenant_id = "tenant-1"
        asset_title = "Q2 Kampanya"

    async def _fake_generate(prompt: str, mode: str) -> str:
        assert "Yaz Kampanyası" in prompt
        assert mode == "campaign_copy_tool"
        return "üretilen içerik"

    async def _fake_persist_content_asset(**kwargs):
        persisted.update(kwargs)
        return "ok"

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_args, **_kwargs: _Payload())
    agent._generate_marketing_output = _fake_generate
    agent._persist_content_asset = _fake_persist_content_asset

    result = asyncio.run(agent._tool_generate_campaign_copy("{}"))

    assert result == "üretilen içerik"
    assert persisted["campaign_id"] == 42
    assert persisted["asset_type"] == "campaign_copy"
    assert persisted["title"] == "Q2 Kampanya"
    assert persisted["metadata"]["channels"] == ["instagram", "facebook"]


def test_build_landing_page_persists_asset_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    persisted: dict[str, object] = {}

    class _Payload:
        sections = []
        brand_name = "Sidar"
        offer = "Demo"
        audience = "KOBİ"
        call_to_action = "Kaydol"
        tone = "güven veren"
        store_asset = True
        campaign_id = 9
        tenant_id = " "
        asset_title = " "
        channel = " "

    async def _fake_generate(prompt: str, mode: str) -> str:
        assert "Bölümler: hero, problem, çözüm, sosyal kanıt, CTA" in prompt
        assert mode == "landing_page"
        return "landing taslağı"

    async def _fake_persist_content_asset(**kwargs):
        persisted.update(kwargs)
        return "ok"

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_args, **_kwargs: _Payload())
    agent._generate_marketing_output = _fake_generate
    agent._persist_content_asset = _fake_persist_content_asset

    result = asyncio.run(agent._tool_build_landing_page("{}"))

    assert result == "landing taslağı"
    assert persisted["campaign_id"] == 9
    assert persisted["tenant_id"] == "default"
    assert persisted["title"] == "Landing Page Taslağı"
    assert persisted["channel"] == "web"


def test_ingest_video_insights_handles_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent.llm = object()
    agent.cfg = object()
    agent.docs = object()

    calls: list[dict[str, object]] = []

    class _Pipeline:
        def __init__(self, _llm, _cfg) -> None:
            return None

        async def analyze_media_source(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "scene_summary": "ürün tanıtımı",
                "document_ingest": {"doc_id": "doc-1"},
            }

    fake_multimodal = types.ModuleType("core.multimodal")
    fake_multimodal.MultimodalPipeline = _Pipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", fake_multimodal)

    success = asyncio.run(
        agent._tool_ingest_video_insights("https://youtu.be/demo|||ürün analizi|||tr|||session-1|||7")
    )
    assert success.startswith("[VIDEO:INGESTED]")
    assert "doc_id=doc-1" in success
    assert calls[0]["max_frames"] == 7
    assert calls[0]["frame_interval_seconds"] == 5.0

    class _FailingPipeline(_Pipeline):
        async def analyze_media_source(self, **kwargs):
            calls.append(kwargs)
            return {"success": False, "reason": "timeout"}

    fake_multimodal.MultimodalPipeline = _FailingPipeline
    error = asyncio.run(agent._tool_ingest_video_insights("https://youtu.be/demo|||analiz"))
    assert error == "[VIDEO:ERROR] source=https://youtu.be/demo reason=timeout"


def test_plan_service_operations_builds_structured_items_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    class _Payload:
        menu_plan = {"ana_yemek": ["Köfte", " "], "içecek": ["Ayran"]}
        vendor_assignments = {"fotoğraf": "Ajans X", "dj": " "}
        timeline = ["T-7 duyuru", " "]
        notes = "Saha ekibi hazır olsun"
        persist_checklist = True
        tenant_id = "tenant-a"
        checklist_title = "Lansman Planı"
        owner_user_id = "user-1"
        campaign_id = 12
        campaign_name = "Yaz Lansmanı"
        service_name = "Açılış"
        audience = "Genç yetişkin"

    class _Db:
        async def add_operation_checklist(self, **kwargs):
            assert kwargs["status"] == "planned"
            assert kwargs["tenant_id"] == "tenant-a"
            return SimpleNamespace(id=77, title=kwargs["title"], status=kwargs["status"])

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_args, **_kwargs: _Payload())
    async def _fake_ensure_db():
        return _Db()

    agent._ensure_db = _fake_ensure_db

    result = asyncio.run(agent._tool_plan_service_operations("{}"))
    payload = json.loads(result)

    assert payload["success"] is True
    items = payload["service_plan"]["items"]
    assert any(item["type"] == "menu_plan" and item["group"] == "ana_yemek" for item in items)
    assert any(item["type"] == "vendor_assignment" and item["role"] == "fotoğraf" for item in items)
    assert payload["service_plan"]["checklist"]["id"] == 77


def test_run_task_routes_marketing_keywords_to_strategy_mode() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _fake_generate(prompt: str, mode: str) -> str:
        return f"{mode}:{prompt}"

    agent._generate_marketing_output = _fake_generate

    result = asyncio.run(agent.run_task("Funnel optimizasyonu ve pazarlama operasyon planı hazırla"))

    assert result.startswith("marketing_strategy:")
    assert "funnel" in result.lower()


def test_ensure_db_initializes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    agent._db = None
    agent._db_lock = None
    agent.cfg = object()

    calls = {"connect": 0, "schema": 0}

    class _Db:
        def __init__(self, _cfg) -> None:
            return None

        async def connect(self):
            calls["connect"] += 1

        async def init_schema(self):
            calls["schema"] += 1

    fake_db_mod = types.ModuleType("core.db")
    fake_db_mod.Database = _Db
    monkeypatch.setitem(sys.modules, "core.db", fake_db_mod)

    first = asyncio.run(agent._ensure_db())
    second = asyncio.run(agent._ensure_db())

    assert first is second
    assert calls == {"connect": 1, "schema": 1}


def test_social_specific_tools_return_expected_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    class _Social:
        async def publish_instagram_post(self, **_kwargs):
            return True, "ok"

        async def publish_facebook_post(self, **_kwargs):
            return False, "fail"

        async def send_whatsapp_message(self, **_kwargs):
            return True, "sent"

    class _Payload:
        caption = "cap"
        image_url = "img"
        message = "msg"
        link_url = "link"
        to = "+90500"
        text = "hello"
        preview_url = True

    agent.social = _Social()
    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_a, **_k: _Payload())

    insta = asyncio.run(agent._tool_publish_instagram_post("{}"))
    face = asyncio.run(agent._tool_publish_facebook_post("{}"))
    wa = asyncio.run(agent._tool_send_whatsapp_message("{}"))

    assert insta.startswith("[INSTAGRAM:PUBLISHED]")
    assert face.startswith("[FACEBOOK:ERROR]")
    assert wa.startswith("[WHATSAPP:SENT]")

def test_init_registers_all_tools_and_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_base_init(self, cfg=None, role_name=None):
        self.cfg = SimpleNamespace(
            META_GRAPH_API_TOKEN="tok",
            INSTAGRAM_BUSINESS_ACCOUNT_ID="ig",
            FACEBOOK_PAGE_ID="fb",
            WHATSAPP_PHONE_NUMBER_ID="wa",
            META_GRAPH_API_VERSION="v99",
            RAG_DIR="/tmp/rag",
            RAG_TOP_K=3,
            RAG_CHUNK_SIZE=100,
            RAG_CHUNK_OVERLAP=10,
            USE_GPU=False,
            GPU_DEVICE="cpu",
            GPU_MIXED_PRECISION=False,
        )
        captured["role_name"] = role_name

    class _FakeWeb:
        def __init__(self, cfg):
            captured["web_cfg"] = cfg

    class _FakeSocial:
        def __init__(self, **kwargs):
            captured["social_kwargs"] = kwargs

    class _FakeDocs:
        def __init__(self, rag_dir, **kwargs):
            captured["rag_dir"] = str(rag_dir)
            captured["docs_kwargs"] = kwargs

    tools: list[str] = []

    def _fake_register_tool(self, name, _fn):
        tools.append(name)

    monkeypatch.setattr(_poyraz_mod.BaseAgent, "__init__", _fake_base_init)
    monkeypatch.setattr(_poyraz_mod, "WebSearchManager", _FakeWeb)
    monkeypatch.setattr(_poyraz_mod, "SocialMediaManager", _FakeSocial)
    monkeypatch.setattr(_poyraz_mod, "DocumentStore", _FakeDocs)
    monkeypatch.setattr(_poyraz_mod.PoyrazAgent, "register_tool", _fake_register_tool)

    agent = _poyraz_mod.PoyrazAgent()

    assert isinstance(agent, _poyraz_mod.PoyrazAgent)
    assert captured["role_name"] == "poyraz"
    assert captured["rag_dir"] == "/tmp/rag"
    assert captured["social_kwargs"]["api_version"] == "v99"
    assert set(tools) == {
        "web_search",
        "fetch_url",
        "search_docs",
        "publish_social",
        "publish_instagram_post",
        "publish_facebook_post",
        "send_whatsapp_message",
        "build_landing_page",
        "generate_campaign_copy",
        "ingest_video_insights",
        "create_marketing_campaign",
        "store_content_asset",
        "create_operation_checklist",
        "plan_service_operations",
    }


def test_tool_web_fetch_and_search_docs_paths() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    class _Web:
        async def search(self, arg: str):
            return True, f"SEARCH:{arg}"

        async def fetch_url(self, arg: str):
            return False, f"FETCH:{arg}"

    class _AwaitableDocs:
        async def _co(self):
            return True, "DOCS-AWAIT"

        def search(self, *_args):
            return self._co()

    class _SyncDocs:
        def search(self, *_args):
            return True, "DOCS-SYNC"

    agent.web = _Web()
    agent.docs = _AwaitableDocs()
    assert asyncio.run(agent._tool_web_search("q")) == "SEARCH:q"
    assert asyncio.run(agent._tool_fetch_url("u")) == "FETCH:u"
    assert asyncio.run(agent._tool_search_docs("x")) == "DOCS-AWAIT"

    agent.docs = _SyncDocs()
    assert asyncio.run(agent._tool_search_docs("x")) == "DOCS-SYNC"


def test_create_campaign_store_asset_and_checklist_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    class _CampaignPayload:
        tenant_id = ""
        name = " Kamp "
        channel = "social"
        objective = "lead"
        status = ""
        owner_user_id = "u1"
        budget = "12.5"
        metadata = {"k": "v"}
        campaign_id = None

    class _AssetPayload:
        campaign_id = "5"
        tenant_id = ""
        asset_type = "copy"
        title = "  Başlık "
        content = "icerik"
        channel = "insta"
        metadata = {"m": 1}

    class _ChecklistPayload:
        tenant_id = ""
        title = " Plan "
        items = ["a", "b"]
        status = ""
        owner_user_id = "owner"
        campaign_id = 3

    class _Db:
        async def upsert_marketing_campaign(self, **kwargs):
            assert kwargs["tenant_id"] == "default"
            assert kwargs["status"] == "draft"
            return SimpleNamespace(id=11, **kwargs)

        async def add_operation_checklist(self, **kwargs):
            assert kwargs["tenant_id"] == "default"
            assert kwargs["status"] == "pending"
            return SimpleNamespace(id=21, campaign_id=kwargs["campaign_id"], tenant_id=kwargs["tenant_id"], title=kwargs["title"], status=kwargs["status"], items_json='["a","b"]')

    async def _fake_ensure_db():
        return _Db()

    persisted: dict[str, object] = {}

    async def _fake_persist_content_asset(**kwargs):
        persisted.update(kwargs)
        return "stored"

    agent._ensure_db = _fake_ensure_db
    agent._persist_content_asset = _fake_persist_content_asset

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda tool, _raw: {
        "create_marketing_campaign": _CampaignPayload(),
        "store_content_asset": _AssetPayload(),
        "create_operation_checklist": _ChecklistPayload(),
    }[tool])

    campaign = json.loads(asyncio.run(agent._tool_create_marketing_campaign("{}")))
    assert campaign["campaign"]["id"] == 11

    stored = asyncio.run(agent._tool_store_content_asset("{}"))
    assert stored == "stored"
    assert persisted["campaign_id"] == 5
    assert persisted["tenant_id"] == "default"

    checklist = json.loads(asyncio.run(agent._tool_create_operation_checklist("{}")))
    assert checklist["checklist"]["id"] == 21


def test_generate_marketing_output_and_additional_run_task_routes() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)
    calls: list[tuple[str, str]] = []

    async def _fake_call_tool(name: str, arg: str) -> str:
        return f"tool:{name}:{arg}"

    async def _fake_llm(messages, **kwargs):
        calls.append((messages[0]["content"], kwargs["system_prompt"]))
        return "llm-ok"

    agent.call_tool = _fake_call_tool
    agent.call_llm = _fake_llm

    out = asyncio.run(agent._generate_marketing_output(" deneme ", "audience_ops"))
    assert out == "llm-ok"
    assert "Görev modu: audience_ops" in calls[0][0]

    assert asyncio.run(agent.run_task("web_search|kedi")) == "tool:web_search:kedi"
    assert asyncio.run(agent.run_task("fetch_url|https://a")) == "tool:fetch_url:https://a"
    assert asyncio.run(agent.run_task("search_docs|prompt")) == "tool:search_docs:prompt"
    assert asyncio.run(agent.run_task("landing_page|brief")) == "tool:build_landing_page:brief"
    assert asyncio.run(agent.run_task("generate_campaign_copy|brief")) == "tool:generate_campaign_copy:brief"
    assert asyncio.run(agent.run_task("publish_instagram_post|{}")) == "tool:publish_instagram_post:{}"
    assert asyncio.run(agent.run_task("publish_facebook_post|{}")) == "tool:publish_facebook_post:{}"
    assert asyncio.run(agent.run_task("send_whatsapp_message|{}")) == "tool:send_whatsapp_message:{}"
    assert asyncio.run(agent.run_task("analyze_video|{}")) == "tool:ingest_video_insights:{}"
    assert asyncio.run(agent.run_task("create_marketing_campaign|{}")) == "tool:create_marketing_campaign:{}"
    assert asyncio.run(agent.run_task("store_content_asset|{}")) == "tool:store_content_asset:{}"
    assert asyncio.run(agent.run_task("create_operation_checklist|{}")) == "tool:create_operation_checklist:{}"
    assert asyncio.run(agent.run_task("plan_service_operations|{}")) == "tool:plan_service_operations:{}"


def test_run_task_non_tool_modes_and_fallbacks() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _fake_call_tool(name: str, arg: str) -> str:
        return f"{name}:{arg}"

    async def _fake_generate(prompt: str, mode: str) -> str:
        return f"{mode}:{prompt}"

    agent.call_tool = _fake_call_tool
    agent._generate_marketing_output = _fake_generate

    assert asyncio.run(agent.run_task("campaign_copy|x")) == "campaign_copy:x"
    assert asyncio.run(agent.run_task("audience_ops|x")) == "audience_ops:x"
    assert asyncio.run(agent.run_task("research_to_marketing|x")) == "research_to_marketing:x"
    assert asyncio.run(agent.run_task("Landing page içeriği hazırla")) .startswith("build_landing_page:{")
    assert asyncio.run(agent.run_task("genel metin")) == "marketing_general:genel metin"


def test_plan_service_operations_without_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    class _Payload:
        menu_plan = {"ana": []}
        vendor_assignments = {"dj": " "}
        timeline = [" "]
        notes = " "
        persist_checklist = False
        tenant_id = ""
        checklist_title = ""
        owner_user_id = ""
        campaign_id = None
        campaign_name = "Kamp"
        service_name = "Servis"
        audience = "Genel"

    monkeypatch.setattr(_poyraz_mod, "parse_tool_argument", lambda *_a, **_k: _Payload())
    payload = json.loads(asyncio.run(agent._tool_plan_service_operations("{}")))
    assert payload["service_plan"]["items"] == []
    assert "checklist" not in payload["service_plan"]


def test_build_and_campaign_copy_without_json_payload() -> None:
    agent = PoyrazAgent.__new__(PoyrazAgent)

    async def _fake_generate(prompt: str, mode: str) -> str:
        return f"{mode}:{prompt.splitlines()[-1]}"

    agent._generate_marketing_output = _fake_generate

    assert asyncio.run(agent._tool_build_landing_page("ham brief")).startswith("landing_page:ham brief")
    assert asyncio.run(agent._tool_generate_campaign_copy("ham copy")).startswith("campaign_copy_tool:ham copy")
