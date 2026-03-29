"""
agent/roles/researcher_agent.py için birim testleri.
"""
from __future__ import annotations

import asyncio
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_researcher_deps():
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
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core stubs — always replace so real modules don't interfere
    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock(); mock_llm.chat = AsyncMock(return_value="llm yanıtı")
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
    for mod, cls in [("managers", None), ("managers.web_search", "WebSearchManager")]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_web = MagicMock()
            mock_web.search = AsyncMock(return_value=(True, "web arama sonucu"))
            mock_web.fetch_url = AsyncMock(return_value=(True, "sayfa içeriği"))
            mock_web.search_docs = AsyncMock(return_value=(True, "doküman bilgisi"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_web)

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        class _BaseAgent:
            def __init__(self, *a, cfg=None, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock(); self.llm.chat = AsyncMock(return_value="llm yanıtı")
                self.tools = {}
            def register_tool(self, name, fn): self.tools[name] = fn
            async def call_tool(self, name, arg):
                if name not in self.tools: return f"HATA: {name} bulunamadı"
                return await self.tools[name](arg)
            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, **kw): return "llm yanıtı"
        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_researcher():
    _stub_researcher_deps()
    sys.modules.pop("agent.roles.researcher_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles"); roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.researcher_agent as m
    return m


class TestResearcherAgentInit:
    def test_instantiation(self):
        m = _get_researcher()
        assert m.ResearcherAgent() is not None

    def test_role_name(self):
        m = _get_researcher()
        assert m.ResearcherAgent().role_name == "researcher"

    def test_tools_registered(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()
        for tool in ("web_search", "fetch_url", "search_docs", "docs_search"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"


class TestResearcherAgentRunTask:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_warning(self):
        m = _get_researcher()
        result = await m.ResearcherAgent().run_task("")
        assert "UYARI" in result

    @pytest.mark.asyncio
    async def test_fetch_url_routing(self):
        m = _get_researcher()
        result = await m.ResearcherAgent().run_task("fetch_url|https://example.com")
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_docs_routing(self):
        m = _get_researcher()
        result = await m.ResearcherAgent().run_task("search_docs|requests get method")
        assert result is not None

    @pytest.mark.asyncio
    async def test_docs_search_routing(self):
        m = _get_researcher()
        result = await m.ResearcherAgent().run_task("docs_search|asyncio kullanımı")
        assert result is not None

    @pytest.mark.asyncio
    async def test_default_web_search(self):
        m = _get_researcher()
        result = await m.ResearcherAgent().run_task("Python asyncio nedir?")
        assert result is not None


class TestResearcherAgentTools:
    @pytest.mark.asyncio
    async def test_web_search_tool(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()
        result = await agent.call_tool("web_search", "test sorgusu")
        assert "web arama sonucu" in result

    @pytest.mark.asyncio
    async def test_fetch_url_tool(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()
        result = await agent.call_tool("fetch_url", "https://example.com")
        assert "sayfa içeriği" in result

    @pytest.mark.asyncio
    async def test_search_docs_tool(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()
        result = await agent.call_tool("search_docs", "requests get")
        assert result is not None

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()
        result = await agent.call_tool("unknown_tool", "arg")
        assert "HATA" in result or "hata" in result.lower()


class TestResearcherAgentDocsSearchAwaitable:
    def test_docs_search_awaits_when_document_store_returns_awaitable(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()

        async def _async_result():
            return True, "await edilen doküman sonucu"

        agent.docs.search = lambda *args, **kwargs: _async_result()
        result = asyncio.run(agent._tool_docs_search("coverage raporu"))
        assert result == "await edilen doküman sonucu"
