import importlib
import sys
import types

import pytest


def _load_agent_module(monkeypatch: pytest.MonkeyPatch):
    sidar_mod = types.ModuleType("agent.sidar_agent")
    sidar_cls = type("SidarAgent", (), {})
    sidar_mod.SidarAgent = sidar_cls

    auto_mod = types.ModuleType("agent.auto_handle")
    auto_cls = type("AutoHandle", (), {})
    auto_mod.AutoHandle = auto_cls

    roles_mod = types.ModuleType("agent.roles")
    roles_mod.ROLES_SENTINEL = True

    registry_mod = types.ModuleType("agent.registry")
    registry_mod.REGISTRY_SENTINEL = True

    swarm_mod = types.ModuleType("agent.swarm")
    swarm_mod.SWARM_SENTINEL = True

    defs_mod = types.ModuleType("agent.definitions")
    defs_mod.SIDAR_SYSTEM_PROMPT = "prompt"
    defs_mod.SIDAR_KEYS = ["k1", "k2"]
    defs_mod.SIDAR_WAKE_WORDS = ["sidar"]

    monkeypatch.setitem(sys.modules, "agent.sidar_agent", sidar_mod)
    monkeypatch.setitem(sys.modules, "agent.auto_handle", auto_mod)
    monkeypatch.setitem(sys.modules, "agent.roles", roles_mod)
    monkeypatch.setitem(sys.modules, "agent.registry", registry_mod)
    monkeypatch.setitem(sys.modules, "agent.swarm", swarm_mod)
    monkeypatch.setitem(sys.modules, "agent.definitions", defs_mod)

    sys.modules.pop("agent", None)
    return importlib.import_module("agent")


def test_getattr_exposes_lazy_class_imports(monkeypatch):
    mod = _load_agent_module(monkeypatch)

    assert mod.SidarAgent.__name__ == "SidarAgent"
    assert mod.AutoHandle.__name__ == "AutoHandle"
    assert mod.AutoHandler is mod.AutoHandle


def test_getattr_exposes_lazy_module_imports(monkeypatch):
    mod = _load_agent_module(monkeypatch)

    assert mod.roles.ROLES_SENTINEL is True
    assert mod.registry.REGISTRY_SENTINEL is True
    assert mod.swarm.SWARM_SENTINEL is True


def test_getattr_exposes_lazy_constant_imports(monkeypatch):
    mod = _load_agent_module(monkeypatch)

    assert mod.SIDAR_SYSTEM_PROMPT == "prompt"
    assert mod.SIDAR_KEYS == ["k1", "k2"]
    assert mod.SIDAR_WAKE_WORDS == ["sidar"]


def test_getattr_raises_for_unknown_names(monkeypatch):
    mod = _load_agent_module(monkeypatch)

    with pytest.raises(AttributeError):
        _ = mod.DOES_NOT_EXIST


def test_module_all_exports_public_api(monkeypatch):
    mod = _load_agent_module(monkeypatch)

    assert mod.__all__ == [
        "SidarAgent",
        "AutoHandle",
        "AutoHandler",
        "SIDAR_SYSTEM_PROMPT",
        "SIDAR_KEYS",
        "SIDAR_WAKE_WORDS",
    ]
