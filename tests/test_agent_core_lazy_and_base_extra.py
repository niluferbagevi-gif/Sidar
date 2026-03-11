import importlib

import pytest

import agent.core as agent_core
from agent.base_agent import BaseAgent
from agent.core.memory_hub import MemoryHub


class _MiniAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return task_prompt


@pytest.mark.asyncio
async def test_base_agent_tool_dispatch_and_delegation_helpers():
    agent = _MiniAgent(role_name="mini")

    async def _echo(arg: str) -> str:
        return f"ok:{arg}"

    agent.register_tool("echo", _echo)
    assert await agent.call_tool("echo", "x") == "ok:x"
    assert "tanımlı değil" in await agent.call_tool("missing", "x")

    req = agent.delegate_to("reviewer", "payload")
    assert req.task_id == "p2p-mini"
    assert _MiniAgent.is_delegation_message(req) is True
    assert _MiniAgent.is_delegation_message("not-delegation") is False


def test_agent_core_lazy_getattr_exports_and_error_paths():
    core = importlib.reload(agent_core)

    assert core.MemoryHub.__name__ == "MemoryHub"
    assert core.AgentRegistry.__name__ == "AgentRegistry"
    assert core.SupervisorAgent.__name__ == "SupervisorAgent"

    with pytest.raises(AttributeError):
        getattr(core, "NotExisting")


@pytest.mark.asyncio
async def test_memory_hub_empty_branches_and_async_helpers():
    hub = MemoryHub()

    hub.add_global("")
    assert hub.global_context() == []

    hub.add_role_note("coder", "")
    assert hub.role_context("coder") == []

    await hub.aadd_global("g1")
    await hub.aadd_role_note("coder", "n1")
    assert await hub.aglobal_context(limit=1) == ["g1"]
    assert await hub.arole_context("coder", limit=1) == ["n1"]
    assert hub.role_context("unknown") == []