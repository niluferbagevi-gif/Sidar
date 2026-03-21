import asyncio
import importlib.util
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
