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
