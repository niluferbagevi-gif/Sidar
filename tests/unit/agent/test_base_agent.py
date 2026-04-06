import asyncio
import sys
import types

import pytest

# core.llm_client bağımlılıklarını (httpx vb.) testte izole etmek için sahte modül.
_fake_llm_module = types.ModuleType("core.llm_client")


class _StubLLMClient:
    def __init__(self, provider, _cfg):
        self.provider = provider
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return "llm-ok"


_fake_llm_module.LLMClient = _StubLLMClient
sys.modules.setdefault("core.llm_client", _fake_llm_module)

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope


class DummyAgent(BaseAgent):
    async def run_task(self, task_prompt: str):
        return f"done:{task_prompt}"


class DelegatingAgent(BaseAgent):
    async def run_task(self, task_prompt: str):
        return DelegationRequest(
            task_id="",
            reply_to=self.role_name,
            target_agent="reviewer",
            payload=task_prompt,
        )


@pytest.fixture
def patched_config(monkeypatch):
    class _DummyConfig:
        AI_PROVIDER = "test-provider"

    monkeypatch.setattr("agent.base_agent.Config", _DummyConfig)


def test_register_and_call_tool(patched_config):
    agent = DummyAgent(role_name="coder")

    async def _tool(arg: str) -> str:
        return f"echo:{arg}"

    agent.register_tool("echo", _tool)

    assert asyncio.run(agent.call_tool("echo", "x")) == "echo:x"
    assert "tanımlı değil" in asyncio.run(agent.call_tool("missing", "x"))


def test_call_llm_passes_expected_payload(patched_config):
    agent = DummyAgent(role_name="qa")

    result = asyncio.run(
        agent.call_llm(
            [{"role": "user", "content": "hello"}],
            system_prompt="sys",
            temperature=0.7,
            json_mode=True,
            model="test-model",
        )
    )

    assert result == "llm-ok"
    call = agent.llm.calls[0]
    assert call["messages"][0]["content"] == "hello"
    assert call["system_prompt"] == "sys"
    assert call["temperature"] == 0.7
    assert call["json_mode"] is True
    assert call["model"] == "test-model"


def test_delegate_to_and_is_delegation_message(patched_config):
    agent = DummyAgent(role_name="researcher")

    req = agent.delegate_to("reviewer", "please review", reason="qa", handoff_depth=-5)

    assert req.task_id == "p2p-researcher"
    assert req.reply_to == "researcher"
    assert req.target_agent == "reviewer"
    assert req.meta == {"reason": "qa"}
    assert req.handoff_depth == 0
    assert agent.is_delegation_message(req) is True
    assert agent.is_delegation_message("not-a-request") is False


def test_handle_wraps_normal_run_task_result(patched_config):
    agent = DummyAgent(role_name="coder")
    envelope = TaskEnvelope(task_id="t1", sender="supervisor", receiver="coder", goal="build", context={})

    result = asyncio.run(agent.handle(envelope))

    assert result.task_id == "t1"
    assert result.status == "success"
    assert result.summary == "done:build"


def test_handle_enriches_delegation_summary_with_envelope_values(patched_config):
    agent = DelegatingAgent(role_name="coder")
    envelope = TaskEnvelope(
        task_id="t-parent",
        sender="supervisor",
        receiver="coder",
        parent_task_id="root-1",
        goal="handoff",
        context={"p2p_handoff_depth": "3"},
    )

    result = asyncio.run(agent.handle(envelope))
    summary = result.summary

    assert isinstance(summary, DelegationRequest)
    assert summary.task_id == "t-parent"
    assert summary.parent_task_id == "root-1"
    assert summary.handoff_depth == 3
