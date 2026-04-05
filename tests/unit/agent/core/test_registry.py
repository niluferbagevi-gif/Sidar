"""Unit tests for active agent registry behavior."""

from __future__ import annotations

import importlib
import sys
import types

import pytest


class _StubBaseAgent:  # pragma: no cover - helper only
    pass


def _load_registry_module(monkeypatch: pytest.MonkeyPatch):
    """Load agent.core.registry with a lightweight BaseAgent stub."""
    base_agent_module = types.ModuleType("agent.base_agent")
    base_agent_module.BaseAgent = _StubBaseAgent

    monkeypatch.setitem(sys.modules, "agent.base_agent", base_agent_module)
    sys.modules.pop("agent.core.registry", None)

    return importlib.import_module("agent.core.registry")


def test_active_agent_registry_register_get_and_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_registry_module(monkeypatch)
    registry = module.ActiveAgentRegistry()
    mock_agent = object()

    registry.register("test_role", mock_agent)

    assert registry.has("test_role") is True
    assert registry.get("test_role") is mock_agent
    assert registry.roles() == ("test_role",)


def test_active_agent_registry_get_missing_role_raises_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_registry_module(monkeypatch)
    registry = module.ActiveAgentRegistry()

    with pytest.raises(KeyError, match="missing_role"):
        registry.get("missing_role")


def test_active_agent_registry_has_returns_false_for_unknown_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_registry_module(monkeypatch)
    registry = module.ActiveAgentRegistry()

    assert registry.has("non_existent") is False
