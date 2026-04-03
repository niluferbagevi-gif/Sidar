from __future__ import annotations

import importlib
import sys
import types

import pytest


def _reload_agent_module(monkeypatch: pytest.MonkeyPatch):
    for mod_name in ("agent", "agent.sidar_agent", "agent.auto_handle", "agent.definitions"):
        sys.modules.pop(mod_name, None)

    sidar_stub = types.ModuleType("agent.sidar_agent")
    sidar_stub.SidarAgent = type("SidarAgent", (), {})
    monkeypatch.setitem(sys.modules, "agent.sidar_agent", sidar_stub)

    auto_stub = types.ModuleType("agent.auto_handle")
    auto_stub.AutoHandle = type("AutoHandle", (), {})
    monkeypatch.setitem(sys.modules, "agent.auto_handle", auto_stub)

    definitions_stub = types.ModuleType("agent.definitions")
    definitions_stub.SIDAR_SYSTEM_PROMPT = "prompt"
    definitions_stub.SIDAR_KEYS = ["sidar"]
    definitions_stub.SIDAR_WAKE_WORDS = ["hey sidar"]
    monkeypatch.setitem(sys.modules, "agent.definitions", definitions_stub)

    return importlib.import_module("agent")


def test_agent_init_lazy_exports_and_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_module = _reload_agent_module(monkeypatch)

    assert agent_module.__getattr__("SidarAgent").__name__ == "SidarAgent"
    assert agent_module.__getattr__("AutoHandle").__name__ == "AutoHandle"
    assert agent_module.__getattr__("AutoHandler").__name__ == "AutoHandle"


def test_agent_init_definition_constants_and_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_module = _reload_agent_module(monkeypatch)

    assert agent_module.__getattr__("SIDAR_SYSTEM_PROMPT") == "prompt"
    assert agent_module.__getattr__("SIDAR_KEYS") == ["sidar"]
    assert agent_module.__getattr__("SIDAR_WAKE_WORDS") == ["hey sidar"]

    with pytest.raises(AttributeError):
        agent_module.__getattr__("UNKNOWN_EXPORT")


def test_agent_init_all_exports_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_module = _reload_agent_module(monkeypatch)

    assert agent_module.__all__ == [
        "SidarAgent",
        "AutoHandle",
        "AutoHandler",
        "SIDAR_SYSTEM_PROMPT",
        "SIDAR_KEYS",
        "SIDAR_WAKE_WORDS",
    ]
