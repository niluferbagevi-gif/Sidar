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
    assert reg.get("reviewer") is agent
    assert "reviewer" in reg.roles()
