import asyncio
import importlib.util
import inspect
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _StubBaseAgent:
    def __init__(self, cfg=None, *, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}
        self.llm = object()
        self.llm_calls = []

    def register_tool(self, name, func):
        self.tools[name] = func

    async def call_tool(self, name, arg):
        if name not in self.tools:
            return f"[HATA] '{name}' aracı bu ajan için tanımlı değil."
        return await self.tools[name](arg)

    async def call_llm(self, messages, **kwargs):
        self.llm_calls.append((messages, kwargs))
        content = messages[0]["content"] if messages else ""
        extracted_mode = "default"
        for line in content.splitlines():
            if line.lower().startswith("görev modu:"):
                extracted_mode = line.split(":", 1)[1].strip() or "default"
                break
        system_prompt = kwargs.get("system_prompt", "default")
        return f"LLM_RESPONSE::{extracted_mode}::{system_prompt}"


class _StubAgentCatalog:
    @classmethod
    def register(cls, **_kwargs):
        def _decorator(agent_cls):
            return agent_cls

        return _decorator


class DummyWebSearchManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.search_calls = []
        self.fetch_calls = []

    async def search(self, arg: str):
        self.search_calls.append(arg)
        return True, f"web:{arg}"

    async def fetch_url(self, arg: str):
        self.fetch_calls.append(arg)
        return True, f"fetch:{arg}"


class DummySocialMediaManager:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    async def publish_content(self, **kwargs):
        self.calls.append(("publish_content", kwargs))
        if kwargs.get("platform") == "bad":
            return False, "nope"
        return True, "ok"

    async def publish_instagram_post(self, **kwargs):
        self.calls.append(("publish_instagram_post", kwargs))
        if kwargs.get("caption") == "fail":
            return False, "ig_err"
        return True, "ig_ok"

    async def publish_facebook_post(self, **kwargs):
        self.calls.append(("publish_facebook_post", kwargs))
        if kwargs.get("message") == "fail":
            return False, "fb_err"
        return True, "fb_ok"

    async def send_whatsapp_message(self, **kwargs):
        self.calls.append(("send_whatsapp_message", kwargs))
        if kwargs.get("to") == "0":
            return False, "wa_err"
        return True, "wa_ok"


class SyncDocStore:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def search(self, query, _filters, mode, session):
        self.calls.append((query, mode, session))
        return True, f"docs:{query}:{mode}:{session}"


class AsyncDocStore:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def search(self, query, _filters, mode, session):
        self.calls.append((query, mode, session))

        async def _inner():
            return True, f"adocs:{query}:{mode}:{session}"

        return _inner()


class DummyDatabase:
    instances = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.connect_count = 0
        self.init_schema_count = 0
        self.add_content_asset_calls = []
        self.upsert_campaign_calls = []
        self.add_checklist_calls = []
        DummyDatabase.instances.append(self)

    async def connect(self):
        self.connect_count += 1

    async def init_schema(self):
        self.init_schema_count += 1

    async def add_content_asset(self, **kwargs):
        self.add_content_asset_calls.append(kwargs)
        return SimpleNamespace(id=7, **kwargs)

    async def upsert_marketing_campaign(self, **kwargs):
        self.upsert_campaign_calls.append(kwargs)
        return SimpleNamespace(id=11, **kwargs)

    async def add_operation_checklist(self, **kwargs):
        self.add_checklist_calls.append(kwargs)
        return SimpleNamespace(id=13, items_json=json.dumps(kwargs.get("items", [])), **kwargs)

    async def get_active_prompt(self, role_name):
        return SimpleNamespace(role_name=role_name, prompt_text="")


class DummyMultimodalPipeline:
    last_kwargs = None

    def __init__(self, llm, cfg):
        self.llm = llm
        self.cfg = cfg

    async def analyze_media_source(self, **kwargs):
        DummyMultimodalPipeline.last_kwargs = kwargs
        source = kwargs["media_source"]
        if source == "bad://video":
            return {"success": False, "reason": "broken"}
        return {
            "success": True,
            "document_ingest": {"doc_id": "doc-1"},
            "scene_summary": "scene-summary",
        }


def test_stub_base_agent_tool_error_and_llm_mode_parsing_paths():
    agent = _StubBaseAgent()

    missing_tool = asyncio.run(agent.call_tool("bilinmeyen", "arg"))
    assert missing_tool.startswith("[HATA]")

    no_mode = asyncio.run(
        agent.call_llm([{"content": "ilk satır\nikinci satır"}], system_prompt="SYS")
    )
    assert no_mode == "LLM_RESPONSE::default::SYS"

    multi_line_mode = asyncio.run(
        agent.call_llm([{"content": "başlık\nGörev Modu: kampanya"}], system_prompt="SYS2")
    )
    assert multi_line_mode == "LLM_RESPONSE::kampanya::SYS2"


def test_dummy_database_get_active_prompt_defaults_to_empty_prompt():
    db = DummyDatabase(cfg=SimpleNamespace())
    prompt = asyncio.run(db.get_active_prompt("poyraz"))
    assert prompt.role_name == "poyraz"
    assert prompt.prompt_text == ""


@pytest.fixture
def poyraz_module(monkeypatch: pytest.MonkeyPatch):
    # WARNING: This fixture mutates `sys.modules` to inject lightweight doubles
    # for import-time dependencies. This is intentionally local and cleaned up by
    # `monkeypatch`, but remains risky for parallel test execution patterns that
    # share interpreter state (thread-based runners). Prefer dependency injection
    # in production code for long-term xdist/thread safety.
    config_mod = types.ModuleType("config")
    config_mod.Config = object
    core_rag_mod = types.ModuleType("core.rag")
    core_rag_mod.DocumentStore = SyncDocStore
    web_search_mod = types.ModuleType("managers.web_search")
    web_search_mod.WebSearchManager = DummyWebSearchManager
    social_mod = types.ModuleType("managers.social_media_manager")
    social_mod.SocialMediaManager = DummySocialMediaManager
    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = _StubBaseAgent
    registry_mod = types.ModuleType("agent.registry")
    registry_mod.AgentCatalog = _StubAgentCatalog

    monkeypatch.setitem(sys.modules, "config", config_mod)  # WARNING: global module table mutation
    monkeypatch.setitem(
        sys.modules, "core.rag", core_rag_mod
    )  # WARNING: global module table mutation
    monkeypatch.setitem(
        sys.modules, "managers.web_search", web_search_mod
    )  # WARNING: global module table mutation
    monkeypatch.setitem(
        sys.modules, "managers.social_media_manager", social_mod
    )  # WARNING: global module table mutation
    monkeypatch.setitem(
        sys.modules, "agent.base_agent", base_agent_mod
    )  # WARNING: global module table mutation
    monkeypatch.setitem(
        sys.modules, "agent.registry", registry_mod
    )  # WARNING: global module table mutation

    file_path = Path(__file__).resolve().parents[4] / "agent" / "roles" / "poyraz_agent.py"
    spec = importlib.util.spec_from_file_location("poyraz_under_test", file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    class _Payload(SimpleNamespace):
        def __getattr__(self, _name):
            return ""

    def parse_arg(_tool_name, raw):
        payload = json.loads(raw)
        return _Payload(**payload)

    monkeypatch.setattr(module, "parse_tool_argument", parse_arg)
    return module


@pytest.fixture
def fake_cfg(tmp_path):
    return SimpleNamespace(
        RAG_DIR=str(tmp_path / "rag"),
        RAG_TOP_K=5,
        RAG_CHUNK_SIZE=100,
        RAG_CHUNK_OVERLAP=10,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
        META_GRAPH_API_TOKEN="t",
        INSTAGRAM_BUSINESS_ACCOUNT_ID="ig",
        FACEBOOK_PAGE_ID="fb",
        WHATSAPP_PHONE_NUMBER_ID="wa",
        META_GRAPH_API_VERSION="v20.0",
    )


def _agent(poyraz_module, fake_cfg, docstore=SyncDocStore):
    poyraz_module.DocumentStore = docstore
    return poyraz_module.PoyrazAgent(fake_cfg)


def test_init_registers_tools(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)
    assert agent.role_name == "poyraz"
    assert {
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
    } == set(agent.tools)
    assert all(inspect.iscoroutinefunction(tool) for tool in agent.tools.values())


def test_search_and_fetch_and_docs_sync_async(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg, docstore=SyncDocStore)
    assert asyncio.run(agent._tool_web_search("q")) == "web:q"
    assert asyncio.run(agent._tool_fetch_url("u")) == "fetch:u"
    assert asyncio.run(agent._tool_search_docs("k")) == "docs:k:auto:marketing"

    agent2 = _agent(poyraz_module, fake_cfg, docstore=AsyncDocStore)
    assert asyncio.run(agent2._tool_search_docs("k2")) == "adocs:k2:auto:marketing"


def test_publish_tools_variants(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)

    ok = asyncio.run(agent._tool_publish_social("instagram|||text|||dest|||m|||l"))
    err = asyncio.run(
        agent._tool_publish_social(
            json.dumps(
                {
                    "platform": "bad",
                    "text": "x",
                    "destination": "d",
                    "media_url": "",
                    "link_url": "",
                }
            )
        )
    )
    assert ok.startswith("[SOCIAL:PUBLISHED]")
    assert err.startswith("[SOCIAL:ERROR]")

    ig_ok = asyncio.run(
        agent._tool_publish_instagram_post(json.dumps({"caption": "cap", "image_url": "img"}))
    )
    ig_err = asyncio.run(
        agent._tool_publish_instagram_post(json.dumps({"caption": "fail", "image_url": "img"}))
    )
    fb_ok = asyncio.run(
        agent._tool_publish_facebook_post(json.dumps({"message": "msg", "link_url": "lnk"}))
    )
    fb_err = asyncio.run(
        agent._tool_publish_facebook_post(json.dumps({"message": "fail", "link_url": "lnk"}))
    )
    wa_ok = asyncio.run(
        agent._tool_send_whatsapp_message(json.dumps({"to": "1", "text": "m", "preview_url": 1}))
    )
    wa_err = asyncio.run(
        agent._tool_send_whatsapp_message(json.dumps({"to": "0", "text": "m", "preview_url": 0}))
    )

    assert "[INSTAGRAM:PUBLISHED]" in ig_ok and "[INSTAGRAM:ERROR]" in ig_err
    assert "[FACEBOOK:PUBLISHED]" in fb_ok and "[FACEBOOK:ERROR]" in fb_err
    assert "[WHATSAPP:SENT]" in wa_ok and "[WHATSAPP:ERROR]" in wa_err


def test_publish_social_invalid_json(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)

    result = asyncio.run(agent._tool_publish_social("{invalid:json}"))
    assert "[SOCIAL:ERROR]" in result


def test_publish_social_text_format_with_missing_segments_uses_unknown(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)
    result = asyncio.run(agent._tool_publish_social("instagram|||only-text"))
    assert "platform=unknown" in result


def test_social_media_invalid_text_format(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)
    result = asyncio.run(agent._tool_publish_social("only-platform|||only-text"))
    assert result.startswith("[SOCIAL:")
    assert "platform=unknown" in result


def test_publish_social_returns_generic_exception_reason(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)

    async def _raise_generic(**_kwargs):
        raise RuntimeError("service down")

    agent.social.publish_content = _raise_generic

    result = asyncio.run(agent._tool_publish_social("instagram|||text|||dest|||m|||l"))
    assert result == "[SOCIAL:ERROR] platform=instagram reason=service down"


def test_ensure_db_returns_existing_instance_inside_lock(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)
    sentinel_db = object()

    class PreloadedLock:
        async def __aenter__(self):
            agent._db = sentinel_db
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    agent._db_lock = PreloadedLock()

    assert asyncio.run(agent._ensure_db()) is sentinel_db


def test_ensure_db_timeout_guard(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)

    class BlockingLock:
        async def __aenter__(self):
            await asyncio.Future()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    agent._db_lock = BlockingLock()

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(asyncio.wait_for(agent._ensure_db(), timeout=0.01))
    assert asyncio.run(agent._db_lock.__aexit__(None, None, None)) is False


def test_ensure_db_and_persist_and_store_asset(poyraz_module, fake_cfg, monkeypatch):
    db_mod = types.ModuleType("core.db")
    DummyDatabase.instances.clear()
    db_mod.Database = DummyDatabase
    monkeypatch.setitem(sys.modules, "core.db", db_mod)

    agent = _agent(poyraz_module, fake_cfg)

    db1 = asyncio.run(agent._ensure_db())
    db2 = asyncio.run(agent._ensure_db())
    assert db1 is db2
    assert db1.connect_count == 1
    assert db1.init_schema_count == 1

    persisted = asyncio.run(
        agent._persist_content_asset(
            campaign_id=1,
            tenant_id="tenant",
            asset_type="landing",
            title="t",
            content="c",
            channel="web",
            metadata={"a": 1},
        )
    )
    parsed = json.loads(persisted)
    assert parsed["success"] is True
    assert parsed["asset"]["campaign_id"] == 1

    stored = asyncio.run(
        agent._tool_store_content_asset(
            json.dumps(
                {
                    "campaign_id": 2,
                    "tenant_id": "",
                    "asset_type": "copy",
                    "title": "title",
                    "content": "body",
                    "channel": "ig",
                    "metadata": {"b": 2},
                }
            )
        )
    )
    assert json.loads(stored)["asset"]["tenant_id"] == "default"


def test_landing_and_campaign_copy_tools_with_and_without_persist(
    poyraz_module, fake_cfg, monkeypatch
):
    db_mod = types.ModuleType("core.db")
    DummyDatabase.instances.clear()
    db_mod.Database = DummyDatabase
    monkeypatch.setitem(sys.modules, "core.db", db_mod)

    agent = _agent(poyraz_module, fake_cfg)

    plain = asyncio.run(agent._tool_build_landing_page("brief"))
    with_payload = asyncio.run(
        agent._tool_build_landing_page(
            json.dumps(
                {
                    "brand_name": "B",
                    "offer": "O",
                    "audience": "A",
                    "call_to_action": "CTA",
                    "tone": "T",
                    "sections": ["hero"],
                    "store_asset": True,
                    "campaign_id": 5,
                    "tenant_id": "",
                    "asset_title": "",
                    "channel": "",
                }
            )
        )
    )
    copy_plain = asyncio.run(agent._tool_generate_campaign_copy("brief2"))
    copy_payload = asyncio.run(
        agent._tool_generate_campaign_copy(
            json.dumps(
                {
                    "campaign_name": "N",
                    "objective": "Obj",
                    "audience": "Au",
                    "channels": ["instagram"],
                    "offer": "Off",
                    "tone": "ton",
                    "call_to_action": "cta",
                    "store_asset": True,
                    "campaign_id": 8,
                    "tenant_id": "",
                    "asset_title": "",
                }
            )
        )
    )

    assert plain.startswith("LLM_RESPONSE::") and with_payload.startswith("LLM_RESPONSE::")
    assert copy_plain.startswith("LLM_RESPONSE::") and copy_payload.startswith("LLM_RESPONSE::")
    assert DummyDatabase.instances[-1].add_content_asset_calls


def test_ingest_video_insights(poyraz_module, fake_cfg, monkeypatch):
    # Düzeltilen Kısım: Dinamik yüklenen modül üzerindeki referansı doğrudan patch et.
    monkeypatch.setattr(poyraz_module, "MultimodalPipeline", DummyMultimodalPipeline)

    agent = _agent(poyraz_module, fake_cfg)
    DummyMultimodalPipeline.last_kwargs = None

    ok = asyncio.run(
        agent._tool_ingest_video_insights(
            json.dumps(
                {
                    "source_url": "https://video",
                    "prompt": "analyze",
                    "language": "tr",
                    "session_id": "s",
                    "max_frames": 3,
                    "frame_interval_seconds": 2.5,
                }
            )
        )
    )
    err = asyncio.run(agent._tool_ingest_video_insights("bad://video|||prompt|||tr|||sess|||3"))

    assert DummyMultimodalPipeline.last_kwargs is not None
    assert DummyMultimodalPipeline.last_kwargs["ingest_document_store"] is agent.docs
    assert DummyMultimodalPipeline.last_kwargs["ingest_session_id"] == "sess"
    assert DummyMultimodalPipeline.last_kwargs["ingest_tags"] == [
        "video",
        "multimodal",
        "marketing",
        "poyraz",
    ]
    assert ok.startswith("[VIDEO:INGESTED]")
    assert err.startswith("[VIDEO:ERROR]")


def test_ingest_video_insights_clamps_negative_numeric_limits(poyraz_module, fake_cfg, monkeypatch):
    # Düzeltilen Kısım
    monkeypatch.setattr(poyraz_module, "MultimodalPipeline", DummyMultimodalPipeline)

    agent = _agent(poyraz_module, fake_cfg)
    DummyMultimodalPipeline.last_kwargs = None

    result = asyncio.run(
        agent._tool_ingest_video_insights(
            json.dumps(
                {
                    "source_url": "https://video-negative",
                    "prompt": "analyze",
                    "language": "tr",
                    "session_id": "neg-session",
                    "max_frames": -4,
                    "frame_interval_seconds": -1.5,
                }
            )
        )
    )

    assert result.startswith("[VIDEO:INGESTED]")
    assert DummyMultimodalPipeline.last_kwargs is not None
    assert DummyMultimodalPipeline.last_kwargs["max_frames"] == 1
    assert DummyMultimodalPipeline.last_kwargs["frame_interval_seconds"] == 0.1


def test_ingest_video_insights_loads_pipeline_via_importlib_fallback(
    poyraz_module, fake_cfg, monkeypatch
):
    class FallbackPipeline(DummyMultimodalPipeline):
        pass

    fake_mm_mod = types.ModuleType("core.multimodal")
    fake_mm_mod.MultimodalPipeline = FallbackPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", fake_mm_mod)
    monkeypatch.setattr(poyraz_module, "MultimodalPipeline", None)

    agent = _agent(poyraz_module, fake_cfg)
    result = asyncio.run(
        agent._tool_ingest_video_insights("https://video|||prompt|||tr|||sess|||3")
    )

    assert result.startswith("[VIDEO:INGESTED]")
    assert DummyMultimodalPipeline.last_kwargs is not None
    assert DummyMultimodalPipeline.last_kwargs["media_source"] == "https://video"


def test_ingest_video_insights_returns_error_when_pipeline_unavailable(
    poyraz_module, fake_cfg, monkeypatch
):
    monkeypatch.setattr(poyraz_module, "MultimodalPipeline", None)
    monkeypatch.setattr(
        poyraz_module.importlib,
        "import_module",
        lambda _: (_ for _ in ()).throw(ImportError("missing")),
    )

    agent = _agent(poyraz_module, fake_cfg)
    result = asyncio.run(agent._tool_ingest_video_insights("https://video|||prompt"))

    assert result == "[VIDEO:ERROR] source=unknown reason=multimodal_pipeline_unavailable"


def test_campaign_and_checklist_and_service_plan(poyraz_module, fake_cfg, monkeypatch):
    db_mod = types.ModuleType("core.db")
    DummyDatabase.instances.clear()
    db_mod.Database = DummyDatabase
    monkeypatch.setitem(sys.modules, "core.db", db_mod)

    agent = _agent(poyraz_module, fake_cfg)

    campaign = asyncio.run(
        agent._tool_create_marketing_campaign(
            json.dumps(
                {
                    "tenant_id": "",
                    "name": "Camp",
                    "channel": "ig",
                    "objective": "sales",
                    "status": "",
                    "owner_user_id": "u1",
                    "budget": 10,
                    "metadata": {"x": 1},
                    "campaign_id": None,
                }
            )
        )
    )
    checklist = asyncio.run(
        agent._tool_create_operation_checklist(
            json.dumps(
                {
                    "tenant_id": "",
                    "title": "Ops",
                    "items": ["a"],
                    "status": "",
                    "owner_user_id": "u1",
                    "campaign_id": 1,
                }
            )
        )
    )
    plan = asyncio.run(
        agent._tool_plan_service_operations(
            json.dumps(
                {
                    "campaign_name": "C",
                    "service_name": "S",
                    "audience": "A",
                    "menu_plan": {"drinks": ["tea", " "]},
                    "vendor_assignments": {"photo": "alice", "music": " "},
                    "timeline": ["t1", ""],
                    "notes": " note ",
                    "persist_checklist": True,
                    "tenant_id": "",
                    "checklist_title": "",
                    "owner_user_id": "u1",
                    "campaign_id": 22,
                }
            )
        )
    )
    plan_no_persist = asyncio.run(
        agent._tool_plan_service_operations(
            json.dumps(
                {
                    "campaign_name": "C",
                    "service_name": "S",
                    "audience": "A",
                    "menu_plan": {"empty": []},
                    "vendor_assignments": {},
                    "timeline": [],
                    "notes": "",
                    "persist_checklist": False,
                    "tenant_id": "",
                    "checklist_title": "",
                    "owner_user_id": "u1",
                    "campaign_id": None,
                }
            )
        )
    )

    assert json.loads(campaign)["campaign"]["tenant_id"] == "default"
    assert json.loads(checklist)["checklist"]["status"] == "pending"
    parsed_plan = json.loads(plan)["service_plan"]
    assert any(i["type"] == "menu_plan" for i in parsed_plan["items"])
    assert "checklist" in parsed_plan
    assert "checklist" not in json.loads(plan_no_persist)["service_plan"]


def test_generate_marketing_output_and_run_task_routes(poyraz_module, fake_cfg, monkeypatch):
    agent = _agent(poyraz_module, fake_cfg)

    output = asyncio.run(agent._generate_marketing_output("Task", "modex"))
    assert output.startswith("LLM_RESPONSE::")

    empty = asyncio.run(agent.run_task("   "))
    assert empty.startswith("[UYARI]")

    routed = {
        "web_search|q": "web:q",
        "fetch_url|u": "fetch:u",
        "search_docs|k": "docs:k:auto:marketing",
        "build_landing_page|brief": "LLM_RESPONSE::",
        "landing_page|brief": "LLM_RESPONSE::",
        "generate_campaign_copy|brief": "LLM_RESPONSE::",
        "publish_instagram_post|"
        + json.dumps({"caption": "c", "image_url": "i"}): "[INSTAGRAM:PUBLISHED]",
        "publish_facebook_post|"
        + json.dumps({"message": "m", "link_url": "l"}): "[FACEBOOK:PUBLISHED]",
        "send_whatsapp_message|"
        + json.dumps({"to": "1", "text": "t", "preview_url": 0}): "[WHATSAPP:SENT]",
        "create_marketing_campaign|"
        + json.dumps(
            {
                "tenant_id": "",
                "name": "n",
                "channel": "c",
                "objective": "o",
                "status": "",
                "owner_user_id": "u",
                "budget": 0,
                "metadata": {},
                "campaign_id": None,
            }
        ): '{"success": true',
        "store_content_asset|"
        + json.dumps(
            {
                "campaign_id": 1,
                "tenant_id": "",
                "asset_type": "a",
                "title": "t",
                "content": "c",
                "channel": "ch",
                "metadata": {},
            }
        ): '{"success": true',
        "create_operation_checklist|"
        + json.dumps(
            {
                "tenant_id": "",
                "title": "t",
                "items": [],
                "status": "",
                "owner_user_id": "u",
                "campaign_id": None,
            }
        ): '{"success": true',
        "plan_service_operations|"
        + json.dumps(
            {
                "campaign_name": "c",
                "service_name": "s",
                "audience": "a",
                "menu_plan": {},
                "vendor_assignments": {},
                "timeline": [],
                "notes": "",
                "persist_checklist": False,
                "tenant_id": "",
                "checklist_title": "",
                "owner_user_id": "u",
                "campaign_id": None,
            }
        ): '{"success": true',
        "seo_audit|x": "LLM_RESPONSE::",
        "campaign_copy|x": "LLM_RESPONSE::",
        "audience_ops|x": "LLM_RESPONSE::",
        "research_to_marketing|x": "LLM_RESPONSE::",
        "publish_social|instagram|||x|||d|||m|||l": "[SOCIAL:PUBLISHED]",
        "we need landing page": "LLM_RESPONSE::",
        "seo kampanya hedef kitle": "LLM_RESPONSE::",
        "other": "LLM_RESPONSE::",
    }

    # set up db/mm imports for route paths that need them
    db_mod = types.ModuleType("core.db")
    db_mod.Database = DummyDatabase
    monkeypatch.setitem(sys.modules, "core.db", db_mod)
    # Düzeltilen Kısım: MultimodalPipeline için setattr kullanıyoruz
    monkeypatch.setattr(poyraz_module, "MultimodalPipeline", DummyMultimodalPipeline)

    # include ingest route aliases
    ingest1 = asyncio.run(agent.run_task("ingest_video_insights|https://video|||p|||tr|||s|||2"))
    ingest2 = asyncio.run(agent.run_task("analyze_video|bad://video|||p|||tr|||s|||2"))
    assert ingest1.startswith("[VIDEO:INGESTED]")
    assert ingest2.startswith("[VIDEO:ERROR]")

    for prompt, expected in routed.items():
        got = asyncio.run(agent.run_task(prompt))
        assert expected in got


def test_poyraz_output_format(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)
    result = asyncio.run(agent._generate_marketing_output("test", "seo"))
    assert "seo" in result


@pytest.mark.asyncio
async def test_poyraz_social_and_video_flows_use_shared_fakes(
    fake_social_api,
    fake_video_stream,
    monkeypatch,
    agent_factory,
) -> None:
    from agent.roles.poyraz_agent import PoyrazAgent

    agent = agent_factory(PoyrazAgent)
    agent.social = fake_social_api
    agent.docs = SimpleNamespace()
    agent.llm = object()
    agent.cfg = SimpleNamespace()

    agent.social.publish_content = AsyncMock(return_value=(True, {"id": "post-1"}))
    social_result = await agent._tool_publish_social("instagram|||Merhaba dünya|||sidar")
    assert "[SOCIAL:PUBLISHED]" in social_result

    class _FakePipeline:
        def __init__(self, *_args, **_kwargs):
            self.stream = fake_video_stream

        async def analyze_media_source(self, **_kwargs):
            frames = await self.stream.read_frames()
            return {
                "success": True,
                "scene_summary": f"frames={len(frames)}",
                "document_ingest": {"doc_id": "doc-123"},
            }

    monkeypatch.setattr("agent.roles.poyraz_agent.MultimodalPipeline", _FakePipeline)
    ingested = await agent._tool_ingest_video_insights(
        "https://video.example/test.mp4|||ürün analizi"
    )
    assert "[VIDEO:INGESTED]" in ingested
    assert "doc-123" in ingested


@pytest.mark.asyncio
async def test_poyraz_agent_error_flows(
    agent_factory,
    fake_social_api,
    fake_video_stream_error,
    monkeypatch,
) -> None:
    from agent.roles.poyraz_agent import PoyrazAgent

    agent = agent_factory(PoyrazAgent)
    agent.social = fake_social_api
    agent.docs = SimpleNamespace()
    agent.llm = object()
    agent.cfg = SimpleNamespace()

    agent.social.set_rate_limit_error()
    agent.social.publish_content = AsyncMock(side_effect=RuntimeError("API Rate Limit"))

    social_result = await agent._tool_publish_social("instagram|||hata testi|||sidar")
    assert social_result.startswith("[SOCIAL:ERROR]")
    assert "rate_limit" in social_result
    assert "Lütfen bekleyip tekrar deneyin" in social_result

    class _FakeErrorPipeline:
        def __init__(self, *_args, **_kwargs):
            self.stream = fake_video_stream_error

        async def analyze_media_source(self, **_kwargs):
            await self.stream.read_frames()

    monkeypatch.setattr("agent.roles.poyraz_agent.MultimodalPipeline", _FakeErrorPipeline)

    with pytest.raises(RuntimeError, match="corrupted video stream"):
        await agent._tool_ingest_video_insights("https://video.example/broken.mp4|||analiz")
