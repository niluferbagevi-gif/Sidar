# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest
from agent.core.memory_hub import MemoryHub
from agent.core.registry import AgentRegistry


class DummyAgent:
    pass


def test_memory_hub_global_and_role_context_limits():
    hub = MemoryHub()
    for i in range(6):
        hub.add_global(f"g{i}")
    for i in range(4):
        hub.add_role_note("reviewer", f"r{i}")

    assert hub.global_context(limit=3) == ["g3", "g4", "g5"]
    assert hub.role_context("reviewer", limit=2) == ["r2", "r3"]


def test_agent_registry_register_get_and_roles():
    reg = AgentRegistry()
    agent = DummyAgent()

    reg.register("reviewer", agent)

    assert reg.has("reviewer") is True
    assert reg.has("coder") is False
    assert reg.get("reviewer") is agent

    roles = reg.roles()
    assert isinstance(roles, tuple)
    assert "reviewer" in roles
    assert len(roles) == 1

class _MinimalAgent(BaseAgent):
    async def run_task(self, task_prompt: str):
        return task_prompt


def test_base_agent_can_build_delegation_request():
    agent = _MinimalAgent(role_name="tester")
    msg = agent.delegate_to("reviewer", "review_code|x", reason="qa")
    assert isinstance(msg, DelegationRequest)
    assert msg.reply_to == "tester"
    assert msg.target_agent == "reviewer"