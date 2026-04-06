from __future__ import annotations

import asyncio
import sys
import types

import pytest

sys.modules.setdefault("httpx", types.ModuleType("httpx"))

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope


class _DummyConfig:
    AI_PROVIDER = "dummy-provider"


class _FakeLLMClient:
    def __init__(self, provider, cfg):
        self.provider = provider
        self.cfg = cfg
        self.last_chat_kwargs = None

    async def chat(self, **kwargs):
        self.last_chat_kwargs = kwargs
        return {"ok": True, "messages": kwargs.get("messages", [])}


class _ConcreteAgent(BaseAgent):
    def __init__(self, cfg=None, *, role_name="concrete", result="done"):
        super().__init__(cfg=cfg, role_name=role_name)
        self.result = result
        self.last_prompt = None

    async def run_task(self, task_prompt: str):
        self.last_prompt = task_prompt
        return self.result


@pytest.fixture
def agent_with_fake_llm(monkeypatch):
    import agent.base_agent as base_agent_module

    monkeypatch.setattr(base_agent_module, "LLMClient", _FakeLLMClient)
    return _ConcreteAgent(cfg=_DummyConfig(), role_name="tester")


def test_register_and_call_tool_success_and_missing(agent_with_fake_llm):
    async def echo_tool(arg: str) -> str:
        return f"echo:{arg}"

    agent_with_fake_llm.register_tool("echo", echo_tool)

    ok = asyncio.run(agent_with_fake_llm.call_tool("echo", "selam"))
    missing = asyncio.run(agent_with_fake_llm.call_tool("none", "selam"))

    assert ok == "echo:selam"
    assert "tanımlı değil" in missing


def test_call_llm_uses_defaults_and_overrides(agent_with_fake_llm):
    messages = [{"role": "user", "content": "Merhaba"}]

    resp = asyncio.run(
        agent_with_fake_llm.call_llm(
            messages,
            system_prompt="custom",
            temperature=0.7,
            json_mode=True,
            model="x-model",
        )
    )

    assert "ok" in resp
    assert agent_with_fake_llm.llm.last_chat_kwargs == {
        "messages": messages,
        "model": "x-model",
        "system_prompt": "custom",
        "temperature": 0.7,
        "stream": False,
        "json_mode": True,
    }


def test_delegate_to_defaults_and_sanitization(agent_with_fake_llm):
    req = agent_with_fake_llm.delegate_to(
        "reviewer",
        "payload",
        handoff_depth=-4,
    )

    assert isinstance(req, DelegationRequest)
    assert req.task_id == "p2p-tester"
    assert req.reply_to == "tester"
    assert req.target_agent == "reviewer"
    assert req.parent_task_id is None
    assert req.handoff_depth == 0
    assert req.meta == {}


def test_delegate_to_full_fields(agent_with_fake_llm):
    req = agent_with_fake_llm.delegate_to(
        "qa",
        "payload-2",
        task_id="task-123",
        reason="needs qa",
        intent="quality",
        parent_task_id="parent-1",
        handoff_depth=3,
    )

    assert req.task_id == "task-123"
    assert req.intent == "quality"
    assert req.parent_task_id == "parent-1"
    assert req.handoff_depth == 3
    assert req.meta == {"reason": "needs qa"}
    assert agent_with_fake_llm.is_delegation_message(req) is True
    assert agent_with_fake_llm.is_delegation_message("raw") is False


def test_handle_returns_task_result_for_plain_summary(agent_with_fake_llm):
    envelope = TaskEnvelope(
        task_id="task-1",
        sender="sup",
        receiver="tester",
        goal="fix bug",
        parent_task_id="parent-x",
        context={"p2p_handoff_depth": "2"},
    )

    result = asyncio.run(agent_with_fake_llm.handle(envelope))

    assert result.task_id == "task-1"
    assert result.status == "success"
    assert result.summary == "done"
    assert result.evidence == []


def test_handle_updates_delegation_summary_metadata(monkeypatch):
    import agent.base_agent as base_agent_module

    monkeypatch.setattr(base_agent_module, "LLMClient", _FakeLLMClient)
    delegated = DelegationRequest(
        task_id="",
        reply_to="coder",
        target_agent="reviewer",
        payload="please review",
        parent_task_id=None,
        handoff_depth=1,
    )
    agent = _ConcreteAgent(cfg=_DummyConfig(), role_name="coder", result=delegated)

    envelope = TaskEnvelope(
        task_id="task-42",
        sender="supervisor",
        receiver="coder",
        goal="implement feature",
        parent_task_id="root-1",
        context={"p2p_handoff_depth": "5"},
    )

    result = asyncio.run(agent.handle(envelope))

    assert isinstance(result.summary, DelegationRequest)
    assert result.summary.task_id == "task-42"
    assert result.summary.parent_task_id == "root-1"
    assert result.summary.handoff_depth == 5
