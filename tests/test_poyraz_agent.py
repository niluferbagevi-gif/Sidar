import asyncio
import importlib.util
import sys
import types
from pathlib import Path


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
        "build_landing_page",
        "generate_campaign_copy",
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
