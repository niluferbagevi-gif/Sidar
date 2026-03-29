"""
agent/registry.py için birim testleri.
AgentRegistry, AgentSpec ve _register_builtin_agents kapsar.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _stub_agent_deps():
    """agent.registry'nin bağımlı olduğu modülleri stub'lar."""
    # config stub
    if "config" not in sys.modules:
        cfg_stub = types.ModuleType("config")
        cfg_stub.Config = type("Config", (), {"AI_PROVIDER": "ollama"})
        sys.modules["config"] = cfg_stub

    # core.llm_client stub
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            stub = types.ModuleType(mod)
            sys.modules[mod] = stub
    llm_stub = sys.modules["core.llm_client"]
    if not hasattr(llm_stub, "LLMClient"):
        llm_stub.LLMClient = MagicMock()

    # agent package stub — __path__ gerekli, yoksa submodule import çalışmaz
    import pathlib as _pl
    _proj = _pl.Path(__file__).parent.parent
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg
    if "agent.core" not in sys.modules:
        sys.modules["agent.core"] = types.ModuleType("agent.core")
    if "agent.core.contracts" not in sys.modules:
        sys.modules["agent.core.contracts"] = types.ModuleType("agent.core.contracts")

    contracts = sys.modules["agent.core.contracts"]
    for attr in ("DelegationRequest", "TaskEnvelope", "TaskResult", "is_delegation_request"):
        if not hasattr(contracts, attr):
            if attr == "is_delegation_request":
                setattr(contracts, attr, lambda x: False)
            else:
                setattr(contracts, attr, MagicMock())


def _get_registry():
    _stub_agent_deps()
    # Önceki kayıtları temizlemek için modülü yeniden yükle
    for mod in list(sys.modules.keys()):
        if mod.startswith("agent.registry") or mod == "agent.registry":
            del sys.modules[mod]
    # Rol modüllerini stub'la (builtin ajan importlarının başarısız olması sorun değil)
    import agent.registry as reg
    # Temiz bir registry ile başla
    reg.AgentRegistry._registry.clear()
    return reg


class TestAgentSpec:
    def test_spec_creation(self):
        reg = _get_registry()
        spec = reg.AgentSpec(
            role_name="test_role",
            agent_class=object,
            capabilities=["cap1"],
            description="test desc",
        )
        assert spec.role_name == "test_role"
        assert spec.capabilities == ["cap1"]
        assert spec.description == "test desc"

    def test_spec_defaults(self):
        reg = _get_registry()
        spec = reg.AgentSpec(role_name="r", agent_class=object)
        assert spec.capabilities == []
        assert spec.description == ""
        assert spec.version == "1.0.0"
        assert spec.is_builtin is True


class TestAgentRegistryRegisterType:
    def test_register_and_get(self):
        reg = _get_registry()

        class DummyAgent:
            pass

        reg.AgentRegistry.register_type(
            role_name="dummy",
            agent_class=DummyAgent,
            capabilities=["test"],
        )
        spec = reg.AgentRegistry.get("dummy")
        assert spec is not None
        assert spec.role_name == "dummy"
        assert spec.agent_class is DummyAgent

    def test_get_nonexistent_returns_none(self):
        reg = _get_registry()
        assert reg.AgentRegistry.get("nonexistent_xyz") is None

    def test_list_all_returns_registered(self):
        reg = _get_registry()

        class AgentA:
            pass

        reg.AgentRegistry.register_type(role_name="agent_a", agent_class=AgentA)
        all_specs = reg.AgentRegistry.list_all()
        names = [s.role_name for s in all_specs]
        assert "agent_a" in names

    def test_unregister(self):
        reg = _get_registry()

        class AgentB:
            pass

        reg.AgentRegistry.register_type(role_name="agent_b", agent_class=AgentB)
        result = reg.AgentRegistry.unregister("agent_b")
        assert result is True
        assert reg.AgentRegistry.get("agent_b") is None

    def test_unregister_nonexistent_returns_false(self):
        reg = _get_registry()
        assert reg.AgentRegistry.unregister("not_there") is False


class TestAgentRegistryFindByCapability:
    def test_find_by_capability(self):
        reg = _get_registry()

        class CapAgent:
            pass

        reg.AgentRegistry.register_type(
            role_name="cap_agent",
            agent_class=CapAgent,
            capabilities=["unique_cap_xyz"],
        )
        results = reg.AgentRegistry.find_by_capability("unique_cap_xyz")
        assert len(results) >= 1
        assert results[0].role_name == "cap_agent"

    def test_find_by_missing_capability_returns_empty(self):
        reg = _get_registry()
        results = reg.AgentRegistry.find_by_capability("capability_that_does_not_exist")
        assert results == []


class TestAgentRegistryDecorator:
    def test_register_decorator(self):
        reg = _get_registry()

        @reg.AgentRegistry.register(capabilities=["decorated_cap"], description="Decorated agent")
        class DecoratedAgent:
            ROLE_NAME = "decorated"

        spec = reg.AgentRegistry.get("decorated")
        assert spec is not None
        assert "decorated_cap" in spec.capabilities

    def test_register_decorator_returns_class_unchanged(self):
        reg = _get_registry()

        @reg.AgentRegistry.register(capabilities=[])
        class ReturnedAgent:
            ROLE_NAME = "returned"
            custom_attr = 42

        assert ReturnedAgent.custom_attr == 42

    def test_register_decorator_infers_role_and_description_from_class(self):
        reg = _get_registry()

        @reg.AgentRegistry.register()
        class InsightAgent:
            """İçgörü üretir."""

        spec = reg.AgentRegistry.get("insight")
        assert spec is not None
        assert spec.description == "İçgörü üretir."


class TestAgentRegistryCreate:
    def test_create_agent(self):
        reg = _get_registry()

        class CreatableAgent:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        reg.AgentRegistry.register_type(role_name="creatable", agent_class=CreatableAgent)
        instance = reg.AgentRegistry.create("creatable", cfg=None)
        assert isinstance(instance, CreatableAgent)

    def test_create_unknown_role_raises(self):
        reg = _get_registry()
        import pytest
        with pytest.raises(KeyError, match="kayıt defterinde bulunamadı"):
            reg.AgentRegistry.create("unknown_role_xyz")


class TestRegisterBuiltinAgents:
    def test_register_builtin_agents_registers_importable_roles(self):
        reg = _get_registry()
        reg.AgentRegistry._registry.clear()

        role_map = {
            "agent.roles.coder_agent": "CoderAgent",
            "agent.roles.researcher_agent": "ResearcherAgent",
            "agent.roles.reviewer_agent": "ReviewerAgent",
            "agent.roles.poyraz_agent": "PoyrazAgent",
            "agent.roles.coverage_agent": "CoverageAgent",
            "agent.roles.qa_agent": "QAAgent",
        }
        for module_name, class_name in role_map.items():
            mod = types.ModuleType(module_name)
            setattr(mod, class_name, type(class_name, (), {}))
            sys.modules[module_name] = mod

        reg._register_builtin_agents()

        for role_name in ("coder", "researcher", "reviewer", "poyraz", "coverage", "qa"):
            assert reg.AgentRegistry.get(role_name) is not None
