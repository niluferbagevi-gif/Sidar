"""
agent/core/registry.py için birim testleri.
AgentRegistry (inner core): register, get, has, roles, KeyError.
BaseAgent stub ile izole çalışır.
"""
from __future__ import annotations

import sys
import types

import pytest


def _get_core_registry():
    # Stub agent.base_agent so we don't need Config/LLMClient
    if "agent.base_agent" not in sys.modules:
        stub = types.ModuleType("agent.base_agent")

        class _BaseAgent:
            pass

        stub.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = stub

    if "agent.core.registry" in sys.modules:
        del sys.modules["agent.core.registry"]
    import agent.core.registry as cr
    return cr


# ══════════════════════════════════════════════════════════════
# AgentRegistry (core)
# ══════════════════════════════════════════════════════════════

class TestCoreAgentRegistry:
    def _make(self):
        cr = _get_core_registry()
        return cr.AgentRegistry()

    def test_register_and_get(self):
        cr = _get_core_registry()
        registry = self._make()

        class _FakeAgent(cr._BaseAgent if hasattr(cr, "_BaseAgent") else object):
            pass

        registry.register("myagent", _FakeAgent())
        agent = registry.get("myagent")
        assert agent is not None

    def test_get_missing_raises_key_error(self):
        registry = self._make()
        with pytest.raises(KeyError, match="missing"):
            registry.get("missing")

    def test_has_registered_role(self):
        cr = _get_core_registry()
        registry = self._make()

        class _FakeAgent:
            pass

        registry.register("r1", _FakeAgent())
        assert registry.has("r1") is True

    def test_has_missing_role(self):
        registry = self._make()
        assert registry.has("__nonexistent__") is False

    def test_roles_returns_registered(self):
        cr = _get_core_registry()
        registry = self._make()

        class _FakeAgent:
            pass

        registry.register("role_a", _FakeAgent())
        registry.register("role_b", _FakeAgent())
        roles = tuple(registry.roles())
        assert "role_a" in roles
        assert "role_b" in roles

    def test_error_message_lists_available_roles(self):
        cr = _get_core_registry()
        registry = self._make()

        class _FakeAgent:
            pass

        registry.register("known_role", _FakeAgent())
        with pytest.raises(KeyError) as exc_info:
            registry.get("unknown_role")
        assert "known_role" in str(exc_info.value)
