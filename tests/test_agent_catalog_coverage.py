from __future__ import annotations

import importlib
import sys
import types

import pytest

import agent.registry as registry_mod


def test_register_decorator_and_find_by_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_mod.AgentCatalog, "_registry", {})

    @registry_mod.AgentCatalog.register(capabilities=["search"], description="", is_builtin=False)
    class SearchAgent:
        """Search docs agent."""
        ROLE_NAME = "searcher"

    spec = registry_mod.AgentCatalog.get("searcher")
    assert spec is not None
    assert spec.description == "Search docs agent."
    assert registry_mod.AgentCatalog.find_by_capability("search")[0].role_name == "searcher"
    assert registry_mod.AgentCatalog.list_all()[0].agent_class is SearchAgent


def test_create_with_factory_and_unregister() -> None:
    registry_mod.AgentCatalog._registry = {}

    class _FactorySpec:
        def __init__(self) -> None:
            self.role_name = "factory-role"
            self.agent_class = None
            self._agent_factory = lambda **kwargs: {"created": kwargs.get("x")}

    registry_mod.AgentCatalog._registry["factory-role"] = _FactorySpec()

    created = registry_mod.AgentCatalog.create("factory-role", x=7)
    assert created == {"created": 7}
    assert registry_mod.AgentCatalog.unregister("factory-role") is True
    assert registry_mod.AgentCatalog.unregister("factory-role") is False


def test_create_raises_for_missing_and_invalid_spec() -> None:
    registry_mod.AgentCatalog._registry = {}
    with pytest.raises(KeyError):
        registry_mod.AgentCatalog.create("missing")

    registry_mod.AgentCatalog._registry["broken"] = types.SimpleNamespace(role_name="broken", agent_class=None)
    with pytest.raises(TypeError):
        registry_mod.AgentCatalog.create("broken")


def test_import_builtin_roles_swallows_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake_import(name: str):
        calls.append(name)
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib, "import_module", _fake_import)

    registry_mod._import_builtin_roles()

    assert len(calls) == 6
