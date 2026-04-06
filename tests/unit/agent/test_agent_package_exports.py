"""Unit tests for ``agent`` package lazy exports and attribute routing."""

from __future__ import annotations

import sys
import types

import pytest

import agent


class _DummySidarAgent:
    pass


class _DummyAutoHandle:
    pass


def test_getattr_returns_lazy_loaded_primary_symbols() -> None:
    sidar_module = types.ModuleType("agent.sidar_agent")
    sidar_module.SidarAgent = _DummySidarAgent
    sys.modules["agent.sidar_agent"] = sidar_module

    auto_module = types.ModuleType("agent.auto_handle")
    auto_module.AutoHandle = _DummyAutoHandle
    sys.modules["agent.auto_handle"] = auto_module

    try:
        assert agent.__getattr__("SidarAgent") is _DummySidarAgent
        assert agent.__getattr__("AutoHandle") is _DummyAutoHandle
        assert agent.__getattr__("AutoHandler") is _DummyAutoHandle
    finally:
        sys.modules.pop("agent.sidar_agent", None)
        sys.modules.pop("agent.auto_handle", None)


def test_getattr_routes_module_level_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_roles_module = object()
    fake_registry_module = object()

    def _fake_import_module(name: str, package: str):
        if name == ".roles":
            return fake_roles_module
        if name == ".registry":
            return fake_registry_module
        raise AssertionError("unexpected module import")

    monkeypatch.setattr(agent, "import_module", _fake_import_module)

    assert agent.__getattr__("roles") is fake_roles_module
    assert agent.__getattr__("registry") is fake_registry_module


def test_getattr_definition_constants_and_unknown_attribute() -> None:
    definitions_module = types.ModuleType("agent.definitions")
    definitions_module.SIDAR_SYSTEM_PROMPT = "system"
    definitions_module.SIDAR_KEYS = ["a", "b"]
    definitions_module.SIDAR_WAKE_WORDS = ["sidar"]
    sys.modules["agent.definitions"] = definitions_module

    try:
        assert agent.__getattr__("SIDAR_SYSTEM_PROMPT") == "system"
        assert agent.__getattr__("SIDAR_KEYS") == ["a", "b"]
        assert agent.__getattr__("SIDAR_WAKE_WORDS") == ["sidar"]
        with pytest.raises(AttributeError):
            agent.__getattr__("UNKNOWN_ATTRIBUTE")
    finally:
        sys.modules.pop("agent.definitions", None)
