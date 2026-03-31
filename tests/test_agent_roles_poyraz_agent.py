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
    def test_empty_prompt_returns_warning(self):
        async def _run():
            m = _get_poyraz()
            result = await m.PoyrazAgent().run_task("")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_web_search_routing(self):
        async def _run():
            m = _get_poyraz()
            result = await m.PoyrazAgent().run_task("web_search|SEO stratejileri")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_fetch_url_routing(self):
        async def _run():
            m = _get_poyraz()
            result = await m.PoyrazAgent().run_task("fetch_url|https://example.com")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_search_docs_routing(self):
        async def _run():
            m = _get_poyraz()
            result = await m.PoyrazAgent().run_task("search_docs|pazarlama stratejisi")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_social_routing_text(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            result = await agent.run_task("publish_social|twitter|||merhaba dünya")
            assert "SOCIAL" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_default_generates_content(self):
        async def _run():
            m = _get_poyraz()
            result = await m.PoyrazAgent().run_task("yaz kampanyası için içerik üret")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestPoyrazAgentTools:
    def test_web_search_tool(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            result = await agent.call_tool("web_search", "dijital pazarlama")
            assert "web sonucu" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_unknown_tool_returns_error(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            result = await agent.call_tool("unknown_xyz", "arg")
            assert "HATA" in result or "hata" in result.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_social_json_payload_success_branch(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_publish_social_pipe_payload_error_branch(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            agent.social.publish_content = AsyncMock(return_value=(False, "api down"))

            result = await agent._tool_publish_social("facebook|||metin|||dest|||media|||link")

            assert result.startswith("[SOCIAL:ERROR]")
            assert "platform=facebook" in result
            assert "api down" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

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
    def test_plan_service_operations_without_persist(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_plan_service_operations_with_persist_adds_checklist(self, monkeypatch):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestPoyrazAdditionalCoverage:
    def test_ensure_db_returns_existing_instance(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            existing_db = MagicMock()
            agent._db = existing_db
            result = await agent._ensure_db()
            assert result is existing_db
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ensure_db_initializes_once_with_lock(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()

            fake_db_instance = MagicMock()
            fake_db_instance.connect = AsyncMock()
            fake_db_instance.init_schema = AsyncMock()

            db_mod = types.ModuleType("core.db")
            db_mod.Database = MagicMock(return_value=fake_db_instance)
            sys.modules["core.db"] = db_mod

            first, second = await asyncio.gather(agent._ensure_db(), agent._ensure_db())
            assert first is second
            db_mod.Database.assert_called_once_with(agent.cfg)
            fake_db_instance.connect.assert_awaited_once()
            fake_db_instance.init_schema.assert_awaited_once()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_search_docs_awaits_async_result_object(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()

            async def _async_search(*_args, **_kwargs):
                return (False, "timeout")

            agent.docs.search = MagicMock(side_effect=_async_search)
            result = await agent._tool_search_docs("kampanya")
            assert result == "timeout"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_social_channel_specific_tools_success_and_error(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ensure_db_reuses_existing_lock_instance(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()

            existing_lock = asyncio.Lock()
            agent._db_lock = existing_lock

            fake_db_instance = MagicMock()
            fake_db_instance.connect = AsyncMock()
            fake_db_instance.init_schema = AsyncMock()

            db_mod = types.ModuleType("core.db")
            db_mod.Database = MagicMock(return_value=fake_db_instance)
            sys.modules["core.db"] = db_mod

            result = await agent._ensure_db()

            assert result is fake_db_instance
            assert agent._db_lock is existing_lock
            db_mod.Database.assert_called_once_with(agent.cfg)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ensure_db_returns_cached_instance_after_lock_enter(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        cached_db = MagicMock()

        class _LateCacheLock:
            async def __aenter__(self_inner):
                agent._db = cached_db
                return None

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        agent._db = None
        agent._db_lock = _LateCacheLock()

        result = asyncio.run(agent._ensure_db())
        assert result is cached_db

    def test_social_channel_specific_missing_branches(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()

        agent.social.publish_instagram_post = AsyncMock(return_value=(False, "ig-down"))
        result = asyncio.run(agent._tool_publish_instagram_post('{"caption":"hello","image_url":"https://img"}'))
        assert result.startswith("[INSTAGRAM:ERROR]")

        agent.social.publish_facebook_post = AsyncMock(return_value=(True, "fb-ok"))
        result = asyncio.run(agent._tool_publish_facebook_post('{"message":"msg","link_url":"https://lnk"}'))
        assert result.startswith("[FACEBOOK:PUBLISHED]")

        agent.social.send_whatsapp_message = AsyncMock(return_value=(False, "wa-down"))
        result = asyncio.run(agent._tool_send_whatsapp_message('{"to":"+90555","text":"selam","preview_url":true}'))
        assert result.startswith("[WHATSAPP:ERROR]")

    def test_build_landing_page_with_store_asset(self, monkeypatch):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_build_landing_page_plain_text_does_not_store_asset(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="plain-landing"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        result = asyncio.run(agent._tool_build_landing_page("Kısa landing page briefi"))
        assert result == "plain-landing"
        agent._persist_content_asset.assert_not_awaited()

    def test_build_landing_page_store_asset_enabled_without_campaign_id_skips_persist(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="landing-no-campaign"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        payload = {
            "brand_name": "Sidar",
            "offer": "İlk teklif",
            "audience": "KOBİ",
            "call_to_action": "Demo al",
            "tone": "professional",
            "sections": ["hero", "cta"],
            "store_asset": True,
            "campaign_id": None,
        }
        result = asyncio.run(agent._tool_build_landing_page(__import__("json").dumps(payload, ensure_ascii=False)))
        assert result == "landing-no-campaign"
        agent._persist_content_asset.assert_not_awaited()

    def test_generate_campaign_copy_with_store_asset(self, monkeypatch):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_generate_campaign_copy_plain_text_branch(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="copy-plain"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        result = asyncio.run(agent._tool_generate_campaign_copy("Serbest metin briefi"))
        assert result == "copy-plain"
        prompt = agent._generate_marketing_output.await_args.args[0]
        assert "Serbest metin briefi" in prompt
        agent._persist_content_asset.assert_not_awaited()

    def test_plan_service_operations_skips_empty_menu_option_groups(self):
        async def _run():
            m = _get_poyraz()
            agent = m.PoyrazAgent()
            payload = {
                "campaign_name": "Sonbahar Kampanyası",
                "service_name": "Coffee Break",
                "audience": "Çalışanlar",
                "menu_plan": {"ana_yemek": [], "tatlı": [], "içecek": ["Filtre Kahve"]},
                "vendor_assignments": {},
                "timeline": [],
                "notes": "",
                "persist_checklist": False,
            }
            result = await agent._tool_plan_service_operations(__import__("json").dumps(payload, ensure_ascii=False))
            parsed = __import__("json").loads(result)
            menu_items = [item for item in parsed["service_plan"]["items"] if item["type"] == "menu_plan"]
            assert len(menu_items) == 1
            assert menu_items[0]["group"] == "içecek"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_video_ingest_success_and_error_paths(self):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_campaign_asset_and_checklist_tools(self, monkeypatch):
        async def _run():
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
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestPoyrazAgentScenarioParametrized:
    @pytest.mark.parametrize(
        "tool_method, payload, expected_mode, should_persist",
        [
            (
                "_tool_build_landing_page",
                {
                    "brand_name": "Sidar",
                    "offer": "AI destekli CRM",
                    "audience": "KOBİ",
                    "call_to_action": "Demo iste",
                    "tone": "professional",
                    "sections": ["hero", "social proof"],
                    "store_asset": True,
                    "campaign_id": 11,
                    "tenant_id": "tenant-a",
                    "asset_title": "LP A",
                    "channel": "web",
                },
                "landing_page",
                True,
            ),
            (
                "_tool_generate_campaign_copy",
                {
                    "campaign_name": "Bahar Satışı",
                    "objective": "lead",
                    "audience": "Genç ebeveyn",
                    "channels": ["instagram", "facebook"],
                    "offer": "%20 indirim",
                    "tone": "enerjik",
                    "call_to_action": "Hemen katıl",
                    "store_asset": False,
                    "campaign_id": 12,
                    "tenant_id": "tenant-b",
                    "asset_title": "Copy B",
                },
                "campaign_copy_tool",
                False,
            ),
        ],
    )
    def test_content_production_scenarios_with_json_payload(
        self,
        monkeypatch,
        tool_method,
        payload,
        expected_mode,
        should_persist,
    ):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="generated-output"))
        monkeypatch.setattr(agent, "_persist_content_asset", AsyncMock(return_value='{"success":true}'))

        raw = __import__("json").dumps(payload, ensure_ascii=False)
        result = asyncio.run(getattr(agent, tool_method)(raw))

        assert result == "generated-output"
        agent._generate_marketing_output.assert_awaited_once()
        called_mode = agent._generate_marketing_output.await_args.args[1]
        assert called_mode == expected_mode
        if should_persist:
            agent._persist_content_asset.assert_awaited_once()
        else:
            agent._persist_content_asset.assert_not_awaited()

    @pytest.mark.parametrize(
        "tool_method, raw_arg, expected_source, expected_max_frames",
        [
            ("_tool_ingest_video_insights", "https://video|||Özetle|||tr|||mkt-session|||4", "https://video", 4),
            (
                "_tool_ingest_video_insights",
                '{"source_url":"https://video-json","prompt":"Analiz et","language":"tr","session_id":"sess-1","max_frames":2,"frame_interval_seconds":1.5}',
                "https://video-json",
                2,
            ),
        ],
    )
    def test_video_insight_scenarios_with_parameterized_inputs(
        self,
        tool_method,
        raw_arg,
        expected_source,
        expected_max_frames,
    ):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        pipe_mod = types.ModuleType("core.multimodal")
        pipeline = MagicMock()
        pipeline.analyze_media_source = AsyncMock(
            return_value={"success": True, "scene_summary": "ok", "document_ingest": {"doc_id": "doc-42"}}
        )
        pipe_mod.MultimodalPipeline = MagicMock(return_value=pipeline)
        sys.modules["core.multimodal"] = pipe_mod

        result = asyncio.run(getattr(agent, tool_method)(raw_arg))

        assert result.startswith("[VIDEO:INGESTED]")
        kwargs = pipeline.analyze_media_source.await_args.kwargs
        assert kwargs["media_source"] == expected_source
        assert kwargs["max_frames"] == expected_max_frames

    @pytest.mark.parametrize(
        "prompt, expected_type, expected_target",
        [
            ("build_landing_page|brief", "tool", "build_landing_page"),
            ("landing_page|brief", "tool", "build_landing_page"),
            ("generate_campaign_copy|brief", "tool", "generate_campaign_copy"),
            ("publish_instagram_post|{\"caption\":\"x\",\"image_url\":\"y\"}", "tool", "publish_instagram_post"),
            ("publish_facebook_post|{\"message\":\"x\",\"link_url\":\"y\"}", "tool", "publish_facebook_post"),
            ("send_whatsapp_message|{\"to\":\"+90\",\"text\":\"hi\",\"preview_url\":true}", "tool", "send_whatsapp_message"),
            ("ingest_video_insights|https://v|||özet|||tr|||s1|||2", "tool", "ingest_video_insights"),
            ("analyze_video|https://v|||özet|||tr|||s1|||2", "tool", "ingest_video_insights"),
            ("create_marketing_campaign|{\"tenant_id\":\"t\",\"name\":\"n\",\"channel\":\"c\",\"objective\":\"o\",\"status\":\"draft\",\"owner_user_id\":\"u\",\"budget\":1,\"metadata\":{}}", "tool", "create_marketing_campaign"),
            ("store_content_asset|{\"campaign_id\":1,\"tenant_id\":\"t\",\"asset_type\":\"copy\",\"title\":\"ttl\",\"content\":\"txt\",\"channel\":\"ig\",\"metadata\":{}}", "tool", "store_content_asset"),
            ("create_operation_checklist|{\"tenant_id\":\"t\",\"title\":\"ops\",\"items\":[],\"status\":\"pending\",\"owner_user_id\":\"u\",\"campaign_id\":1}", "tool", "create_operation_checklist"),
            ("plan_service_operations|{\"campaign_name\":\"K\",\"service_name\":\"S\",\"audience\":\"A\",\"menu_plan\":{},\"vendor_assignments\":{},\"timeline\":[],\"notes\":\"\",\"persist_checklist\":false}", "tool", "plan_service_operations"),
            ("seo_audit|teknik denetim", "mode", "seo_audit"),
            ("campaign_copy|kanal metni", "mode", "campaign_copy"),
            ("audience_ops|segmentasyon", "mode", "audience_ops"),
            ("research_to_marketing|araştırmayı plana çevir", "mode", "research_to_marketing"),
            ("Bu bir landing page metni olsun", "tool", "build_landing_page"),
            ("Yeni SEO ve pazarlama funnel operasyonu hazırla", "mode", "marketing_strategy"),
            ("Tamamen nötr bir metin", "mode", "marketing_general"),
        ],
    )
    def test_run_task_routes_for_marketing_and_operations(self, monkeypatch, prompt, expected_type, expected_target):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "call_tool", AsyncMock(return_value="TOOL_OK"))
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(return_value="MODE_OK"))

        result = asyncio.run(agent.run_task(prompt))

        if expected_type == "tool":
            assert result == "TOOL_OK"
            called_tool = agent.call_tool.await_args.args[0]
            assert called_tool == expected_target
        else:
            assert result == "MODE_OK"
            called_mode = agent._generate_marketing_output.await_args.args[1]
            assert called_mode == expected_target


class TestPoyrazAgentFailureScenarios:
    def test_web_search_timeout_is_propagated(self):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        agent.web.search = AsyncMock(side_effect=TimeoutError("web timeout"))

        with pytest.raises(TimeoutError):
            asyncio.run(agent._tool_web_search("sidar growth strategy"))

    def test_generate_marketing_output_error_is_propagated(self, monkeypatch):
        m = _get_poyraz()
        agent = m.PoyrazAgent()
        monkeypatch.setattr(agent, "_generate_marketing_output", AsyncMock(side_effect=RuntimeError("llm failed")))

        with pytest.raises(RuntimeError):
            asyncio.run(agent.run_task("seo_audit|teknik denetim"))
