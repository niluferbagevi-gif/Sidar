"""
agent/roles/poyraz_agent.py için birim testleri.
"""
from __future__ import annotations

import asyncio
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_poyraz_deps():
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent"); pkg.__path__ = [str(_proj / "agent")]; pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core"); core.__path__ = [str(_proj / "agent" / "core")]; core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"): c.__path__ = [str(_proj / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        contracts = types.ModuleType("agent.core.contracts")
        contracts.is_delegation_request = lambda v: False
        sys.modules["agent.core.contracts"] = contracts

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")
        class _Config:
            AI_PROVIDER = "ollama"; OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_test"
            USE_GPU = False; GPU_DEVICE = 0; GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"; RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000; RAG_CHUNK_OVERLAP = 200
            META_GRAPH_API_TOKEN = ""; INSTAGRAM_BUSINESS_ACCOUNT_ID = ""
            FACEBOOK_PAGE_ID = ""; WHATSAPP_PHONE_NUMBER_ID = ""
            META_GRAPH_API_VERSION = "v20.0"
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core stubs — always replace so real modules don't interfere
    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock(); mock_llm.chat = AsyncMock(return_value="pazarlama içeriği")
    llm_stub.LLMClient = MagicMock(return_value=mock_llm)
    sys.modules["core.llm_client"] = llm_stub

    rag_stub = types.ModuleType("core.rag")
    mock_docs = MagicMock()
    mock_docs.search = MagicMock(return_value=(True, "doküman sonucu"))
    rag_stub.DocumentStore = MagicMock(return_value=mock_docs)
    sys.modules["core.rag"] = rag_stub

    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")

    # managers stubs
    for mod, cls in [
        ("managers", None),
        ("managers.web_search", "WebSearchManager"),
        ("managers.social_media_manager", "SocialMediaManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls == "WebSearchManager":
            mock_web = MagicMock()
            mock_web.search = AsyncMock(return_value=(True, "web sonucu"))
            mock_web.fetch_url = AsyncMock(return_value=(True, "url içeriği"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_web)
        elif cls == "SocialMediaManager":
            mock_social = MagicMock()
            mock_social.publish_content = AsyncMock(return_value=(True, "yayınlandı"))
            mock_social.publish_instagram_post = AsyncMock(return_value=(True, "ig yayınlandı"))
            mock_social.publish_facebook_post = AsyncMock(return_value=(True, "fb yayınlandı"))
            mock_social.send_whatsapp_message = AsyncMock(return_value=(True, "wa gönderildi"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_social)

    # agent.tooling stub (poyraz_agent try/except ile import eder)
    if "agent.tooling" not in sys.modules:
        tooling = types.ModuleType("agent.tooling")
        class _FallbackPayload:
            def __init__(self, d): self.__dict__.update(d)
            def __getattr__(self, _): return ""
        def parse_tool_argument(tool_name, raw_arg):
            import json as _json
            try: return _FallbackPayload(_json.loads(raw_arg))
            except Exception: return _FallbackPayload({})
        tooling.parse_tool_argument = parse_tool_argument
        sys.modules["agent.tooling"] = tooling

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        class _BaseAgent:
            def __init__(self, *a, cfg=None, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock(); self.llm.chat = AsyncMock(return_value="pazarlama içeriği")
                self.tools = {}
            def register_tool(self, name, fn): self.tools[name] = fn
            async def call_tool(self, name, arg):
                if name not in self.tools: return f"HATA: {name} bulunamadı"
                return await self.tools[name](arg)
            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, **kw): return "pazarlama içeriği üretildi"
        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_poyraz():
    _stub_poyraz_deps()
    sys.modules.pop("agent.roles.poyraz_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles"); roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.poyraz_agent as m
    return m


class TestPoyrazAgentInit:
    def test_instantiation(self):
        assert _get_poyraz().PoyrazAgent() is not None

    def test_role_name(self):
        assert _get_poyraz().PoyrazAgent().role_name == "poyraz"

    def test_tools_registered(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        for tool in ("web_search", "fetch_url", "search_docs", "publish_social",
                     "build_landing_page", "generate_campaign_copy",
                     "create_marketing_campaign"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"

    def test_system_prompt_contains_poyraz(self):
        m = _get_poyraz()
        assert "Poyraz" in m.PoyrazAgent.SYSTEM_PROMPT


class TestPoyrazAgentRunTask:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_warning(self):
        m = _get_poyraz()
        result = await m.PoyrazAgent().run_task("")
        assert "UYARI" in result

    @pytest.mark.asyncio
    async def test_web_search_routing(self):
        m = _get_poyraz()
        result = await m.PoyrazAgent().run_task("web_search|SEO stratejileri")
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_url_routing(self):
        m = _get_poyraz()
        result = await m.PoyrazAgent().run_task("fetch_url|https://example.com")
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_docs_routing(self):
        m = _get_poyraz()
        result = await m.PoyrazAgent().run_task("search_docs|pazarlama stratejisi")
        assert result is not None

    @pytest.mark.asyncio
    async def test_publish_social_routing_text(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        result = await agent.run_task("publish_social|twitter|||merhaba dünya")
        assert "SOCIAL" in result

    @pytest.mark.asyncio
    async def test_default_generates_content(self):
        m = _get_poyraz()
        result = await m.PoyrazAgent().run_task("yaz kampanyası için içerik üret")
        assert result is not None


class TestPoyrazAgentTools:
    @pytest.mark.asyncio
    async def test_web_search_tool(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        result = await agent.call_tool("web_search", "dijital pazarlama")
        assert "web sonucu" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        result = await agent.call_tool("unknown_xyz", "arg")
        assert "HATA" in result or "hata" in result.lower()

    @pytest.mark.asyncio
    async def test_publish_social_json_payload_success_branch(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        agent.social.publish_content = AsyncMock(return_value=(True, "ok-1"))

        payload = {
            "platform": "instagram",
            "text": "kampanya metni",
            "destination": "audience-segment-a",
            "media_url": "https://img.example.com/promo.jpg",
            "link_url": "https://example.com",
        }
        raw = __import__("json").dumps(payload, ensure_ascii=False)
        result = await agent._tool_publish_social(raw)

        assert result.startswith("[SOCIAL:PUBLISHED]")
        assert "platform=instagram" in result
        agent.social.publish_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_social_pipe_payload_error_branch(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        agent.social.publish_content = AsyncMock(return_value=(False, "api down"))

        result = await agent._tool_publish_social("facebook|||metin|||dest|||media|||link")

        assert result.startswith("[SOCIAL:ERROR]")
        assert "platform=facebook" in result
        assert "api down" in result


class TestPoyrazAgentPromptVariations:
    @pytest.mark.parametrize(
        "prompt, expected_fragment",
        [
            ("web_search|growth funnel", "web sonucu"),
            ("fetch_url|https://example.com", "url içeriği"),
            ("search_docs|kampanya", "doküman sonucu"),
            ("publish_social|instagram|||merhaba", "SOCIAL"),
        ],
    )
    def test_prompt_variations_for_tool_routing(self, prompt, expected_fragment):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        result = asyncio.run(agent.run_task(prompt))
        assert expected_fragment in result

    def test_marketing_keyword_prompt_uses_generation_path(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="[MARKETING:marketing_strategy]"))
        result = asyncio.run(agent.run_task("SEO ve pazarlama funnel planı hazırla"))
        assert "MARKETING:marketing_strategy" in result


class TestPoyrazServiceOperations:
    @pytest.mark.asyncio
    async def test_plan_service_operations_without_persist(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        payload = {
            "campaign_name": "İlkbahar Kampanyası",
            "service_name": "Brunch",
            "audience": "Aile",
            "menu_plan": {"ana_yemek": ["  Pizza  ", "", "Pasta"]},
            "vendor_assignments": {"DJ": "  Murat  ", "Fotoğrafçı": ""},
            "timeline": ["10:00 kurulum", " ", "12:00 açılış"],
            "notes": "  Ek personel ayarla ",
            "persist_checklist": False,
        }
        result = await agent._tool_plan_service_operations(__import__("json").dumps(payload, ensure_ascii=False))
        parsed = __import__("json").loads(result)
        items = parsed["service_plan"]["items"]
        assert parsed["success"] is True
        assert any(item["type"] == "menu_plan" for item in items)
        assert any(item["type"] == "vendor_assignment" for item in items)
        assert any(item["type"] == "timeline" for item in items)
        assert any(item["type"] == "note" for item in items)
        assert "checklist" not in parsed["service_plan"]

    @pytest.mark.asyncio
    async def test_plan_service_operations_with_persist_adds_checklist(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        fake_db = MagicMock()
        fake_db.add_operation_checklist = AsyncMock(
            return_value=types.SimpleNamespace(id=42, title="Operasyon", status="planned")
        )
        monkeypatch.setattr(agent, "_ensure_db", AsyncMock(return_value=fake_db))

        payload = {
            "campaign_name": "Yaz Kampanyası",
            "service_name": "After Party",
            "audience": "Genç yetişkin",
            "menu_plan": {},
            "vendor_assignments": {},
            "timeline": [],
            "notes": "",
            "persist_checklist": True,
            "tenant_id": "tenant-1",
            "checklist_title": "Operasyon",
            "owner_user_id": "owner-1",
            "campaign_id": 7,
        }
        result = await agent._tool_plan_service_operations(__import__("json").dumps(payload, ensure_ascii=False))
        parsed = __import__("json").loads(result)
        assert parsed["success"] is True
        assert parsed["service_plan"]["checklist"]["id"] == 42
        fake_db.add_operation_checklist.assert_awaited_once()


class TestPoyrazAdditionalCoverage:
    @pytest.mark.asyncio
    async def test_social_channel_specific_tools_success_and_error(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()

        agent.social.publish_instagram_post = AsyncMock(return_value=(True, "ig-ok"))
        result = await agent._tool_publish_instagram_post('{"caption":"hello","image_url":"https://img"}')
        assert result.startswith("[INSTAGRAM:PUBLISHED]")

        agent.social.publish_facebook_post = AsyncMock(return_value=(False, "fb-down"))
        result = await agent._tool_publish_facebook_post('{"message":"msg","link_url":"https://lnk"}')
        assert result.startswith("[FACEBOOK:ERROR]")

        agent.social.send_whatsapp_message = AsyncMock(return_value=(True, "wa-ok"))
        result = await agent._tool_send_whatsapp_message('{"to":"+90555","text":"selam","preview_url":true}')
        assert result.startswith("[WHATSAPP:SENT]")

    @pytest.mark.asyncio
    async def test_build_landing_page_with_store_asset(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="lp-content"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        payload = {
            "brand_name": "Sidar",
            "offer": "İlk teklif",
            "audience": "KOBİ",
            "call_to_action": "Demo al",
            "tone": "professional",
            "sections": ["hero", "cta"],
            "store_asset": True,
            "campaign_id": 4,
            "tenant_id": "tenant-a",
            "asset_title": "LP",
            "channel": "web",
        }
        result = await agent._tool_build_landing_page(__import__("json").dumps(payload, ensure_ascii=False))
        assert result == "lp-content"
        agent._persist_content_asset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_campaign_copy_with_store_asset(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="copy-content"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        payload = {
            "campaign_name": "Bahar",
            "objective": "lead",
            "audience": "genç",
            "channels": ["instagram"],
            "offer": "indirim",
            "tone": "friendly",
            "call_to_action": "Katıl",
            "store_asset": True,
            "campaign_id": 8,
            "tenant_id": "tenant-b",
            "asset_title": "Copy",
        }
        result = await agent._tool_generate_campaign_copy(__import__("json").dumps(payload, ensure_ascii=False))
        assert result == "copy-content"
        agent._persist_content_asset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_ingest_success_and_error_paths(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()

        pipe_mod = types.ModuleType("core.multimodal")
        pipeline = MagicMock()
        pipeline.analyze_media_source = AsyncMock(return_value={"success": False, "reason": "timeout"})
        pipe_mod.MultimodalPipeline = MagicMock(return_value=pipeline)
        sys.modules["core.multimodal"] = pipe_mod

        err = await agent._tool_ingest_video_insights("https://v|||özet|||tr|||s1|||4")
        assert err.startswith("[VIDEO:ERROR]")

        pipeline.analyze_media_source = AsyncMock(
            return_value={"success": True, "scene_summary": "s", "document_ingest": {"doc_id": "d1"}}
        )
        ok = await agent._tool_ingest_video_insights(
            '{"source_url":"https://v","prompt":"özet","language":"tr","session_id":"s2","max_frames":2,"frame_interval_seconds":1.0}'
        )
        assert ok.startswith("[VIDEO:INGESTED]")

    @pytest.mark.asyncio
    async def test_campaign_asset_and_checklist_tools(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        fake_db = MagicMock()
        fake_db.upsert_marketing_campaign = AsyncMock(
            return_value=types.SimpleNamespace(
                id=77,
                tenant_id="t1",
                name="Kamp",
                channel="instagram",
                objective="lead",
                status="draft",
                owner_user_id="u1",
                budget=99.0,
            )
        )
        fake_db.add_content_asset = AsyncMock(
            return_value=types.SimpleNamespace(
                id=12,
                campaign_id=77,
                tenant_id="t1",
                asset_type="copy",
                title="başlık",
                channel="instagram",
            )
        )
        fake_db.add_operation_checklist = AsyncMock(
            return_value=types.SimpleNamespace(
                id=34, campaign_id=77, tenant_id="t1", title="ops", status="pending", items_json="[]"
            )
        )
        monkeypatch.setattr(agent, "_ensure_db", AsyncMock(return_value=fake_db))

        campaign = await agent._tool_create_marketing_campaign(
            '{"tenant_id":"t1","name":"Kamp","channel":"instagram","objective":"lead","status":"draft","owner_user_id":"u1","budget":99.0,"metadata":{}}'
        )
        assert __import__("json").loads(campaign)["campaign"]["id"] == 77

        asset = await agent._tool_store_content_asset(
            '{"campaign_id":77,"tenant_id":"t1","asset_type":"copy","title":"başlık","content":"metin","channel":"instagram","metadata":{}}'
        )
        assert __import__("json").loads(asset)["asset"]["id"] == 12

        checklist = await agent._tool_create_operation_checklist(
            '{"tenant_id":"t1","title":"ops","items":[],"status":"pending","owner_user_id":"u1","campaign_id":77}'
        )
        assert __import__("json").loads(checklist)["checklist"]["id"] == 34
