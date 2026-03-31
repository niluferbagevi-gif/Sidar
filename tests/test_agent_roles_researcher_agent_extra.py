"""
Extra tests for agent/roles/researcher_agent.py targeting missing coverage lines.

Missing lines targeted:
  39-42: register_tool() calls in __init__
  45-46: _tool_web_search()
  49-50: _tool_fetch_url()
  53-57: _tool_search_docs()
  60-65: _tool_docs_search()
  68-80: run_task() all branches

Uses sys.modules stubbing for ALL heavy deps.
Uses asyncio.run() for async tests (NO @pytest.mark.asyncio).
"""
from __future__ import annotations

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

    # Config stub
    if "config" not in sys.modules:
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

def test_init_creates_instance():
    """ResearcherAgent can be instantiated."""
    agent = _make_agent()
    assert agent is not None
    assert agent.role_name == "researcher"


def test_init_registers_web_search_tool():
    """web_search tool is registered in __init__ (line 39)."""
    agent = _make_agent()
    assert "web_search" in agent.tools


def test_init_registers_fetch_url_tool():
    """fetch_url tool is registered in __init__ (line 40)."""
    agent = _make_agent()
    assert "fetch_url" in agent.tools


def test_init_registers_search_docs_tool():
    """search_docs tool is registered in __init__ (line 41)."""
    agent = _make_agent()
    assert "search_docs" in agent.tools


def test_init_registers_docs_search_tool():
    """docs_search tool is registered in __init__ (line 42)."""
    agent = _make_agent()
    assert "docs_search" in agent.tools


def test_init_creates_web_manager():
    """WebSearchManager is created in __init__."""
    agent = _make_agent()
    assert agent.web is not None


def test_init_creates_docs_store():
    """DocumentStore is created in __init__."""
    agent = _make_agent()
    assert agent.docs is not None


def test_system_prompt_is_set():
    """SYSTEM_PROMPT class attribute is non-empty."""
    assert ResearcherAgent.SYSTEM_PROMPT
    assert "araştırmacı" in ResearcherAgent.SYSTEM_PROMPT


# --- _tool_web_search ---

def test_tool_web_search_returns_result():
    """_tool_web_search calls web.search and returns result string (lines 45-46)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_web_search("python asyncio"))
    assert result == "web result"


def test_tool_web_search_passes_query():
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

def test_tool_fetch_url_returns_result():
    """_tool_fetch_url calls web.fetch_url and returns result (lines 49-50)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_fetch_url("https://example.com"))
    assert result == "fetched content"


def test_tool_fetch_url_passes_url():
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

def test_tool_search_docs_single_word():
    """_tool_search_docs with single word uses it as lib and empty topic (lines 53-57)."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "result")

    agent.web.search_docs = _fake_search_docs
    asyncio.run(agent._tool_search_docs("fastapi"))
    assert captured == [("fastapi", "")]


def test_tool_search_docs_two_words():
    """_tool_search_docs splits arg into lib and topic."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "result")

    agent.web.search_docs = _fake_search_docs
    asyncio.run(agent._tool_search_docs("fastapi routing basics"))
    assert captured == [("fastapi", "routing basics")]


def test_tool_search_docs_returns_result():
    """_tool_search_docs returns the string result."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_search_docs("requests authentication"))
    assert result == "docs result"


def test_tool_search_docs_empty_arg():
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

def test_tool_docs_search_returns_result():
    """_tool_docs_search calls docs.search via asyncio.to_thread (lines 60-65)."""
    agent = _make_agent()
    result = asyncio.run(agent._tool_docs_search("vector search"))
    assert result == "doc result"


def test_tool_docs_search_uses_global_session():
    """_tool_docs_search always passes 'global' as session_id."""
    agent = _make_agent()
    captured = []

    def _fake_search(query, doc_id, mode, session_id):
        captured.append(session_id)
        return (True, "r")

    agent.docs.search = _fake_search
    asyncio.run(agent._tool_docs_search("query"))
    assert captured == ["global"]


def test_tool_docs_search_handles_awaitable_result():
    """_tool_docs_search awaits result_obj if it is awaitable (lines 62-63)."""
    agent = _make_agent()

    async def _async_search(query, doc_id, mode, session_id):
        return (True, "awaited result")

    agent.docs.search = _async_search
    result = asyncio.run(agent._tool_docs_search("query"))
    assert result == "awaited result"


# --- run_task ---

def test_run_task_empty_prompt_returns_warning():
    """run_task with empty string returns warning (line 69-70)."""
    agent = _make_agent()
    result = asyncio.run(agent.run_task(""))
    assert "[UYARI]" in result


def test_run_task_whitespace_only_returns_warning():
    """run_task with whitespace-only string returns warning."""
    agent = _make_agent()
    result = asyncio.run(agent.run_task("   "))
    assert "[UYARI]" in result


def test_run_task_fetch_url_prefix():
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


def test_run_task_fetch_url_prefix_case_insensitive():
    """run_task with FETCH_URL| prefix (upper case) also dispatches to fetch_url."""
    agent = _make_agent()
    captured = []

    async def _fake_fetch(url):
        captured.append(url)
        return (True, "fetched2")

    agent.web.fetch_url = _fake_fetch
    result = asyncio.run(agent.run_task("FETCH_URL|https://test.com"))
    assert result == "fetched2"


def test_run_task_search_docs_prefix():
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


def test_run_task_docs_search_prefix():
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


def test_run_task_default_uses_web_search():
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


def test_run_task_default_does_not_use_fetch_url():
    """run_task with plain text does NOT call fetch_url."""
    agent = _make_agent()
    fetch_called = []

    async def _fake_fetch(url):
        fetch_called.append(url)
        return (True, "x")

    agent.web.fetch_url = _fake_fetch
    asyncio.run(agent.run_task("search something"))
    assert fetch_called == []


def test_call_tool_unknown_tool_returns_error():
    """call_tool with unregistered name returns error message (from BaseAgent)."""
    agent = _make_agent()
    result = asyncio.run(agent.call_tool("nonexistent_tool", "arg"))
    assert "[HATA]" in result


def test_run_task_search_docs_uppercase_prefix():
    """run_task with SEARCH_DOCS| is case-insensitive (lower comparison)."""
    agent = _make_agent()
    captured = []

    async def _fake_search_docs(lib, topic):
        captured.append((lib, topic))
        return (True, "r")

    agent.web.search_docs = _fake_search_docs
    result = asyncio.run(agent.run_task("SEARCH_DOCS|numpy linalg"))
    assert result == "r"
