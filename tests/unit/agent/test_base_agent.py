from __future__ import annotations

import pytest

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope


class _FakeLLMClient:
    def __init__(self, provider: str, cfg: object) -> None:
        self.provider = provider
        self.cfg = cfg
        self.calls: list[dict[str, object]] = []

    async def chat(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {"ok": True, "payload": kwargs.get("messages")}


class _DummyAgent(BaseAgent):
    ROLE_NAME = "dummy"

    def __init__(self, *args, result: object = "done", **kwargs) -> None:
        super().__init__(*args, role_name=self.ROLE_NAME, **kwargs)
        self._result = result

    async def run_task(self, task_prompt: str):
        return self._result


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> _DummyAgent:
    monkeypatch.setattr("agent.base_agent.LLMClient", _FakeLLMClient)
    return _DummyAgent()


@pytest.mark.asyncio
async def test_register_tool_and_call_tool(agent: _DummyAgent) -> None:
    async def _tool(value: str) -> str:
        return value.upper()

    agent.register_tool("upper", _tool)
    assert await agent.call_tool("upper", "merhaba") == "MERHABA"


@pytest.mark.asyncio
async def test_call_tool_returns_error_for_unknown_tool(agent: _DummyAgent) -> None:
    result = await agent.call_tool("missing", "arg")
    assert "tanımlı değil" in result


@pytest.mark.asyncio
async def test_call_llm_uses_prompt_and_json_mode(agent: _DummyAgent) -> None:
    response = await agent.call_llm(
        [{"role": "user", "content": "selam"}],
        system_prompt="specialist",
        temperature=0.7,
        json_mode=True,
        model="gpt-test",
    )

    assert "ok" in response
    call = agent.llm.calls[-1]
    assert call["system_prompt"] == "specialist"
    assert call["temperature"] == 0.7
    assert call["json_mode"] is True
    assert call["model"] == "gpt-test"


def test_delegate_to_builds_safe_payload(agent: _DummyAgent) -> None:
    req = agent.delegate_to(
        "reviewer",
        "payload",
        reason="quality",
        handoff_depth=-3,
    )

    assert isinstance(req, DelegationRequest)
    assert req.task_id == "p2p-dummy"
    assert req.meta == {"reason": "quality"}
    assert req.handoff_depth == 0


@pytest.mark.asyncio
async def test_handle_wraps_plain_run_task_result(agent: _DummyAgent) -> None:
    envelope = TaskEnvelope(task_id="t1", sender="sup", receiver="dummy", goal="do")
    result = await agent.handle(envelope)

    assert result.task_id == "t1"
    assert result.status == "success"
    assert result.summary == "done"


@pytest.mark.asyncio
async def test_handle_updates_delegation_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.base_agent.LLMClient", _FakeLLMClient)
    delegation = DelegationRequest(
        task_id="",
        reply_to="dummy",
        target_agent="qa",
        payload="check",
        parent_task_id=None,
        handoff_depth=0,
    )
    agent = _DummyAgent(result=delegation)
    envelope = TaskEnvelope(
        task_id="root-1",
        sender="sup",
        receiver="dummy",
        goal="delegate",
        parent_task_id="parent-1",
        context={"p2p_handoff_depth": "3"},
    )

    result = await agent.handle(envelope)
    assert isinstance(result.summary, DelegationRequest)
    assert result.summary.task_id == "root-1"
    assert result.summary.parent_task_id == "parent-1"
    assert result.summary.handoff_depth == 3


def test_is_delegation_message(agent: _DummyAgent) -> None:
    msg = agent.delegate_to("qa", "payload", task_id="t2")
    assert agent.is_delegation_message(msg) is True
    assert agent.is_delegation_message("not-delegation") is False


def test_delegate_to_defaults_parent_task_id_to_none(agent: _DummyAgent) -> None:
    req = agent.delegate_to("reviewer", "payload", task_id="t3")
    assert req.parent_task_id is None


@pytest.mark.asyncio
async def test_handle_fills_parent_task_id_with_envelope_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.base_agent.LLMClient", _FakeLLMClient)
    delegation = DelegationRequest(
        task_id="",
        reply_to="dummy",
        target_agent="qa",
        payload="check",
        parent_task_id=None,
        handoff_depth=1,
    )
    agent = _DummyAgent(result=delegation)
    envelope = TaskEnvelope(task_id="root-2", sender="sup", receiver="dummy", goal="delegate")

    result = await agent.handle(envelope)
    assert isinstance(result.summary, DelegationRequest)
    assert result.summary.task_id == "root-2"
    assert result.summary.parent_task_id == "root-2"
    assert result.summary.handoff_depth == 1
