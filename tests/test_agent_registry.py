"""
agent/registry.py için birim testleri.
AgentSpec dataclass, AgentRegistry: register_type, get, find_by_capability,
list_all, create, unregister, @register dekoratör.
"""
from __future__ import annotations

import pytest


def _get_reg():
    import agent.registry as reg
    return reg


def _clean_registry():
    """Each test should clean up its own test registrations."""
    reg = _get_reg()
    return reg


# ══════════════════════════════════════════════════════════════
# AgentSpec
# ══════════════════════════════════════════════════════════════

class TestAgentSpec:
    def test_required_fields(self):
        reg = _get_reg()
        spec = reg.AgentSpec(role_name="test", agent_class=object)
        assert spec.role_name == "test"
        assert spec.agent_class is object

    def test_defaults(self):
        reg = _get_reg()
        spec = reg.AgentSpec(role_name="test", agent_class=object)
        assert spec.capabilities == []
        assert spec.description == ""
        assert spec.version == "1.0.0"
        assert spec.is_builtin is True


# ══════════════════════════════════════════════════════════════
# AgentRegistry — register_type / get
# ══════════════════════════════════════════════════════════════

class TestAgentRegistryRegister:
    def setup_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__test_role__")
        reg.AgentRegistry.unregister("__test_role_2__")

    def teardown_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__test_role__")
        reg.AgentRegistry.unregister("__test_role_2__")

    def test_register_and_get(self):
        reg = _get_reg()
        reg.AgentRegistry.register_type(
            role_name="__test_role__",
            agent_class=object,
            capabilities=["test_cap"],
        )
        spec = reg.AgentRegistry.get("__test_role__")
        assert spec is not None
        assert spec.role_name == "__test_role__"

    def test_get_missing_returns_none(self):
        reg = _get_reg()
        assert reg.AgentRegistry.get("__nonexistent_xyz__") is None

    def test_capabilities_stored(self):
        reg = _get_reg()
        reg.AgentRegistry.register_type(
            role_name="__test_role__",
            agent_class=object,
            capabilities=["cap_a", "cap_b"],
        )
        spec = reg.AgentRegistry.get("__test_role__")
        assert "cap_a" in spec.capabilities
        assert "cap_b" in spec.capabilities

    def test_description_stored(self):
        reg = _get_reg()
        reg.AgentRegistry.register_type(
            role_name="__test_role__",
            agent_class=object,
            description="My test agent",
        )
        spec = reg.AgentRegistry.get("__test_role__")
        assert spec.description == "My test agent"


# ══════════════════════════════════════════════════════════════
# AgentRegistry — find_by_capability
# ══════════════════════════════════════════════════════════════

class TestFindByCapability:
    def setup_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__cap_agent__")

    def teardown_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__cap_agent__")

    def test_finds_registered_capability(self):
        reg = _get_reg()
        reg.AgentRegistry.register_type(
            role_name="__cap_agent__",
            agent_class=object,
            capabilities=["unique_cap_xyz"],
        )
        results = reg.AgentRegistry.find_by_capability("unique_cap_xyz")
        assert any(s.role_name == "__cap_agent__" for s in results)

    def test_missing_capability_returns_empty(self):
        reg = _get_reg()
        results = reg.AgentRegistry.find_by_capability("__cap_that_doesnt_exist__")
        assert results == []


# ══════════════════════════════════════════════════════════════
# AgentRegistry — list_all
# ══════════════════════════════════════════════════════════════

class TestListAll:
    def test_returns_list(self):
        reg = _get_reg()
        result = reg.AgentRegistry.list_all()
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════
# AgentRegistry — create
# ══════════════════════════════════════════════════════════════

class TestCreate:
    def setup_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__create_test__")

    def teardown_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__create_test__")

    def test_create_instantiates_class(self):
        reg = _get_reg()

        class _FakeAgent:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        reg.AgentRegistry.register_type(role_name="__create_test__", agent_class=_FakeAgent)
        instance = reg.AgentRegistry.create("__create_test__", cfg=None)
        assert isinstance(instance, _FakeAgent)

    def test_create_missing_raises_key_error(self):
        reg = _get_reg()
        with pytest.raises(KeyError, match="__no_such_agent__"):
            reg.AgentRegistry.create("__no_such_agent__")


# ══════════════════════════════════════════════════════════════
# AgentRegistry — unregister
# ══════════════════════════════════════════════════════════════

class TestUnregister:
    def setup_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("__unreg_test__")

    def test_unregister_existing(self):
        reg = _get_reg()
        reg.AgentRegistry.register_type(role_name="__unreg_test__", agent_class=object)
        assert reg.AgentRegistry.unregister("__unreg_test__") is True
        assert reg.AgentRegistry.get("__unreg_test__") is None

    def test_unregister_missing_returns_false(self):
        reg = _get_reg()
        assert reg.AgentRegistry.unregister("__unreg_test__") is False


# ══════════════════════════════════════════════════════════════
# @register decorator
# ══════════════════════════════════════════════════════════════

class TestRegisterDecorator:
    def teardown_method(self):
        reg = _get_reg()
        reg.AgentRegistry.unregister("decorated_test_agent")

    def test_decorator_registers_class(self):
        reg = _get_reg()

        @reg.AgentRegistry.register(capabilities=["test_cap_dec"])
        class DecoratedTestAgent:
            ROLE_NAME = "decorated_test_agent"

        spec = reg.AgentRegistry.get("decorated_test_agent")
        assert spec is not None
        assert "test_cap_dec" in spec.capabilities

    def test_decorator_returns_original_class(self):
        reg = _get_reg()

        @reg.AgentRegistry.register(capabilities=[])
        class AnotherTestAgent:
            ROLE_NAME = "decorated_test_agent"

        assert AnotherTestAgent is not None
        assert AnotherTestAgent.__name__ == "AnotherTestAgent"
