import asyncio
import importlib.util
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

    def register_tool(self, name, func):
        self.tools[name] = func

    async def call_tool(self, name, arg):
        if name not in self.tools:
            return f"[HATA] '{name}' aracı bu ajan için tanımlı değil."
        return await self.tools[name](arg)


class _StubAgentCatalog:
    @classmethod
    def register(cls, **_kwargs):
        def _decorator(agent_cls):
            return agent_cls

        return _decorator


def test_stub_base_agent_call_tool_returns_error_for_unknown_tool():
    agent = _StubBaseAgent()
    result = asyncio.run(agent.call_tool("unknown_tool", "payload"))
    assert result.startswith("[HATA]")


class DummyWebSearchManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.search_calls = []
        self.fetch_calls = []
        self.search_docs_calls = []

    async def search(self, arg: str):
        self.search_calls.append(arg)
        return True, f"web:{arg}"

    async def fetch_url(self, arg: str):
        self.fetch_calls.append(arg)
        return True, f"fetch:{arg}"

    async def search_docs(self, lib: str, topic: str):
        self.search_docs_calls.append((lib, topic))
        return True, f"docs:{lib}:{topic}"


class SyncDocStore:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls = []

    def search(self, query: str, _filters, mode: str, session_id: str):
        self.calls.append((query, mode, session_id))
        return True, f"sync:{query}:{mode}:{session_id}"


class AsyncLikeDocStore:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def search(self, query: str, _filters, mode: str, session_id: str):
        self.calls.append((query, mode, session_id))

        async def _inner():
            return True, f"async:{query}:{mode}:{session_id}"

        return _inner()


class ErrorDocStore:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def search(self, query: str, _filters, mode: str, session_id: str):
        self.calls.append((query, mode, session_id))
        raise RuntimeError("storage backend unavailable")


@pytest.fixture
def researcher_module(monkeypatch: pytest.MonkeyPatch):
    config_mod = types.ModuleType("config")
    config_mod.Config = object
    core_rag_mod = types.ModuleType("core.rag")
    core_rag_mod.DocumentStore = SyncDocStore
    web_search_mod = types.ModuleType("managers.web_search")
    web_search_mod.WebSearchManager = DummyWebSearchManager
    base_agent_mod = types.ModuleType("agent.base_agent")
    base_agent_mod.BaseAgent = _StubBaseAgent
    registry_mod = types.ModuleType("agent.registry")
    registry_mod.AgentCatalog = _StubAgentCatalog

    monkeypatch.setitem(sys.modules, "config", config_mod)
    monkeypatch.setitem(sys.modules, "core.rag", core_rag_mod)
    monkeypatch.setitem(sys.modules, "managers.web_search", web_search_mod)
    monkeypatch.setitem(sys.modules, "agent.base_agent", base_agent_mod)
    monkeypatch.setitem(sys.modules, "agent.registry", registry_mod)

    file_path = Path(__file__).resolve().parents[4] / "agent" / "roles" / "researcher_agent.py"
    spec = importlib.util.spec_from_file_location("researcher_under_test", file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
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
    )


def _build_agent(researcher_module, fake_cfg, docstore_cls=SyncDocStore):
    researcher_module.WebSearchManager = DummyWebSearchManager
    researcher_module.DocumentStore = docstore_cls
    return researcher_module.ResearcherAgent(fake_cfg)


def test_init_registers_all_tools(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg)

    assert agent.role_name == "researcher"
    assert set(agent.tools) == {"web_search", "fetch_url", "search_docs", "docs_search"}


def test_web_and_fetch_tools(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg)

    web_result = asyncio.run(agent._tool_web_search("python"))
    fetch_result = asyncio.run(agent._tool_fetch_url("https://example.com"))

    assert web_result == "web:python"
    assert fetch_result == "fetch:https://example.com"
    assert agent.web.search_calls == ["python"]
    assert agent.web.fetch_calls == ["https://example.com"]


def test_search_docs_tool_parses_library_and_topic(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg)

    with_topic = asyncio.run(agent._tool_search_docs("numpy indexing"))
    only_lib = asyncio.run(agent._tool_search_docs("pandas"))

    assert with_topic == "docs:numpy:indexing"
    assert only_lib == "docs:pandas:"
    assert agent.web.search_docs_calls == [("numpy", "indexing"), ("pandas", "")]


def test_docs_search_tool_handles_sync_result(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg, docstore_cls=SyncDocStore)

    result = asyncio.run(agent._tool_docs_search("vector db"))

    assert result == "sync:vector db:auto:global"
    assert agent.docs.calls == [("vector db", "auto", "global")]


def test_docs_search_tool_handles_awaitable_result(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg, docstore_cls=AsyncLikeDocStore)

    result = asyncio.run(agent._tool_docs_search("embeddings"))

    assert result == "async:embeddings:auto:global"
    assert agent.docs.calls == [("embeddings", "auto", "global")]


def test_docs_search_tool_returns_timeout_message_on_timeout_error(
    researcher_module, fake_cfg, monkeypatch
):
    agent = _build_agent(researcher_module, fake_cfg, docstore_cls=SyncDocStore)

    async def raise_timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(researcher_module.asyncio, "to_thread", raise_timeout)

    result = asyncio.run(agent._tool_docs_search("timeouts are handled"))

    assert result == "Doküman araması zaman aşımına uğradı."


def test_docs_search_tool_returns_unavailable_message_on_unexpected_error(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg, docstore_cls=ErrorDocStore)

    result = asyncio.run(agent._tool_docs_search("unexpected errors are handled"))

    assert result == "Doküman araması şu anda kullanılamıyor: storage backend unavailable"
    assert agent.docs.calls == [("unexpected errors are handled", "auto", "global")]


def test_run_task_routing(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg)

    empty = asyncio.run(agent.run_task("   "))
    fetch = asyncio.run(agent.run_task("fetch_url| https://site.test"))
    docs = asyncio.run(agent.run_task("search_docs| scipy optimize"))
    rag = asyncio.run(agent.run_task("docs_search|faiss"))
    default = asyncio.run(agent.run_task("latest ai papers"))

    assert empty == "[UYARI] Boş araştırma görevi verildi."
    assert fetch == "fetch:https://site.test"
    assert docs == "docs:scipy:optimize"
    assert rag == "sync:faiss:auto:global"
    assert default == "web:latest ai papers"


def test_init_fallback_populates_tools_when_register_tool_is_noop(researcher_module, fake_cfg):
    researcher_module.WebSearchManager = DummyWebSearchManager
    researcher_module.DocumentStore = SyncDocStore

    def noop_register_tool(self, _name, _func):
        return None

    researcher_module.BaseAgent.register_tool = noop_register_tool

    agent = researcher_module.ResearcherAgent(fake_cfg)

    assert set(agent.tools) == {"web_search", "fetch_url", "search_docs", "docs_search"}


def test_run_task_falls_back_to_web_search_when_llm_returns_invalid_json(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg)

    async def fake_call_llm(**_kwargs):
        return "not-json"

    agent.call_llm = fake_call_llm

    result = asyncio.run(agent.run_task("state of python packaging"))

    assert result == "web:state of python packaging"


def test_run_task_falls_back_when_llm_selects_unknown_tool(researcher_module, fake_cfg):
    agent = _build_agent(researcher_module, fake_cfg)

    async def fake_call_llm(**_kwargs):
        return '{"tool":"unknown_tool","argument":"x"}'

    agent.call_llm = fake_call_llm

    result = asyncio.run(agent.run_task("mlops trendleri"))

    assert result == "web:mlops trendleri"


def test_run_task_falls_back_to_web_search_when_llm_hits_token_limit_error(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg)

    async def fake_call_llm(**_kwargs):
        raise RuntimeError("token limit exceeded while planning tool call")

    agent.call_llm = fake_call_llm

    result = asyncio.run(agent.run_task("uzun araştırma özeti hazırla"))

    assert result == "web:uzun araştırma özeti hazırla"


def test_run_task_after_four_llm_tool_iterations_falls_back_with_latest_prompt(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg)

    async def fake_call_llm(**_kwargs):
        return '{"tool":"web_search","argument":"iter-next"}'

    call_tool_spy = []

    async def fake_call_tool(name, arg):
        call_tool_spy.append((name, arg))
        if name == "web_search":
            return f"web:{arg}"
        return "unexpected"

    agent.call_llm = fake_call_llm
    agent.call_tool = fake_call_tool

    result = asyncio.run(agent.run_task("initial prompt"))
    unexpected = asyncio.run(fake_call_tool("fetch_url", "ignored"))

    assert result == "web:web:iter-next"
    assert unexpected == "unexpected"
    assert call_tool_spy == [
        ("web_search", "iter-next"),
        ("web_search", "iter-next"),
        ("web_search", "iter-next"),
        ("web_search", "iter-next"),
        ("web_search", "web:iter-next"),
        ("fetch_url", "ignored"),
    ]


def test_run_task_conflicting_llm_directions_use_latest_tool_output_as_fallback(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg)
    llm_payloads = iter(
        [
            '{"tool":"docs_search","argument":"first query"}',
            '{"tool":"unknown_tool","argument":"conflict"}',
        ]
    )

    async def fake_call_llm(**_kwargs):
        return next(llm_payloads)

    agent.call_llm = fake_call_llm

    result = asyncio.run(agent.run_task("başlangıç görevi"))

    assert result == "web:sync:first query:auto:global"


def test_run_task_returns_llm_final_answer_content_when_tool_is_final_answer(
    researcher_module, fake_cfg
):
    agent = _build_agent(researcher_module, fake_cfg)

    async def fake_call_llm(**_kwargs):
        return '{"tool":"final_answer","content":"özet: tamamlandı"}'

    agent.call_llm = fake_call_llm

    result = asyncio.run(agent.run_task("bir özet üret"))

    assert result == "özet: tamamlandı"
