"""Unit tests for active agent registry behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.base_agent import BaseAgent
from agent.core.registry import ActiveAgentRegistry, AgentRegistry


def test_active_agent_registry_register_get_and_roles() -> None:
    registry = ActiveAgentRegistry()
    mock_agent = MagicMock(spec=BaseAgent)

    registry.register("test_role", mock_agent)

    assert registry.has("test_role") is True
    assert registry.get("test_role") is mock_agent
    assert registry.roles() == ("test_role",)


def test_active_agent_registry_get_missing_role_raises_keyerror() -> None:
    registry = ActiveAgentRegistry()

    with pytest.raises(KeyError, match="missing_role"):
        registry.get("missing_role")


def test_active_agent_registry_has_returns_false_for_unknown_role() -> None:
    registry = ActiveAgentRegistry()

    assert registry.has("non_existent") is False


def test_agent_registry_alias_points_to_active_registry() -> None:
    assert AgentRegistry is ActiveAgentRegistry
