import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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
        return f"LLM::{messages[0]['content'][:20]}"


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


class DummyMultimodalPipeline:
    def __init__(self, llm, cfg):
        self.llm = llm
        self.cfg = cfg

    async def analyze_media_source(self, **kwargs):
        source = kwargs["media_source"]
        if source == "bad://video":
            return {"success": False, "reason": "broken"}
        return {
            "success": True,
            "document_ingest": {"doc_id": "doc-1"},
            "scene_summary": "scene-summary",
        }


@pytest.fixture
def poyraz_module(monkeypatch: pytest.MonkeyPatch):
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

    monkeypatch.setitem(sys.modules, "config", config_mod)
    monkeypatch.setitem(sys.modules, "core.rag", core_rag_mod)
    monkeypatch.setitem(sys.modules, "managers.web_search", web_search_mod)
    monkeypatch.setitem(sys.modules, "managers.social_media_manager", social_mod)
    monkeypatch.setitem(sys.modules, "agent.base_agent", base_agent_mod)
    monkeypatch.setitem(sys.modules, "agent.registry", registry_mod)

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
    assert {"web_search", "fetch_url", "search_docs", "publish_social", "publish_instagram_post", "publish_facebook_post", "send_whatsapp_message", "build_landing_page", "generate_campaign_copy", "ingest_video_insights", "create_marketing_campaign", "store_content_asset", "create_operation_checklist", "plan_service_operations"} == set(agent.tools)


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
    err = asyncio.run(agent._tool_publish_social(json.dumps({"platform": "bad", "text": "x", "destination": "d", "media_url": "", "link_url": ""})))
    assert ok.startswith("[SOCIAL:PUBLISHED]")
    assert err.startswith("[SOCIAL:ERROR]")

    ig_ok = asyncio.run(agent._tool_publish_instagram_post(json.dumps({"caption": "cap", "image_url": "img"})))
    ig_err = asyncio.run(agent._tool_publish_instagram_post(json.dumps({"caption": "fail", "image_url": "img"})))
    fb_ok = asyncio.run(agent._tool_publish_facebook_post(json.dumps({"message": "msg", "link_url": "lnk"})))
    fb_err = asyncio.run(agent._tool_publish_facebook_post(json.dumps({"message": "fail", "link_url": "lnk"})))
    wa_ok = asyncio.run(agent._tool_send_whatsapp_message(json.dumps({"to": "1", "text": "m", "preview_url": 1})))
    wa_err = asyncio.run(agent._tool_send_whatsapp_message(json.dumps({"to": "0", "text": "m", "preview_url": 0})))

    assert "[INSTAGRAM:PUBLISHED]" in ig_ok and "[INSTAGRAM:ERROR]" in ig_err
    assert "[FACEBOOK:PUBLISHED]" in fb_ok and "[FACEBOOK:ERROR]" in fb_err
    assert "[WHATSAPP:SENT]" in wa_ok and "[WHATSAPP:ERROR]" in wa_err




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


def test_landing_and_campaign_copy_tools_with_and_without_persist(poyraz_module, fake_cfg, monkeypatch):
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

    assert plain.startswith("LLM::") and with_payload.startswith("LLM::")
    assert copy_plain.startswith("LLM::") and copy_payload.startswith("LLM::")
    assert DummyDatabase.instances[-1].add_content_asset_calls


def test_video_ingest_success_and_error(poyraz_module, fake_cfg, monkeypatch):
    mm_mod = types.ModuleType("core.multimodal")
    mm_mod.MultimodalPipeline = DummyMultimodalPipeline
    monkeypatch.setitem(sys.modules, "core.multimodal", mm_mod)

    agent = _agent(poyraz_module, fake_cfg)

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

    assert ok.startswith("[VIDEO:INGESTED]")
    assert err.startswith("[VIDEO:ERROR]")


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


def test_generate_marketing_output_and_run_task_routes(poyraz_module, fake_cfg):
    agent = _agent(poyraz_module, fake_cfg)

    output = asyncio.run(agent._generate_marketing_output("Task", "modex"))
    assert output.startswith("LLM::")

    empty = asyncio.run(agent.run_task("   "))
    assert empty.startswith("[UYARI]")

    routed = {
        "web_search|q": "web:q",
        "fetch_url|u": "fetch:u",
        "search_docs|k": "docs:k:auto:marketing",
        "build_landing_page|brief": "LLM::",
        "landing_page|brief": "LLM::",
        "generate_campaign_copy|brief": "LLM::",
        "publish_instagram_post|" + json.dumps({"caption": "c", "image_url": "i"}): "[INSTAGRAM:PUBLISHED]",
        "publish_facebook_post|" + json.dumps({"message": "m", "link_url": "l"}): "[FACEBOOK:PUBLISHED]",
        "send_whatsapp_message|" + json.dumps({"to": "1", "text": "t", "preview_url": 0}): "[WHATSAPP:SENT]",
        "create_marketing_campaign|" + json.dumps({"tenant_id": "", "name": "n", "channel": "c", "objective": "o", "status": "", "owner_user_id": "u", "budget": 0, "metadata": {}, "campaign_id": None}): '{"success": true',
        "store_content_asset|" + json.dumps({"campaign_id": 1, "tenant_id": "", "asset_type": "a", "title": "t", "content": "c", "channel": "ch", "metadata": {}}): '{"success": true',
        "create_operation_checklist|" + json.dumps({"tenant_id": "", "title": "t", "items": [], "status": "", "owner_user_id": "u", "campaign_id": None}): '{"success": true',
        "plan_service_operations|" + json.dumps({"campaign_name": "c", "service_name": "s", "audience": "a", "menu_plan": {}, "vendor_assignments": {}, "timeline": [], "notes": "", "persist_checklist": False, "tenant_id": "", "checklist_title": "", "owner_user_id": "u", "campaign_id": None}): '{"success": true',
        "seo_audit|x": "LLM::",
        "campaign_copy|x": "LLM::",
        "audience_ops|x": "LLM::",
        "research_to_marketing|x": "LLM::",
        "publish_social|instagram|||x|||d|||m|||l": "[SOCIAL:PUBLISHED]",
        "we need landing page": "LLM::",
        "seo kampanya hedef kitle": "LLM::",
        "other": "LLM::",
    }

    # set up db/mm imports for route paths that need them
    db_mod = types.ModuleType("core.db")
    db_mod.Database = DummyDatabase
    mm_mod = types.ModuleType("core.multimodal")
    mm_mod.MultimodalPipeline = DummyMultimodalPipeline
    sys.modules["core.db"] = db_mod
    sys.modules["core.multimodal"] = mm_mod

    # include ingest route aliases
    ingest1 = asyncio.run(agent.run_task("ingest_video_insights|https://video|||p|||tr|||s|||2"))
    ingest2 = asyncio.run(agent.run_task("analyze_video|bad://video|||p|||tr|||s|||2"))
    assert ingest1.startswith("[VIDEO:INGESTED]")
    assert ingest2.startswith("[VIDEO:ERROR]")

    for prompt, expected in routed.items():
        got = asyncio.run(agent.run_task(prompt))
        assert expected in got
