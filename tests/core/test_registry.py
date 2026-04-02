from __future__ import annotations

import sys
import types

import pytest

_base_agent_mod = types.ModuleType("agent.base_agent")
_base_agent_mod.BaseAgent = type("BaseAgent", (), {})
sys.modules.setdefault("agent.base_agent", _base_agent_mod)

from agent.core.registry import ActiveAgentRegistry, AgentRegistry


class _DummyAgent:
    pass


def test_registry_register_get_and_has() -> None:
    registry = ActiveAgentRegistry()
    agent = _DummyAgent()

    registry.register("qa", agent)

    assert registry.has("qa") is True
    assert registry.get("qa") is agent


def test_registry_roles_returns_registered_keys_in_insertion_order() -> None:
    registry = ActiveAgentRegistry()
    registry.register("reviewer", _DummyAgent())
    registry.register("coder", _DummyAgent())

    assert tuple(registry.roles()) == ("reviewer", "coder")


def test_registry_get_raises_helpful_error_for_missing_role() -> None:
    registry = ActiveAgentRegistry()
    registry.register("researcher", _DummyAgent())

    with pytest.raises(KeyError) as exc:
        registry.get("unknown")

    assert "unknown" in str(exc.value)
    assert "researcher" in str(exc.value)


def test_agent_registry_alias_points_to_active_registry() -> None:
    assert AgentRegistry is ActiveAgentRegistry
