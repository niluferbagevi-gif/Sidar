from unittest.mock import AsyncMock

import pytest

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope


pytestmark = pytest.mark.asyncio


class DummyLLMClient:
    def __init__(self, provider, cfg):
        self.provider = provider
        self.cfg = cfg
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs.get("messages", ["empty"])[0]


async def _tool_echo(arg: str) -> str:
    return f"echo:{arg}"


class DummyAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        self.next_result = "ok"
        super().__init__(*args, **kwargs)

    async def run_task(self, task_prompt: str):
        return self.next_result


def _make_dummy_agent(mock_config, monkeypatch: pytest.MonkeyPatch, role_name: str = "base") -> DummyAgent:
    cfg = mock_config(AI_PROVIDER="dummy-provider")
    monkeypatch.setattr("agent.base_agent.LLMClient", DummyLLMClient)
    return DummyAgent(cfg=cfg, role_name=role_name)


async def test_init_register_and_call_tool(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="qa")

    assert agent.cfg.AI_PROVIDER == "dummy-provider"
    assert agent.role_name == "qa"
    assert agent.llm.provider == "dummy-provider"

    missing = await agent.call_tool("unknown", "x")
    assert "tanımlı değil" in missing

    agent.register_tool("echo", _tool_echo)
    result = await agent.call_tool("echo", "hello")
    assert result == "echo:hello"


async def test_call_llm_uses_default_and_override_prompt(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="coder")
    monkeypatch.setattr(agent.llm, "chat", AsyncMock(side_effect=agent.llm.chat))

    response_default = await agent.call_llm(messages=["msg-1"])
    assert response_default == "msg-1"
    first_call = agent.llm.calls[0]
    assert first_call["system_prompt"] == agent.SYSTEM_PROMPT
    assert first_call["temperature"] == 0.3
    assert first_call["stream"] is False
    assert first_call["json_mode"] is False

    response_override = await agent.call_llm(
        messages=["msg-2"],
        system_prompt="custom",
        temperature=0.9,
        json_mode=True,
        model="gpt-test",
    )
    assert response_override == "msg-2"
    second_call = agent.llm.calls[1]
    assert second_call["system_prompt"] == "custom"
    assert second_call["temperature"] == 0.9
    assert second_call["json_mode"] is True
    assert second_call["model"] == "gpt-test"


async def test_delegate_to_and_is_delegation_message(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="reviewer")

    delegated = agent.delegate_to(
        target_agent="qa",
        payload="run tests",
        task_id="",
        reason="",
        parent_task_id="",
        handoff_depth=-8,
    )
    assert delegated.task_id == "p2p-reviewer"
    assert delegated.meta == {}
    assert delegated.parent_task_id is None
    assert delegated.handoff_depth == 0

    delegated_with_reason = agent.delegate_to(
        target_agent="coder",
        payload="fix bug",
        task_id="t-1",
        reason="needs patch",
        intent="code",
        parent_task_id="p-1",
        handoff_depth=2,
    )
    assert delegated_with_reason.task_id == "t-1"
    assert delegated_with_reason.meta == {"reason": "needs patch"}
    assert delegated_with_reason.parent_task_id == "p-1"
    assert delegated_with_reason.intent == "code"

    assert agent.is_delegation_message(delegated_with_reason) is True
    assert agent.is_delegation_message("not-a-delegation") is False


async def test_handle_returns_task_result_for_plain_summary(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="researcher")
    agent.next_result = "plain-summary"

    envelope = TaskEnvelope(
        task_id="task-11",
        sender="sup",
        receiver="researcher",
        goal="collect context",
    )

    result = await agent.handle(envelope)

    assert result.task_id == "task-11"
    assert result.status == "success"
    assert result.summary == "plain-summary"
    assert result.evidence == []


async def test_handle_enriches_delegation_defaults_from_envelope(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="coder")
    agent.next_result = DelegationRequest(
        task_id="",
        reply_to="coder",
        target_agent="qa",
        payload="validate",
        handoff_depth=1,
    )

    envelope = TaskEnvelope(
        task_id="task-22",
        sender="sup",
        receiver="coder",
        goal="validate",
        parent_task_id="parent-22",
        context={"p2p_handoff_depth": "3"},
    )

    result = await agent.handle(envelope)
    summary = result.summary

    assert isinstance(summary, DelegationRequest)
    assert summary.task_id == "task-22"
    assert summary.parent_task_id == "parent-22"
    assert summary.handoff_depth == 3


async def test_handle_preserves_existing_delegation_ids_and_depth(mock_config, monkeypatch: pytest.MonkeyPatch):
    agent = _make_dummy_agent(mock_config, monkeypatch, role_name="coder")
    agent.next_result = DelegationRequest(
        task_id="existing-task",
        reply_to="coder",
        target_agent="qa",
        payload="validate",
        parent_task_id="existing-parent",
        handoff_depth=7,
    )

    envelope = TaskEnvelope(
        task_id="task-99",
        sender="sup",
        receiver="coder",
        goal="validate",
        parent_task_id="parent-99",
        context={"p2p_handoff_depth": "2"},
    )

    result = await agent.handle(envelope)
    summary = result.summary

    assert isinstance(summary, DelegationRequest)
    assert summary.task_id == "existing-task"
    assert summary.parent_task_id == "existing-parent"
    assert summary.handoff_depth == 7
