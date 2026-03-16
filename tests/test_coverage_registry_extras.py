"""
Coverage tests for:
  - agent/registry.py: lines 66-77, 112, 120, 130-131, 143, 159-160, 171-172, 183-184
  - agent/core/registry.py: line 21 (KeyError on missing role)
"""
from __future__ import annotations

import pytest

from agent.registry import AgentRegistry, AgentSpec


# ── helper base class ─────────────────────────────────────────────────────────

class _FakeBase:
    pass


# ── register decorator (lines 66-77) ─────────────────────────────────────────

def test_register_decorator_uses_role_name_attribute():
    """Lines 66-77: @register reads ROLE_NAME from class if present."""

    @AgentRegistry.register(capabilities=["test_cap"], description="Test agent", version="2.0.0", is_builtin=False)
    class _DecoratedAgent(_FakeBase):
        ROLE_NAME = "decorated_test_agent"

    try:
        spec = AgentRegistry.get("decorated_test_agent")
        assert spec is not None
        assert spec.role_name == "decorated_test_agent"
        assert "test_cap" in spec.capabilities
        assert spec.version == "2.0.0"
        assert spec.is_builtin is False
    finally:
        AgentRegistry.unregister("decorated_test_agent")


def test_register_decorator_derives_role_from_class_name():
    """Lines 66-67: when ROLE_NAME not set, role is derived from class name."""

    @AgentRegistry.register(capabilities=[])
    class _SomeTestAgent(_FakeBase):
        pass  # no ROLE_NAME

    # role = "_sometestagent".lower().replace("agent", "") = "_sometest"
    derived_role = _SomeTestAgent.__name__.lower().replace("agent", "")
    try:
        spec = AgentRegistry.get(derived_role)
        assert spec is not None
    finally:
        AgentRegistry.unregister(derived_role)


def test_register_decorator_returns_class():
    """Decorator returns the original class unchanged."""

    @AgentRegistry.register(capabilities=[])
    class _ReturnTestAgent(_FakeBase):
        ROLE_NAME = "return_test_agent_xyz"

    try:
        assert _ReturnTestAgent.ROLE_NAME == "return_test_agent_xyz"
    finally:
        AgentRegistry.unregister("return_test_agent_xyz")


def test_register_decorator_uses_docstring_as_description():
    """Line 72: description falls back to class docstring first line."""

    @AgentRegistry.register(capabilities=[])
    class _DocAgent(_FakeBase):
        """This is the docstring description."""
        ROLE_NAME = "doc_agent_xyz"

    try:
        spec = AgentRegistry.get("doc_agent_xyz")
        assert "docstring" in spec.description
    finally:
        AgentRegistry.unregister("doc_agent_xyz")


# ── find_by_capability (line 112) ─────────────────────────────────────────────

def test_find_by_capability_returns_matching_specs():
    """Line 112: find_by_capability filters by capability."""
    AgentRegistry.register_type(
        role_name="cap_agent_a",
        agent_class=_FakeBase,
        capabilities=["unique_cap_xyz"],
    )
    AgentRegistry.register_type(
        role_name="cap_agent_b",
        agent_class=_FakeBase,
        capabilities=["other_cap"],
    )
    try:
        results = AgentRegistry.find_by_capability("unique_cap_xyz")
        roles = [s.role_name for s in results]
        assert "cap_agent_a" in roles
        assert "cap_agent_b" not in roles
    finally:
        AgentRegistry.unregister("cap_agent_a")
        AgentRegistry.unregister("cap_agent_b")


def test_find_by_capability_returns_empty_for_unknown():
    results = AgentRegistry.find_by_capability("__totally_unknown_cap__")
    assert results == []


# ── list_all (line 120) ────────────────────────────────────────────────────────

def test_list_all_returns_list():
    """Line 120: list_all returns a list."""
    result = AgentRegistry.list_all()
    assert isinstance(result, list)


# ── create (lines 130-131) ────────────────────────────────────────────────────

def test_create_raises_keyerror_for_missing_role():
    """Lines 130-131: create raises KeyError if role not registered."""
    with pytest.raises(KeyError) as exc_info:
        AgentRegistry.create("__nonexistent_role__")
    assert "__nonexistent_role__" in str(exc_info.value)


def test_create_succeeds_for_registered_role():
    """create() instantiates the registered class."""

    class _SimpleAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    AgentRegistry.register_type(
        role_name="create_test_agent",
        agent_class=_SimpleAgent,
        capabilities=[],
    )
    try:
        instance = AgentRegistry.create("create_test_agent", cfg=None)
        assert isinstance(instance, _SimpleAgent)
    finally:
        AgentRegistry.unregister("create_test_agent")


# ── unregister (line 143) ─────────────────────────────────────────────────────

def test_unregister_returns_false_for_missing():
    """Line 143: unregister returns False if role not found."""
    result = AgentRegistry.unregister("__not_registered__")
    assert result is False


def test_unregister_returns_true_and_removes():
    AgentRegistry.register_type(
        role_name="unreg_test",
        agent_class=_FakeBase,
        capabilities=[],
    )
    result = AgentRegistry.unregister("unreg_test")
    assert result is True
    assert AgentRegistry.get("unreg_test") is None


# ── _register_builtin_agents (lines 159-160, 171-172, 183-184) ───────────────

def test_builtin_agents_registration_survives_import_error():
    """Lines 159-160, 171-172, 183-184: ImportError in builtin registration is swallowed."""
    import sys
    from unittest.mock import patch

    # Simulate all three agent imports failing
    with patch.dict(sys.modules, {
        "agent.roles.coder_agent": None,
        "agent.roles.researcher_agent": None,
        "agent.roles.reviewer_agent": None,
    }):
        # Re-running _register_builtin_agents should not raise
        from agent.registry import _register_builtin_agents
        _register_builtin_agents()


# ── agent/core/registry.py — line 21: KeyError for missing role ───────────────

def test_core_registry_get_raises_for_missing_role():
    """agent/core/registry.py line 21: get() raises KeyError for missing role."""
    from agent.core.registry import AgentRegistry as CoreRegistry

    reg = CoreRegistry()
    with pytest.raises(KeyError) as exc_info:
        reg.get("nonexistent_role")
    assert "nonexistent_role" in str(exc_info.value)


def test_core_registry_has_and_register():
    """agent/core/registry.py: register, has, roles, get basic paths."""
    from agent.core.registry import AgentRegistry as CoreRegistry

    reg = CoreRegistry()
    assert not reg.has("myrole")

    fake_agent = object()
    reg.register("myrole", fake_agent)
    assert reg.has("myrole")
    assert reg.get("myrole") is fake_agent
    assert "myrole" in reg.roles()
