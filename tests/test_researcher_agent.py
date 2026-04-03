from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class Timeout:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = Timeout
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.AsyncClient = object
    fake_httpx.Request = object
    fake_httpx.Response = object
    sys.modules["httpx"] = fake_httpx

if not _has_module("bs4"):
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            return None

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

_module_path = Path(__file__).resolve().parents[1] / "agent" / "roles" / "researcher_agent.py"
_spec = importlib.util.spec_from_file_location("researcher_agent_direct", _module_path)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)
ResearcherAgent = _mod.ResearcherAgent


def _agent() -> ResearcherAgent:
    a = ResearcherAgent.__new__(ResearcherAgent)
    a.web = SimpleNamespace(
        search=lambda arg: asyncio.sleep(0, result=(True, f"SEARCH:{arg}"),),
        fetch_url=lambda arg: asyncio.sleep(0, result=(True, f"FETCH:{arg}"),),
        search_docs=lambda lib, topic: asyncio.sleep(0, result=(True, f"DOCS:{lib}:{topic}"),),
    )
    a.docs = SimpleNamespace(search=lambda *args, **kwargs: (True, "RAG:docs"))
    return a


def test_researcher_agent_tools_and_run_task_routes(monkeypatch) -> None:
    agent = _agent()

    async def _call_tool(name: str, arg: str):
        return f"TOOL:{name}:{arg}"

    monkeypatch.setattr(agent, "call_tool", _call_tool, raising=False)
    monkeypatch.setattr(asyncio, "to_thread", lambda fn, *args, **kwargs: asyncio.sleep(0, result=fn(*args, **kwargs)))

    assert asyncio.run(agent._tool_web_search("sidar")) == "SEARCH:sidar"
    assert asyncio.run(agent._tool_fetch_url("https://a")) == "FETCH:https://a"
    assert asyncio.run(agent._tool_search_docs("fastapi auth")) == "DOCS:fastapi:auth"
    assert asyncio.run(agent._tool_search_docs("onlylib")) == "DOCS:onlylib:"
    assert asyncio.run(agent._tool_docs_search("topic")) == "RAG:docs"

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş araştırma görevi verildi."
    assert asyncio.run(agent.run_task("fetch_url|https://x")) == "TOOL:fetch_url:https://x"
    assert asyncio.run(agent.run_task("search_docs|pkg use")) == "TOOL:search_docs:pkg use"
    assert asyncio.run(agent.run_task("docs_search|rag query")) == "TOOL:docs_search:rag query"
    assert asyncio.run(agent.run_task("plain query")) == "TOOL:web_search:plain query"


def test_researcher_agent_init_registers_tools_and_dependencies(monkeypatch) -> None:
    cfg = SimpleNamespace(
        RAG_DIR="/tmp/rag",
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=300,
        RAG_CHUNK_OVERLAP=25,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
    )
    observed: dict[str, object] = {}

    def _fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}

    class FakeWeb:
        def __init__(self, passed_cfg):
            observed["web_cfg"] = passed_cfg

    class FakeStore:
        def __init__(self, *args, **kwargs):
            observed["store_args"] = args
            observed["store_kwargs"] = kwargs

    monkeypatch.setattr(_mod.BaseAgent, "__init__", _fake_base_init)
    monkeypatch.setattr(_mod, "WebSearchManager", FakeWeb)
    monkeypatch.setattr(_mod, "DocumentStore", FakeStore)

    agent = ResearcherAgent(cfg)

    assert agent.role_name == "researcher"
    assert observed["web_cfg"] is cfg
    assert observed["store_args"][0] == Path(cfg.RAG_DIR)
    assert observed["store_kwargs"]["top_k"] == cfg.RAG_TOP_K
    assert observed["store_kwargs"]["chunk_size"] == cfg.RAG_CHUNK_SIZE
    assert observed["store_kwargs"]["chunk_overlap"] == cfg.RAG_CHUNK_OVERLAP
    assert observed["store_kwargs"]["use_gpu"] is cfg.USE_GPU
    assert observed["store_kwargs"]["gpu_device"] == cfg.GPU_DEVICE
    assert observed["store_kwargs"]["mixed_precision"] is cfg.GPU_MIXED_PRECISION
    assert observed["store_kwargs"]["cfg"] is cfg
    assert set(agent.tools) == {"web_search", "fetch_url", "search_docs", "docs_search"}


def test_researcher_agent_init_populates_tools_when_register_tool_is_noop(monkeypatch) -> None:
    cfg = SimpleNamespace(
        RAG_DIR="/tmp/rag",
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=300,
        RAG_CHUNK_OVERLAP=25,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
    )

    def _fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}

    class FakeWeb:
        def __init__(self, passed_cfg):
            self.cfg = passed_cfg

    class FakeStore:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    monkeypatch.setattr(_mod.BaseAgent, "__init__", _fake_base_init)
    monkeypatch.setattr(_mod.BaseAgent, "register_tool", lambda self, name, func: None)
    monkeypatch.setattr(_mod, "WebSearchManager", FakeWeb)
    monkeypatch.setattr(_mod, "DocumentStore", FakeStore)

    agent = ResearcherAgent(cfg)

    assert set(agent.tools) == {"web_search", "fetch_url", "search_docs", "docs_search"}
    assert callable(agent.tools["web_search"])
    assert callable(agent.tools["fetch_url"])
    assert callable(agent.tools["search_docs"])
    assert callable(agent.tools["docs_search"])


def test_tool_docs_search_accepts_awaitable_from_document_store(monkeypatch) -> None:
    agent = _agent()

    async def _awaitable_result():
        return True, "RAG:awaited"

    agent.docs = SimpleNamespace(search=lambda *args, **kwargs: _awaitable_result())
    monkeypatch.setattr(asyncio, "to_thread", lambda fn, *args, **kwargs: asyncio.sleep(0, result=fn(*args, **kwargs)))

    assert asyncio.run(agent._tool_docs_search("topic")) == "RAG:awaited"
