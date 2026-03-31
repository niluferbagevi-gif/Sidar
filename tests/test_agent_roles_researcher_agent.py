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
    def test_empty_prompt_returns_warning(self):
        async def _run():
            m = _get_researcher()
            result = await m.ResearcherAgent().run_task("")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_fetch_url_routing(self):
        async def _run():
            m = _get_researcher()
            result = await m.ResearcherAgent().run_task("fetch_url|https://example.com")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_search_docs_routing(self):
        async def _run():
            m = _get_researcher()
            result = await m.ResearcherAgent().run_task("search_docs|requests get method")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_docs_search_routing(self):
        async def _run():
            m = _get_researcher()
            result = await m.ResearcherAgent().run_task("docs_search|asyncio kullanımı")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_default_web_search(self):
        async def _run():
            m = _get_researcher()
            result = await m.ResearcherAgent().run_task("Python asyncio nedir?")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestResearcherAgentTools:
    def test_web_search_tool(self):
        async def _run():
            m = _get_researcher()
            agent = m.ResearcherAgent()
            result = await agent.call_tool("web_search", "test sorgusu")
            assert "web arama sonucu" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_fetch_url_tool(self):
        async def _run():
            m = _get_researcher()
            agent = m.ResearcherAgent()
            result = await agent.call_tool("fetch_url", "https://example.com")
            assert "sayfa içeriği" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_search_docs_tool(self):
        async def _run():
            m = _get_researcher()
            agent = m.ResearcherAgent()
            result = await agent.call_tool("search_docs", "requests get")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_unknown_tool_returns_error(self):
        async def _run():
            m = _get_researcher()
            agent = m.ResearcherAgent()
            result = await agent.call_tool("unknown_tool", "arg")
            assert "HATA" in result or "hata" in result.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestResearcherAgentDocsSearchAwaitable:
    def test_docs_search_awaits_when_document_store_returns_awaitable(self):
        m = _get_researcher()
        agent = m.ResearcherAgent()

        async def _async_result():
            return True, "await edilen doküman sonucu"

        agent.docs.search = lambda *args, **kwargs: _async_result()
        result = asyncio.run(agent._tool_docs_search("coverage raporu"))
        assert result == "await edilen doküman sonucu"

# ===== MERGED FROM tests/test_agent_roles_researcher_agent_extra.py =====

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Install stubs BEFORE importing researcher_agent
# ---------------------------------------------------------------------------

def _install_stubs():
    # pydantic
    if "pydantic" not in sys.modules:
        pyd = types.ModuleType("pydantic")
        pyd.BaseModel = type("BaseModel", (), {})  # type: ignore[attr-defined]
        sys.modules["pydantic"] = pyd

    # redis
    for mod_name in ("redis", "redis.asyncio", "redis.exceptions"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # chromadb
    for mod_name in ("chromadb", "chromadb.utils", "chromadb.utils.embedding_functions"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # sqlalchemy
    for mod_name in ("sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext", "sqlalchemy.ext.asyncio"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # sentence_transformers
    if "sentence_transformers" not in sys.modules:
        sys.modules["sentence_transformers"] = types.ModuleType("sentence_transformers")

    # opentelemetry
    for mod_name in ("opentelemetry", "opentelemetry.trace"):
        if mod_name not in sys.modules:
            mod = types.ModuleType(mod_name)
            sys.modules[mod_name] = mod
    otel_trace = sys.modules["opentelemetry.trace"]
    if not hasattr(otel_trace, "get_tracer"):
        otel_trace.get_tracer = lambda *a, **kw: None  # type: ignore[attr-defined]

    # bleach
    if "bleach" not in sys.modules:
        sys.modules["bleach"] = types.ModuleType("bleach")

    # torch
    for mod_name in ("torch", "torch.amp"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # pgvector
    if "pgvector" not in sys.modules:
        sys.modules["pgvector"] = types.ModuleType("pgvector")

    # Config stub (her çağrıda taze; kirli config'i devralma)
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        CHROMA_PERSIST_DIRECTORY = "data/chroma"
        USE_GPU = False
        GPU_MIXED_PRECISION = False
        GPU_DEVICE = 0
        RAG_CHUNK_SIZE = 512
        RAG_CHUNK_OVERLAP = 50
        RAG_TOP_K = 3
        RAG_DIR = "/tmp/rag_test"
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        RAG_VECTOR_BACKEND = "chroma"
        AI_PROVIDER = "openai"
        RAG_LOCAL_ENABLE_HYBRID = False
        ENABLE_GRAPH_RAG = False
        BASE_DIR = Path("/tmp")
        GRAPH_RAG_MAX_FILES = 5000
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False
        RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER = 1
        SEARCH_ENGINE = "auto"
        TAVILY_API_KEY = ""
        GOOGLE_SEARCH_API_KEY = ""
        GOOGLE_SEARCH_CX = ""
        WEB_SEARCH_MAX_RESULTS = 5
        WEB_FETCH_TIMEOUT = 15
        WEB_SCRAPE_MAX_CHARS = 12000
        ENABLE_ENTITY_MEMORY = False
        ENTITY_MEMORY_TTL_DAYS = 90
        ENTITY_MEMORY_MAX_PER_USER = 100

    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod

    # core.judge stub
    judge_mod = types.ModuleType("core.judge")

    class _FakeJudge:
        enabled = False

        def schedule_background_evaluation(self, **kw):
            pass

    judge_mod.get_llm_judge = lambda: _FakeJudge()  # type: ignore[attr-defined]
    sys.modules["core.judge"] = judge_mod

    # core.llm_client stub
    llm_mod = types.ModuleType("core.llm_client")

    class _FakeLLMClient:
        def __init__(self, provider, cfg):
            pass

        async def chat(self, messages, **kwargs):
            return "stub response"

    llm_mod.LLMClient = _FakeLLMClient  # type: ignore[attr-defined]
    sys.modules["core.llm_client"] = llm_mod

    # agent.core.contracts stub
    contracts_mod = types.ModuleType("agent.core.contracts")

    class DelegationRequest:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class TaskEnvelope:
        def __init__(self, task_id="t1", goal="", parent_task_id=None, context=None):
            self.task_id = task_id
            self.goal = goal
            self.parent_task_id = parent_task_id
            self.context = context or {}

    class TaskResult:
        def __init__(self, task_id="", status="", summary=None, evidence=None):
            self.task_id = task_id
            self.status = status
            self.summary = summary
            self.evidence = evidence or []

    contracts_mod.DelegationRequest = DelegationRequest  # type: ignore[attr-defined]
    contracts_mod.TaskEnvelope = TaskEnvelope  # type: ignore[attr-defined]
    contracts_mod.TaskResult = TaskResult  # type: ignore[attr-defined]
    contracts_mod.is_delegation_request = lambda x: isinstance(x, DelegationRequest)  # type: ignore[attr-defined]
    sys.modules["agent.core.contracts"] = contracts_mod

    # agent stub (package) — must look like a real package with __path__
    # We replace the real agent package (which tries to import SidarAgent etc.)
    # with a lightweight stub that only provides what we need.
    import importlib
    import os

    # Find the real agent package path so submodules can still be found
    _agent_real_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent")

    _agent_pkg = types.ModuleType("agent")
    _agent_pkg.__path__ = [_agent_real_path]  # type: ignore[attr-defined]
    _agent_pkg.__package__ = "agent"
    _agent_pkg.__spec__ = None
    sys.modules["agent"] = _agent_pkg

    # agent.core stub (package)
    _agent_core_path = os.path.join(_agent_real_path, "core")
    _agent_core = types.ModuleType("agent.core")
    _agent_core.__path__ = [_agent_core_path]  # type: ignore[attr-defined]
    _agent_core.__package__ = "agent.core"
    sys.modules["agent.core"] = _agent_core

    # agent.roles stub (package)
    _agent_roles_path = os.path.join(_agent_real_path, "roles")
    _agent_roles = types.ModuleType("agent.roles")
    _agent_roles.__path__ = [_agent_roles_path]  # type: ignore[attr-defined]
    _agent_roles.__package__ = "agent.roles"
    sys.modules["agent.roles"] = _agent_roles


_install_stubs()

# Remove cached modules so we get a fresh import with stubs in place
for _k in list(sys.modules.keys()):
    if _k in (
        "agent.base_agent",
        "agent.roles.researcher_agent",
        "core.rag",
        "managers.web_search",
    ):
        del sys.modules[_k]

# Now stub core.rag before importing
_rag_mod = types.ModuleType("core.rag")


class _FakeDocumentStore:
    def __init__(self, path, top_k=3, chunk_size=512, chunk_overlap=50,
                 use_gpu=False, gpu_device=0, mixed_precision=False, cfg=None):
        self.path = path

    def search(self, query, doc_id=None, mode="auto", session_id=""):
        return (True, "doc result")


_rag_mod.DocumentStore = _FakeDocumentStore  # type: ignore[attr-defined]
sys.modules["core.rag"] = _rag_mod

# Stub managers.web_search
_wsm_mod = types.ModuleType("managers.web_search")


class _FakeWebSearchManager:
    def __init__(self, cfg=None):
        self.cfg = cfg

    async def search(self, query):
        return (True, "web result")

    async def fetch_url(self, url):
        return (True, "fetched content")

    async def search_docs(self, lib, topic):
        return (True, "docs result")


_wsm_mod.WebSearchManager = _FakeWebSearchManager  # type: ignore[attr-defined]
sys.modules["managers.web_search"] = _wsm_mod

import agent.base_agent  # noqa: E402
import agent.roles.researcher_agent as ra  # noqa: E402

ResearcherAgent = ra.ResearcherAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(cfg=None) -> ResearcherAgent:
    """Build a ResearcherAgent using the fake Config."""
    if cfg is None:
        cfg = sys.modules["config"].Config()
    return ResearcherAgent(cfg=cfg)


# ===========================================================================
# TESTS
# ===========================================================================

# --- __init__ / tool registration ---

def test_extra_init_creates_instance():
    """ResearcherAgent can be instantiated."""
    agent = _make_agent()
    assert agent is not None
    assert agent.role_name == "researcher"


def test_extra_init_registers_web_search_tool():
    """web_search tool is registered in __init__ (line 39)."""
    agent = _make_agent()
    assert "web_search" in agent.tools


def test_extra_init_registers_fetch_url_tool():
    """fetch_url tool is registered in __init__ (line 40)."""
    agent = _make_agent()
    assert "fetch_url" in agent.tools


def test_extra_init_registers_search_docs_tool():
    """search_docs tool is registered in __init__ (line 41)."""
    agent = _make_agent()
    assert "search_docs" in agent.tools


def test_extra_init_registers_docs_search_tool():
    """docs_search tool is registered in __init__ (line 42)."""
    agent = _make_agent()
    assert "docs_search" in agent.tools


def test_extra_init_creates_web_manager():
    """WebSearchManager is created in __init__."""
    agent = _make_agent()
    assert agent.web is not None


def test_extra_init_creates_docs_store():
    """DocumentStore is created in __init__."""
    agent = _make_agent()
    assert agent.docs is not None


def test_extra_system_prompt_is_set():
    """SYSTEM_PROMPT class attribute is non-empty."""
    assert ResearcherAgent.SYSTEM_PROMPT
    assert "araştırmacı" in ResearcherAgent.SYSTEM_PROMPT


# --- _tool_web_search ---

def test_extra_tool_web_search_returns_result():
    """_tool_web_search calls web.search and returns result string (lines 45-46)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_web_search("python asyncio"))
    assert result == "web result"


def test_extra_tool_web_search_passes_query():
    """_tool_web_search passes the full query to web.search."""
    agent = _make_agent()
    captured = []

    async def _fake_search(q):
        captured.append(q)
        return (True, "ok")

    agent.web.search = _fake_search
    asyncio.run(agent._tool_web_search("my query"))
    assert captured == ["my query"]


# --- _tool_fetch_url ---

def test_extra_tool_fetch_url_returns_result():
    """_tool_fetch_url calls web.fetch_url and returns result (lines 49-50)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_fetch_url("https://example.com"))
    assert result == "fetched content"


def test_extra_tool_fetch_url_passes_url():
    """_tool_fetch_url passes the URL to web.fetch_url."""
    agent = _make_agent()
    captured = []

    async def _fake_fetch(url):
        captured.append(url)
        return (True, "content")

    agent.web.fetch_url = _fake_fetch
    asyncio.run(agent._tool_fetch_url("https://test.io"))
    assert captured == ["https://test.io"]


# --- _tool_search_docs ---

def test_extra_tool_search_docs_single_word():
    """_tool_search_docs with single word uses it as lib and empty topic (lines 53-57)."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "result")

    agent.web.search_docs = _fake_search_docs
    asyncio.run(agent._tool_search_docs("fastapi"))
    assert captured == [("fastapi", "")]


def test_extra_tool_search_docs_two_words():
    """_tool_search_docs splits arg into lib and topic."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "result")

    agent.web.search_docs = _fake_search_docs
    asyncio.run(agent._tool_search_docs("fastapi routing basics"))
    assert captured == [("fastapi", "routing basics")]


def test_extra_tool_search_docs_returns_result():
    """_tool_search_docs returns the string result."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_search_docs("requests authentication"))
    assert result == "docs result"


def test_extra_tool_search_docs_empty_arg():
    """_tool_search_docs handles empty string gracefully."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "r")

    agent.web.search_docs = _fake_search_docs
    asyncio.run(agent._tool_search_docs(""))
    assert captured == [("", "")]


# --- _tool_docs_search ---

def test_extra_tool_docs_search_returns_result():
    """_tool_docs_search calls docs.search via asyncio.to_thread (lines 60-65)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_docs_search("vector search"))
    assert result == "doc result"


def test_extra_tool_docs_search_uses_global_session():
    """_tool_docs_search always passes 'global' as session_id."""
    agent = _make_agent()
    captured = []

    def _fake_search(query, doc_id, mode, session_id):
        captured.append(session_id)
        return (True, "r")

    agent.docs.search = _fake_search
    asyncio.run(agent._tool_docs_search("query"))
    assert captured == ["global"]


def test_extra_tool_docs_search_handles_awaitable_result():
    """_tool_docs_search awaits result_obj if it is awaitable (lines 62-63)."""
    agent = _make_agent()

    async def _async_search(query, doc_id, mode, session_id):
        return (True, "awaited result")

    agent.docs.search = _async_search
    result = asyncio.run(agent._tool_docs_search("query"))
    assert result == "awaited result"


# --- run_task ---

def test_extra_run_task_empty_prompt_returns_warning():
    """run_task with empty string returns warning (line 69-70)."""
    agent = _make_agent()
    result = asyncio.run(agent.run_task(""))
    assert "[UYARI]" in result


def test_extra_run_task_whitespace_only_returns_warning():
    """run_task with whitespace-only string returns warning."""
    agent = _make_agent()
    result = asyncio.run(agent.run_task("   "))
    assert "[UYARI]" in result


def test_extra_run_task_fetch_url_prefix():
    """run_task with fetch_url| prefix dispatches to fetch_url tool (lines 73-74)."""
    agent = _make_agent()
    captured = []

    async def _fake_fetch(url):
        captured.append(url)
        return (True, "fetched")

    agent.web.fetch_url = _fake_fetch
    result = asyncio.run(agent.run_task("fetch_url|https://example.com"))
    assert captured == ["https://example.com"]
    assert result == "fetched"


def test_extra_run_task_fetch_url_prefix_case_insensitive():
    """run_task with FETCH_URL| prefix (upper case) also dispatches to fetch_url."""
    agent = _make_agent()
    captured = []

    async def _fake_fetch(url):
        captured.append(url)
        return (True, "fetched2")

    agent.web.fetch_url = _fake_fetch
    result = asyncio.run(agent.run_task("FETCH_URL|https://test.com"))
    assert result == "fetched2"


def test_extra_run_task_search_docs_prefix():
    """run_task with search_docs| prefix dispatches to search_docs tool (lines 75-76)."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "sdocs")

    agent.web.search_docs = _fake_search_docs
    result = asyncio.run(agent.run_task("search_docs|requests auth"))
    assert result == "sdocs"
    assert captured == [("requests", "auth")]


def test_extra_run_task_docs_search_prefix():
    """run_task with docs_search| prefix dispatches to docs_search tool (lines 77-78)."""
    agent = _make_agent()
    captured = []

    def _fake_search(query, doc_id, mode, session_id):
        captured.append(query)
        return (True, "local_docs")

    agent.docs.search = _fake_search
    result = asyncio.run(agent.run_task("docs_search|vector embedding"))
    assert result == "local_docs"
    assert captured == ["vector embedding"]


def test_extra_run_task_default_uses_web_search():
    """run_task with plain text defaults to web_search tool (line 80)."""
    agent = _make_agent()
    captured = []

    async def _fake_search(q):
        captured.append(q)
        return (True, "web")

    agent.web.search = _fake_search
    result = asyncio.run(agent.run_task("what is FastAPI"))
    assert result == "web"
    assert captured == ["what is FastAPI"]


def test_extra_run_task_default_does_not_use_fetch_url():
    """run_task with plain text does NOT call fetch_url."""
    agent = _make_agent()
    fetch_called = []

    async def _fake_fetch(url):
        fetch_called.append(url)
        return (True, "x")

    agent.web.fetch_url = _fake_fetch
    asyncio.run(agent.run_task("search something"))
    assert fetch_called == []


def test_extra_call_tool_unknown_tool_returns_error():
    """call_tool with unregistered name returns error message (from BaseAgent)."""
    agent = _make_agent()
    result = asyncio.run(agent.call_tool("nonexistent_tool", "arg"))
    assert "[HATA]" in result


def test_extra_run_task_search_docs_uppercase_prefix():
    """run_task with SEARCH_DOCS| is case-insensitive (lower comparison)."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "r")

    agent.web.search_docs = _fake_search_docs
    result = asyncio.run(agent.run_task("SEARCH_DOCS|numpy linalg"))
    assert result == "r"
