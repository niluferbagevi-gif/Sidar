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

    monkeypatch.setattr(agent, "call_tool", _call_tool)
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
