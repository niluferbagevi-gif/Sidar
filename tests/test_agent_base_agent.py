"""
agent/base_agent.py için birim testleri.
BaseAgent soyut sınıfı, tool dispatch, delegate_to ve handle metodlarını kapsar.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _stub_base_agent_deps():
    """BaseAgent'ın ihtiyaç duyduğu modülleri stub'lar."""
    # config stub
    cfg_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_MODEL = "qwen2.5-coder:7b"

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    # core.llm_client stub
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    llm_mod = sys.modules["core.llm_client"]
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value="LLM yanıtı")
    llm_mod.LLMClient = MagicMock(return_value=mock_llm)

    # agent.core.contracts stub
    for mod in ("agent", "agent.core", "agent.core.contracts"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    contracts = sys.modules["agent.core.contracts"]

    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class DelegationRequest:
        task_id: str
        reply_to: str
        target_agent: str
        payload: str
        intent: str = "mixed"
        parent_task_id: str = None
        handoff_depth: int = 0
        meta: dict = field(default_factory=dict)

        def bumped(self):
            return DelegationRequest(
                task_id=self.task_id,
                reply_to=self.reply_to,
                target_agent=self.target_agent,
                payload=self.payload,
                intent=self.intent,
                parent_task_id=self.parent_task_id,
                handoff_depth=self.handoff_depth + 1,
                meta=dict(self.meta),
            )

    @dataclass
    class TaskEnvelope:
        task_id: str
        sender: str
        receiver: str
        goal: str
        intent: str = "mixed"
        parent_task_id: str = None
        context: dict = field(default_factory=dict)
        inputs: list = field(default_factory=list)

    @dataclass
    class TaskResult:
        task_id: str
        status: str
        summary: Any
        evidence: list = field(default_factory=list)
        next_actions: list = field(default_factory=list)

    def is_delegation_request(value):
        return isinstance(value, DelegationRequest)

    contracts.DelegationRequest = DelegationRequest
    contracts.TaskEnvelope = TaskEnvelope
    contracts.TaskResult = TaskResult
    contracts.is_delegation_request = is_delegation_request

    return contracts


def _get_base_agent():
    _stub_base_agent_deps()
    for mod in list(sys.modules.keys()):
        if "agent.base_agent" in mod:
            del sys.modules[mod]
    import agent.base_agent as ba
    return ba


def _make_concrete_agent(ba, role_name="test"):
    """BaseAgent'tan somut bir alt sınıf üretir."""
    class ConcreteAgent(ba.BaseAgent):
        async def run_task(self, task_prompt: str):
            return f"görev tamamlandı: {task_prompt}"

    return ConcreteAgent(role_name=role_name)


class TestBaseAgentInit:
    def test_init_sets_role_name(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba, role_name="coder")
        assert agent.role_name == "coder"

    def test_init_creates_llm(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        assert agent.llm is not None

    def test_init_tools_empty(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        assert agent.tools == {}

    def test_init_with_none_cfg_uses_default(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        assert agent.cfg is not None


class TestBaseAgentTools:
    def test_register_tool(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)

        async def my_tool(arg: str) -> str:
            return f"result:{arg}"

        agent.register_tool("my_tool", my_tool)
        assert "my_tool" in agent.tools

    @pytest.mark.asyncio
    async def test_call_tool_registered(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)

        async def echo(arg: str) -> str:
            return f"echo:{arg}"

        agent.register_tool("echo", echo)
        result = await agent.call_tool("echo", "hello")
        assert result == "echo:hello"

    @pytest.mark.asyncio
    async def test_call_tool_unregistered_returns_error(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        result = await agent.call_tool("nonexistent", "arg")
        assert "HATA" in result or "hata" in result.lower()
        assert "nonexistent" in result


class TestBaseAgentCallLlm:
    @pytest.mark.asyncio
    async def test_call_llm_returns_string(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        result = await agent.call_llm([{"role": "user", "content": "merhaba"}])
        assert isinstance(result, str)


class TestBaseAgentDelegateTo:
    def test_delegate_to_creates_delegation_request(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba, role_name="coder")
        contracts = sys.modules["agent.core.contracts"]

        req = agent.delegate_to("reviewer", "kodu incele", task_id="t1", reason="kalite")
        assert isinstance(req, contracts.DelegationRequest)
        assert req.target_agent == "reviewer"
        assert req.payload == "kodu incele"
        assert req.reply_to == "coder"

    def test_delegate_to_sets_task_id(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba, role_name="qa")
        req = agent.delegate_to("coder", "payload", task_id="explicit-id")
        assert req.task_id == "explicit-id"

    def test_delegate_to_default_task_id(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba, role_name="qa")
        req = agent.delegate_to("coder", "payload")
        assert "qa" in req.task_id

    def test_is_delegation_message_true(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        req = agent.delegate_to("reviewer", "payload")
        assert ba.BaseAgent.is_delegation_message(req) is True

    def test_is_delegation_message_false_for_string(self):
        ba = _get_base_agent()
        assert ba.BaseAgent.is_delegation_message("just a string") is False


class TestBaseAgentHandle:
    @pytest.mark.asyncio
    async def test_handle_returns_task_result(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        contracts = sys.modules["agent.core.contracts"]

        envelope = contracts.TaskEnvelope(
            task_id="task-1",
            sender="swarm",
            receiver="test",
            goal="bir görev yap",
        )
        result = await agent.handle(envelope)
        assert isinstance(result, contracts.TaskResult)
        assert result.task_id == "task-1"
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_handle_summary_contains_goal(self):
        ba = _get_base_agent()
        agent = _make_concrete_agent(ba)
        contracts = sys.modules["agent.core.contracts"]

        envelope = contracts.TaskEnvelope(
            task_id="task-2",
            sender="s",
            receiver="r",
            goal="hedef görev",
        )
        result = await agent.handle(envelope)
        assert "hedef görev" in str(result.summary)
