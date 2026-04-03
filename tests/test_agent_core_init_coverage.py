from __future__ import annotations

import importlib
import sys
import types

import pytest


def _reload_agent_core_module(monkeypatch: pytest.MonkeyPatch):
    for mod_name in (
        "agent.core",
        "agent.core.contracts",
        "agent.core.memory_hub",
        "agent.core.registry",
        "agent.core.supervisor",
    ):
        sys.modules.pop(mod_name, None)

    contracts_stub = types.ModuleType("agent.core.contracts")
    contracts_stub.TaskEnvelope = type("TaskEnvelope", (), {})
    contracts_stub.TaskResult = type("TaskResult", (), {})
    monkeypatch.setitem(sys.modules, "agent.core.contracts", contracts_stub)

    memory_stub = types.ModuleType("agent.core.memory_hub")
    memory_stub.MemoryHub = type("MemoryHub", (), {})
    monkeypatch.setitem(sys.modules, "agent.core.memory_hub", memory_stub)

    registry_stub = types.ModuleType("agent.core.registry")
    registry_stub.AgentRegistry = type("AgentRegistry", (), {})
    monkeypatch.setitem(sys.modules, "agent.core.registry", registry_stub)

    supervisor_stub = types.ModuleType("agent.core.supervisor")
    supervisor_stub.SupervisorAgent = type("SupervisorAgent", (), {})
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", supervisor_stub)

    return importlib.import_module("agent.core")


def test_agent_core_init_lazy_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    core_module = _reload_agent_core_module(monkeypatch)

    assert core_module.__getattr__("MemoryHub").__name__ == "MemoryHub"
    assert core_module.__getattr__("AgentRegistry").__name__ == "AgentRegistry"
    assert core_module.__getattr__("SupervisorAgent").__name__ == "SupervisorAgent"


def test_agent_core_init_contract_exports_and_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    core_module = _reload_agent_core_module(monkeypatch)

    assert core_module.TaskEnvelope.__name__ == "TaskEnvelope"
    assert core_module.TaskResult.__name__ == "TaskResult"

    with pytest.raises(AttributeError):
        core_module.__getattr__("UNKNOWN_CORE_EXPORT")


def test_agent_core_init_all_exports_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    core_module = _reload_agent_core_module(monkeypatch)

    assert core_module.__all__ == [
        "TaskEnvelope",
        "TaskResult",
        "MemoryHub",
        "AgentRegistry",
        "SupervisorAgent",
    ]
