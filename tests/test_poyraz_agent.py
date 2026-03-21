import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_poyraz_agent_class():
    saved = {name: sys.modules.get(name) for name in (
        "agent", "agent.base_agent", "agent.core", "agent.core.contracts", "config", "core",
        "core.llm_client", "core.rag", "managers", "managers.web_search", "managers.social_media_manager", "agent.roles.poyraz_agent",
    )}

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    root_core_pkg = types.ModuleType("core")
    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = [str(ROOT / "managers")]
    config_mod = types.ModuleType("config")
    llm_client_mod = types.ModuleType("core.llm_client")
    rag_mod = types.ModuleType("core.rag")
    web_search_mod = types.ModuleType("managers.web_search")
    social_media_mod = types.ModuleType("managers.social_media_manager")

    class _Config:
        AI_PROVIDER = "test"
        RAG_DIR = str(ROOT / "data")
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 256
        RAG_CHUNK_OVERLAP = 32
        USE_GPU = False
        GPU_DEVICE = "cpu"
        GPU_MIXED_PRECISION = False

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def chat(self, **_kwargs):
            return "stub"

    class _DocumentStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def search(self, query, *_args, **_kwargs):
            return True, f"docs:{query}"

    class _WebSearchManager:
        def __init__(self, *_args, **_kwargs):
            pass

        async def search(self, query):
            return True, f"web:{query}"

        async def fetch_url(self, url):
            return True, f"fetch:{url}"

    class _SocialMediaManager:
        def __init__(self, *_args, **_kwargs):
            pass

        async def publish_content(self, **kwargs):
            return True, f"published:{kwargs.get('platform', '')}"

        async def publish_instagram_post(self, **kwargs):
            return True, f"instagram:{kwargs.get('caption', '')}"

        async def publish_facebook_post(self, **kwargs):
            return True, f"facebook:{kwargs.get('message', '')}"

        async def send_whatsapp_message(self, **kwargs):
            return True, f"whatsapp:{kwargs.get('to', '')}"

    config_mod.Config = _Config
    llm_client_mod.LLMClient = _LLMClient
    rag_mod.DocumentStore = _DocumentStore
    web_search_mod.WebSearchManager = _WebSearchManager
    social_media_mod.SocialMediaManager = _SocialMediaManager
    root_core_pkg.llm_client = llm_client_mod
    root_core_pkg.rag = rag_mod

    sys.modules.update({
        "agent": agent_pkg,
        "agent.core": core_pkg,
        "config": config_mod,
        "core": root_core_pkg,
        "core.llm_client": llm_client_mod,
        "core.rag": rag_mod,
        "managers": managers_pkg,
        "managers.web_search": web_search_mod,
        "managers.social_media_manager": social_media_mod,
    })

    try:
        for name, rel_path in (
            ("agent.core.contracts", "agent/core/contracts.py"),
            ("agent.base_agent", "agent/base_agent.py"),
            ("agent.roles.poyraz_agent", "agent/roles/poyraz_agent.py"),
        ):
            spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        return sys.modules["agent.roles.poyraz_agent"].PoyrazAgent
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


PoyrazAgent = _load_poyraz_agent_class()


def test_poyraz_agent_initializes_with_marketing_tools():
    agent = PoyrazAgent()
    assert set(agent.tools.keys()) == {
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


def test_poyraz_agent_routes_prefixed_marketing_tasks(monkeypatch):
    agent = PoyrazAgent()
    seen = {}

    async def _fake_generate(task_prompt: str, mode: str) -> str:
        seen["task_prompt"] = task_prompt
        seen["mode"] = mode
        return "kampanya taslağı"

    monkeypatch.setattr(agent, "_generate_marketing_output", _fake_generate)

    out = asyncio.run(agent.run_task("campaign_copy|Yeni ürün lansmanı için LinkedIn kampanyası"))

    assert out == "kampanya taslağı"
    assert seen == {
        "task_prompt": "Yeni ürün lansmanı için LinkedIn kampanyası",
        "mode": "campaign_copy",
    }


def test_poyraz_agent_detects_marketing_intent_in_freeform_prompt(monkeypatch):
    agent = PoyrazAgent()
    seen = {}

    async def _fake_generate(task_prompt: str, mode: str) -> str:
        seen["task_prompt"] = task_prompt
        seen["mode"] = mode
        return "seo planı"

    monkeypatch.setattr(agent, "_generate_marketing_output", _fake_generate)

    out = asyncio.run(agent.run_task("SEO görünürlüğünü artırmak için 30 günlük plan çıkar"))

    assert out == "seo planı"
    assert seen["mode"] == "marketing_strategy"
    assert "30 günlük plan" in seen["task_prompt"]


def test_poyraz_agent_routes_social_publish_tool():
    agent = PoyrazAgent()
    out = asyncio.run(agent.run_task("publish_social|instagram|||Yeni kampanya|||@brand|||https://img.test/post.jpg"))
    assert out == "[SOCIAL:PUBLISHED] platform=instagram result=published:instagram"


def test_poyraz_agent_routes_json_marketing_tools():
    agent = PoyrazAgent()

    social_out = asyncio.run(
        agent.run_task('publish_social|{"platform":"facebook","text":"Yeni duyuru","link_url":"https://example.test"}')
    )
    assert social_out == "[SOCIAL:PUBLISHED] platform=facebook result=published:facebook"

    landing_out = asyncio.run(
        agent.run_task(
            'build_landing_page|{"brand_name":"Sidar","offer":"Demo","audience":"KOBI","call_to_action":"Kaydol"}'
        )
    )
    assert landing_out == "stub"


def test_poyraz_agent_routes_channel_specific_social_tools(monkeypatch):
    agent = PoyrazAgent()
    seen = {}

    async def _fake_instagram(**kwargs):
        seen["instagram"] = kwargs
        return True, "ig-1"

    async def _fake_facebook(**kwargs):
        seen["facebook"] = kwargs
        return True, "fb-2"

    async def _fake_whatsapp(**kwargs):
        seen["whatsapp"] = kwargs
        return True, "wa-3"

    monkeypatch.setattr(agent.social, "publish_instagram_post", _fake_instagram)
    monkeypatch.setattr(agent.social, "publish_facebook_post", _fake_facebook)
    monkeypatch.setattr(agent.social, "send_whatsapp_message", _fake_whatsapp)

    instagram_out = asyncio.run(
        agent.run_task('publish_instagram_post|{"caption":"Yeni post","image_url":"https://cdn.test/post.jpg"}')
    )
    facebook_out = asyncio.run(
        agent.run_task('publish_facebook_post|{"message":"Duyuru","link_url":"https://example.test"}')
    )
    whatsapp_out = asyncio.run(
        agent.run_task('send_whatsapp_message|{"to":"+905555555555","text":"Merhaba","preview_url":true}')
    )

    assert instagram_out == "[INSTAGRAM:PUBLISHED] result=ig-1"
    assert facebook_out == "[FACEBOOK:PUBLISHED] result=fb-2"
    assert whatsapp_out == "[WHATSAPP:SENT] result=wa-3"
    assert seen["instagram"]["caption"] == "Yeni post"
    assert seen["facebook"]["link_url"] == "https://example.test"
    assert seen["whatsapp"]["preview_url"] is True


def test_poyraz_agent_persists_campaign_assets_and_service_plan(monkeypatch):
    agent = PoyrazAgent()

    class _Db:
        async def upsert_marketing_campaign(self, **kwargs):
            return types.SimpleNamespace(
                id=14,
                tenant_id=kwargs["tenant_id"],
                name=kwargs["name"],
                channel=kwargs["channel"],
                objective=kwargs["objective"],
                status=kwargs["status"],
                owner_user_id=kwargs["owner_user_id"],
                budget=kwargs["budget"],
            )

        async def add_content_asset(self, **kwargs):
            return types.SimpleNamespace(
                id=22,
                campaign_id=kwargs["campaign_id"],
                tenant_id=kwargs["tenant_id"],
                asset_type=kwargs["asset_type"],
                title=kwargs["title"],
                content=kwargs["content"],
                channel=kwargs["channel"],
            )

        async def add_operation_checklist(self, **kwargs):
            return types.SimpleNamespace(
                id=31,
                campaign_id=kwargs.get("campaign_id"),
                tenant_id=kwargs["tenant_id"],
                title=kwargs["title"],
                items_json=str(kwargs["items"]),
                status=kwargs["status"],
            )

    async def _fake_ensure_db():
        return _Db()

    monkeypatch.setattr(agent, "_ensure_db", _fake_ensure_db)

    campaign_out = asyncio.run(
        agent.run_task(
            'create_marketing_campaign|{"tenant_id":"tenant-a","name":"Yaz Lansmanı","channel":"instagram","objective":"lead","status":"draft","owner_user_id":"u-1","budget":2500}'
        )
    )

    monkeypatch.setattr(agent, "_generate_marketing_output", lambda *_args, **_kwargs: asyncio.sleep(0, result="landing taslağı"))
    landing_out = asyncio.run(
        agent.run_task(
            'build_landing_page|{"brand_name":"Sidar","offer":"Demo","audience":"KOBI","call_to_action":"Kaydol","campaign_id":14,"tenant_id":"tenant-a","store_asset":true}'
        )
    )
    plan_out = asyncio.run(
        agent.run_task(
            'plan_service_operations|{"tenant_id":"tenant-a","campaign_id":14,"campaign_name":"Doğum Günü","service_name":"Etkinlik","menu_plan":{"adult":["Izgara"],"child":["Mini pizza"]},"vendor_assignments":{"DJ":"Efe","Fotografci":"Luna"},"timeline":["18:00 karşılama"],"persist_checklist":true}'
        )
    )

    assert '"id": 14' in campaign_out
    assert landing_out == "landing taslağı"
    assert '"success": true' in plan_out.lower()
    assert '"menu_plan"' in plan_out


def test_poyraz_agent_ingests_video_insights_into_docs():
    agent = PoyrazAgent()

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze_media_source(self, **kwargs):
            assert kwargs["media_source"].endswith("dQw4w9WgXcQ")
            return {
                "success": True,
                "scene_summary": "0.0s → güçlü açılış",
                "document_ingest": {"doc_id": "doc-42"},
            }

    fake_module = types.SimpleNamespace(MultimodalPipeline=_Pipeline)
    with patch.dict(sys.modules, {"core.multimodal": fake_module}):
        out = asyncio.run(
            agent.run_task(
                'ingest_video_insights|{"source_url":"https://youtu.be/dQw4w9WgXcQ","prompt":"hook çıkar","session_id":"marketing"}'
            )
        )

    assert out == "[VIDEO:INGESTED] source=https://youtu.be/dQw4w9WgXcQ doc_id=doc-42 scene_summary=0.0s → güçlü açılış"


def test_poyraz_agent_db_and_search_helpers_cover_cache_and_async_paths(monkeypatch):
    agent = PoyrazAgent()
    calls = {"db": 0, "connect": 0, "init_schema": 0}

    class _Database:
        def __init__(self, _cfg):
            calls["db"] += 1

        async def connect(self):
            calls["connect"] += 1

        async def init_schema(self):
            calls["init_schema"] += 1

    fake_db_mod = types.SimpleNamespace(Database=_Database)
    with patch.dict(sys.modules, {"core.db": fake_db_mod}):
        db_first = asyncio.run(agent._ensure_db())
        db_second = asyncio.run(agent._ensure_db())

    assert db_first is db_second
    assert calls == {"db": 1, "connect": 1, "init_schema": 1}

    async def _async_search(query, *_args):
        return True, f"docs-async:{query}"

    monkeypatch.setattr(agent.docs, "search", _async_search)

    web_out = asyncio.run(agent._tool_web_search("trend raporu"))
    fetch_out = asyncio.run(agent._tool_fetch_url("https://sidar.dev"))
    docs_out = asyncio.run(agent._tool_search_docs("seo checklist"))

    assert web_out == "web:trend raporu"
    assert fetch_out == "fetch:https://sidar.dev"
    assert docs_out == "docs-async:seo checklist"


def test_poyraz_agent_social_tool_error_branches(monkeypatch):
    agent = PoyrazAgent()

    async def _social_error(**kwargs):
        return False, f"bad:{kwargs.get('platform', '')}"

    async def _instagram_error(**_kwargs):
        return False, "ig-down"

    async def _facebook_error(**_kwargs):
        return False, "fb-down"

    async def _whatsapp_error(**_kwargs):
        return False, "wa-down"

    monkeypatch.setattr(agent.social, "publish_content", _social_error)
    monkeypatch.setattr(agent.social, "publish_instagram_post", _instagram_error)
    monkeypatch.setattr(agent.social, "publish_facebook_post", _facebook_error)
    monkeypatch.setattr(agent.social, "send_whatsapp_message", _whatsapp_error)

    social_out = asyncio.run(
        agent._tool_publish_social('{"platform":"instagram","text":"Post","destination":"@brand","media_url":"https://img","link_url":"https://site"}')
    )
    instagram_out = asyncio.run(
        agent._tool_publish_instagram_post('{"caption":"Yeni post","image_url":"https://img.test/post.jpg"}')
    )
    facebook_out = asyncio.run(
        agent._tool_publish_facebook_post('{"message":"Duyuru","link_url":"https://example.test"}')
    )
    whatsapp_out = asyncio.run(
        agent._tool_send_whatsapp_message('{"to":"+905555555555","text":"Merhaba","preview_url":false}')
    )

    assert social_out == "[SOCIAL:ERROR] platform=instagram reason=bad:instagram"
    assert instagram_out == "[INSTAGRAM:ERROR] reason=ig-down"
    assert facebook_out == "[FACEBOOK:ERROR] reason=fb-down"
    assert whatsapp_out == "[WHATSAPP:ERROR] reason=wa-down"


def test_poyraz_agent_campaign_copy_and_operation_payloads_are_persisted(monkeypatch):
    agent = PoyrazAgent()
    persisted_assets = []
    persisted_checklists = []
    prompts = []

    async def _fake_generate(task_prompt: str, mode: str) -> str:
        prompts.append((mode, task_prompt))
        return f"{mode}:ok"

    async def _fake_persist_content_asset(**kwargs):
        persisted_assets.append(kwargs)
        return json.dumps({"success": True, "asset": {"id": 55}}, ensure_ascii=False)

    class _Db:
        async def add_operation_checklist(self, **kwargs):
            persisted_checklists.append(kwargs)
            return types.SimpleNamespace(
                id=77,
                campaign_id=kwargs.get("campaign_id"),
                tenant_id=kwargs["tenant_id"],
                title=kwargs["title"],
                status=kwargs["status"],
                items_json=json.dumps(kwargs["items"], ensure_ascii=False),
            )

    async def _fake_ensure_db():
        return _Db()

    monkeypatch.setattr(agent, "_generate_marketing_output", _fake_generate)
    monkeypatch.setattr(agent, "_persist_content_asset", _fake_persist_content_asset)
    monkeypatch.setattr(agent, "_ensure_db", _fake_ensure_db)

    raw_copy_out = asyncio.run(agent._tool_generate_campaign_copy("Ham brief metni"))
    json_copy_out = asyncio.run(
        agent._tool_generate_campaign_copy(
            '{"tenant_id":"tenant-a","campaign_id":12,"campaign_name":"Launch","objective":"lead","audience":"KOBI","channels":["instagram","linkedin"],"offer":"Demo","tone":"direct","call_to_action":"Kaydol","store_asset":true,"asset_title":"Launch Copy"}'
        )
    )
    checklist_out = asyncio.run(
        agent._tool_create_operation_checklist(
            '{"tenant_id":"tenant-a","campaign_id":12,"title":"Etkinlik Öncesi","items":[{"type":"vendor"}],"owner_user_id":"u-1"}'
        )
    )
    plan_out = asyncio.run(
        agent._tool_plan_service_operations(
            '{"tenant_id":"tenant-a","campaign_id":12,"campaign_name":"Launch","service_name":"Roadshow","audience":"B2B","menu_plan":{"adult":["Izgara","  "],"child":[]},"vendor_assignments":{"DJ":"Efe","Hostes":"  "},"timeline":["18:00 karşılama","  "],"notes":"Sahne kurulumu kontrolü","persist_checklist":true,"checklist_title":"Saha Operasyonları","owner_user_id":"u-1"}'
        )
    )

    plan_payload = json.loads(plan_out)
    checklist_payload = json.loads(checklist_out)

    assert raw_copy_out == "campaign_copy_tool:ok"
    assert json_copy_out == "campaign_copy_tool:ok"
    assert prompts[0] == ("campaign_copy_tool", "Aşağıdaki brief için kanal bazlı kampanya kopyaları üret. Her kanal için kısa ana mesaj, CTA ve önerilen kreatif açıyı ekle.\n\nHam brief metni")
    assert persisted_assets[0]["asset_type"] == "campaign_copy"
    assert persisted_assets[0]["title"] == "Launch Copy"
    assert persisted_assets[0]["metadata"]["channels"] == ["instagram", "linkedin"]
    assert checklist_payload["checklist"]["status"] == "pending"
    assert plan_payload["service_plan"]["checklist"]["status"] == "planned"
    assert plan_payload["service_plan"]["items"] == [
        {"type": "menu_plan", "group": "adult", "options": ["Izgara"]},
        {"type": "vendor_assignment", "role": "DJ", "assignee": "Efe"},
        {"type": "timeline", "entry": "18:00 karşılama"},
        {"type": "note", "text": "Sahne kurulumu kontrolü"},
    ]
    assert persisted_checklists[0]["status"] == "pending"
    assert persisted_checklists[1]["title"] == "Saha Operasyonları"


def test_poyraz_agent_video_asset_and_prompt_helpers(monkeypatch):
    agent = PoyrazAgent()
    persisted_assets = []
    llm_calls = []

    async def _fake_persist_content_asset(**kwargs):
        persisted_assets.append(kwargs)
        return json.dumps({"success": True}, ensure_ascii=False)

    async def _fake_call_llm(messages, **kwargs):
        llm_calls.append({"messages": messages, **kwargs})
        return "llm-ok"

    monkeypatch.setattr(agent, "_persist_content_asset", _fake_persist_content_asset)
    monkeypatch.setattr(agent, "call_llm", _fake_call_llm)

    landing_out = asyncio.run(agent._tool_build_landing_page("Özel bir landing briefi"))
    generated_out = asyncio.run(agent._generate_marketing_output("Yeni teklif", "marketing_general"))

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze_media_source(self, **kwargs):
            assert kwargs["media_source"] == "https://video.test/demo.mp4"
            assert kwargs["prompt"] == "öne çıkan sahneleri çıkar"
            assert kwargs["language"] == "tr"
            assert kwargs["ingest_session_id"] == "session-9"
            assert kwargs["max_frames"] == 8
            assert kwargs["frame_interval_seconds"] == 5.0
            return {"success": False, "reason": "pipeline-fail"}

    fake_module = types.SimpleNamespace(MultimodalPipeline=_Pipeline)
    with patch.dict(sys.modules, {"core.multimodal": fake_module}):
        video_out = asyncio.run(
            agent._tool_ingest_video_insights(
                "https://video.test/demo.mp4|||öne çıkan sahneleri çıkar|||tr|||session-9|||8"
            )
        )

    store_out = asyncio.run(
        agent._tool_store_content_asset(
            '{"campaign_id":41,"asset_type":"brief","title":"İçerik Kartı","content":"gövde","channel":"email","metadata":{"lang":"tr"}}'
        )
    )

    assert landing_out == "llm-ok"
    assert generated_out == "llm-ok"
    assert "[GOREV]\nYeni teklif" in llm_calls[1]["messages"][0]["content"]
    assert llm_calls[1]["system_prompt"] == agent.SYSTEM_PROMPT
    assert video_out == "[VIDEO:ERROR] source=https://video.test/demo.mp4 reason=pipeline-fail"
    assert json.loads(store_out)["success"] is True
    assert persisted_assets[0]["campaign_id"] == 41
    assert persisted_assets[0]["metadata"] == {"lang": "tr"}


def test_poyraz_agent_run_task_fallback_paths(monkeypatch):
    agent = PoyrazAgent()
    calls = {"tool": [], "generate": []}

    async def _fake_call_tool(name: str, payload: str) -> str:
        calls["tool"].append((name, payload))
        return f"tool:{name}"

    async def _fake_generate(task_prompt: str, mode: str) -> str:
        calls["generate"].append((mode, task_prompt))
        return f"gen:{mode}"

    monkeypatch.setattr(agent, "call_tool", _fake_call_tool)
    monkeypatch.setattr(agent, "_generate_marketing_output", _fake_generate)

    empty_out = asyncio.run(agent.run_task("   "))
    landing_intent_out = asyncio.run(agent.run_task("Landing page için etkinlik sayfası hazırla"))
    audience_out = asyncio.run(agent.run_task("audience_ops|yeniden hedefleme planı"))
    research_out = asyncio.run(agent.run_task("research_to_marketing|araştırmayı kampanyaya çevir"))
    general_out = asyncio.run(agent.run_task("müşteri sadakat akışı öner"))

    assert empty_out == "[UYARI] Boş pazarlama görevi verildi."
    assert landing_intent_out == "tool:build_landing_page"
    assert audience_out == "gen:audience_ops"
    assert research_out == "gen:research_to_marketing"
    assert general_out == "gen:marketing_general"
    assert calls["tool"][0][0] == "build_landing_page"
    landing_payload = json.loads(calls["tool"][0][1])
    assert landing_payload["brand_name"] == "SİDAR"
    assert calls["generate"][-1] == ("marketing_general", "müşteri sadakat akışı öner")


def test_poyraz_agent_ensure_db_returns_cached_value_inside_lock():
    agent = PoyrazAgent()
    sentinel_db = object()

    class _LockThatSeedsDb:
        async def __aenter__(self):
            agent._db = sentinel_db
            return self

        async def __aexit__(self, *_args):
            return False

    agent._db = None
    agent._db_lock = _LockThatSeedsDb()

    db = asyncio.run(agent._ensure_db())

    assert db is sentinel_db


def test_poyraz_agent_routes_additional_prefixed_tools(monkeypatch):
    agent = PoyrazAgent()
    calls = {"tool": [], "generate": []}

    async def _fake_call_tool(name: str, payload: str) -> str:
        calls["tool"].append((name, payload))
        return f"tool:{name}:{payload}"

    async def _fake_generate(task_prompt: str, mode: str) -> str:
        calls["generate"].append((mode, task_prompt))
        return f"gen:{mode}:{task_prompt}"

    monkeypatch.setattr(agent, "call_tool", _fake_call_tool)
    monkeypatch.setattr(agent, "_generate_marketing_output", _fake_generate)

    web_search_out = asyncio.run(agent.run_task("web_search| trend raporu "))
    fetch_out = asyncio.run(agent.run_task("fetch_url| https://sidar.dev/blog "))
    docs_out = asyncio.run(agent.run_task("search_docs| growth playbook "))
    copy_out = asyncio.run(agent.run_task('generate_campaign_copy|{"brief":"launch"}'))
    store_out = asyncio.run(agent.run_task('store_content_asset|{"title":"Asset"}'))
    checklist_out = asyncio.run(agent.run_task('create_operation_checklist|{"title":"Checklist"}'))
    seo_out = asyncio.run(agent.run_task("seo_audit| teknik seo özeti "))

    assert web_search_out == "tool:web_search:trend raporu"
    assert fetch_out == "tool:fetch_url:https://sidar.dev/blog"
    assert docs_out == "tool:search_docs:growth playbook"
    assert copy_out == 'tool:generate_campaign_copy:{"brief":"launch"}'
    assert store_out == 'tool:store_content_asset:{"title":"Asset"}'
    assert checklist_out == 'tool:create_operation_checklist:{"title":"Checklist"}'
    assert seo_out == "gen:seo_audit:teknik seo özeti"
    assert calls["tool"] == [
        ("web_search", "trend raporu"),
        ("fetch_url", "https://sidar.dev/blog"),
        ("search_docs", "growth playbook"),
        ("generate_campaign_copy", '{"brief":"launch"}'),
        ("store_content_asset", '{"title":"Asset"}'),
        ("create_operation_checklist", '{"title":"Checklist"}'),
    ]
    assert calls["generate"] == [("seo_audit", "teknik seo özeti")]