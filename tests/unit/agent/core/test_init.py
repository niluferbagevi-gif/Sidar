import sys
from types import ModuleType

import pytest

import agent.core as core


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, module_name: str, symbol_name: str):
    fake_module = ModuleType(module_name)
    fake_symbol = type(symbol_name, (), {})
    setattr(fake_module, symbol_name, fake_symbol)
    monkeypatch.setitem(sys.modules, module_name, fake_module)
    return fake_symbol


def test_dunder_all_contains_public_api_symbols():
    assert core.__all__ == [
        "TaskEnvelope",
        "TaskResult",
        "MemoryHub",
        "AgentRegistry",
        "SupervisorAgent",
    ]


def test_getattr_resolves_memory_hub_lazily(monkeypatch: pytest.MonkeyPatch):
    expected = _install_fake_module(monkeypatch, "agent.core.memory_hub", "MemoryHub")

    assert core.MemoryHub is expected


def test_getattr_resolves_agent_registry_lazily(monkeypatch: pytest.MonkeyPatch):
    expected = _install_fake_module(monkeypatch, "agent.core.registry", "AgentRegistry")

    assert core.AgentRegistry is expected


def test_getattr_resolves_supervisor_agent_lazily(monkeypatch: pytest.MonkeyPatch):
    expected = _install_fake_module(monkeypatch, "agent.core.supervisor", "SupervisorAgent")

    assert core.SupervisorAgent is expected


def test_getattr_raises_attribute_error_for_unknown_symbol():
    with pytest.raises(AttributeError):
        core.__getattr__("UnknownSymbol")
