"""
agent/core/registry.py için birim testleri.
Bu dosya agent.base_agent'a bağımlıdır; BaseAgent stub'lanır.
"""
from __future__ import annotations

import sys
import types
import pathlib as _pl
from unittest.mock import MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_core_registry_deps():
    """agent.core.registry'nin bağımlılıklarını stub'lar."""
    # agent package stub
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    # agent.core stub — __path__ ile submodule import çalışır
    if "agent.core" not in sys.modules:
        core_pkg = types.ModuleType("agent.core")
        core_pkg.__path__ = [str(_proj / "agent" / "core")]
        core_pkg.__package__ = "agent.core"
        sys.modules["agent.core"] = core_pkg
    else:
        core_pkg = sys.modules["agent.core"]
        if not hasattr(core_pkg, "__path__"):
            core_pkg.__path__ = [str(_proj / "agent" / "core")]
            core_pkg.__package__ = "agent.core"

    # config stub (agent.base_agent tarafından import edilebilir)
    if "config" not in sys.modules:
        cfg_stub = types.ModuleType("config")
        cfg_stub.Config = type("Config", (), {"AI_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen2.5-coder:7b"})
        sys.modules["config"] = cfg_stub

    # core.llm_client stub
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        sys.modules["core.llm_client"].LLMClient = MagicMock()

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        sys.modules["agent.core.contracts"] = types.ModuleType("agent.core.contracts")
    contracts = sys.modules["agent.core.contracts"]
    for attr in ("DelegationRequest", "TaskEnvelope", "TaskResult", "is_delegation_request"):
        if not hasattr(contracts, attr):
            if attr == "is_delegation_request":
                setattr(contracts, attr, lambda x: False)
            else:
                setattr(contracts, attr, MagicMock())

    # agent.base_agent stub — BaseAgent soyut sınıf gibi davranır
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")

        class _BaseAgent:
            def __init__(self, *args, cfg=None, role_name="base", **kwargs):
                self.cfg = cfg
                self.role_name = role_name
                self.llm = MagicMock()
                self.tools = {}

            async def run_task(self, task_prompt: str):
                return f"stub: {task_prompt}"

        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_core_registry():
    _stub_core_registry_deps()
    sys.modules.pop("agent.core.registry", None)
    import agent.core.registry as reg
    return reg


def _make_mock_agent(role_name="test"):
    ba = sys.modules["agent.base_agent"].BaseAgent
    class DummyAgent(ba):
        async def run_task(self, task_prompt: str, **kwargs):
            return "ok"

    agent = DummyAgent(role_name=role_name)
    return agent


class TestAgentRegistryRegister:
    def test_register_and_get(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        agent = _make_mock_agent("coder")
        registry.register("coder", agent)
        result = registry.get("coder")
        assert result is agent

    def test_register_overwrites(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        agent1 = _make_mock_agent("coder")
        agent2 = _make_mock_agent("coder")
        registry.register("coder", agent1)
        registry.register("coder", agent2)
        assert registry.get("coder") is agent2

    def test_get_unknown_raises_key_error(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        with pytest.raises(KeyError, match="kayıtlı değil"):
            registry.get("unknown_role_xyz")

    def test_get_error_message_contains_role(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        with pytest.raises(KeyError) as exc_info:
            registry.get("my_missing_role")
        assert "my_missing_role" in str(exc_info.value)


class TestAgentRegistryHas:
    def test_has_registered_role(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        registry.register("reviewer", _make_mock_agent("reviewer"))
        assert registry.has("reviewer") is True

    def test_has_unregistered_role(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        assert registry.has("nonexistent") is False


class TestAgentRegistryRoles:
    def test_roles_empty_initially(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        roles = tuple(registry.roles())
        assert len(roles) == 0

    def test_roles_contains_registered(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        registry.register("coder", _make_mock_agent("coder"))
        registry.register("reviewer", _make_mock_agent("reviewer"))
        roles = tuple(registry.roles())
        assert "coder" in roles
        assert "reviewer" in roles

    def test_roles_returns_tuple(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        registry.register("qa", _make_mock_agent("qa"))
        roles = registry.roles()
        assert isinstance(roles, tuple)


class TestAgentRegistryIsolation:
    def test_two_registries_are_independent(self):
        reg = _get_core_registry()
        r1 = reg.AgentRegistry()
        r2 = reg.AgentRegistry()
        r1.register("coder", _make_mock_agent("coder"))
        assert not r2.has("coder")

    def test_multiple_agents_registered(self):
        reg = _get_core_registry()
        registry = reg.AgentRegistry()
        roles = ["coder", "reviewer", "qa", "researcher", "poyraz"]
        for role in roles:
            registry.register(role, _make_mock_agent(role))
        for role in roles:
            assert registry.has(role)
        assert len(tuple(registry.roles())) == len(roles)
