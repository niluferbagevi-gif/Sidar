from __future__ import annotations

import asyncio
from types import SimpleNamespace
import sys
import types


if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object, Client=object)

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope


class _DummyLLM:
    async def chat(self, **kwargs):
        return {"ok": True, "payload": kwargs}


class _Agent(BaseAgent):
    async def run_task(self, task_prompt: str):
        if task_prompt.startswith("delegate"):
            return self.delegate_to("qa", "payload", task_id="", handoff_depth=-3)
        return f"done:{task_prompt}"


def test_call_tool_and_call_llm_paths(monkeypatch) -> None:
    monkeypatch.setattr("agent.base_agent.LLMClient", lambda *_args, **_kwargs: _DummyLLM())
    agent = _Agent(cfg=SimpleNamespace(AI_PROVIDER="ollama"), role_name="coder")

    async def _runner() -> None:
        async def _tool(arg: str) -> str:
            return f"ok:{arg}"

        agent.register_tool("echo", _tool)
        assert await agent.call_tool("echo", "x") == "ok:x"
        assert "tanımlı değil" in await agent.call_tool("missing", "x")

        text = await agent.call_llm([{"role": "user", "content": "hello"}], model="m")
        assert "payload" in text

    asyncio.run(_runner())


def test_handle_sets_task_fields_for_delegation(monkeypatch) -> None:
    monkeypatch.setattr("agent.base_agent.LLMClient", lambda *_args, **_kwargs: _DummyLLM())
    agent = _Agent(cfg=SimpleNamespace(AI_PROVIDER="ollama"), role_name="reviewer")
    envelope = TaskEnvelope(
        task_id="t-1",
        sender="supervisor",
        receiver="reviewer",
        goal="delegate now",
        context={"p2p_handoff_depth": "4"},
        parent_task_id="parent-1",
    )

    result = asyncio.run(agent.handle(envelope))

    assert isinstance(result.summary, DelegationRequest)
    assert result.summary.task_id == "p2p-reviewer"
    assert result.summary.parent_task_id == "parent-1"
    assert result.summary.handoff_depth == 4
    assert BaseAgent.is_delegation_message(result.summary) is True


def test_handle_non_delegation_success(monkeypatch) -> None:
    monkeypatch.setattr("agent.base_agent.LLMClient", lambda *_args, **_kwargs: _DummyLLM())
    agent = _Agent(cfg=SimpleNamespace(AI_PROVIDER="ollama"), role_name="researcher")

    envelope = TaskEnvelope(task_id="t-2", sender="supervisor", receiver="researcher", goal="plain", context={})
    result = asyncio.run(agent.handle(envelope))

    assert result.status == "success"
    assert result.summary == "done:plain"
    assert BaseAgent.is_delegation_message(result.summary) is False
