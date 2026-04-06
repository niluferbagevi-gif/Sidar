"""Unit tests for lazy import behavior in managers package."""

from types import ModuleType

import pytest

import managers


def test_getattr_resolves_manager_class_and_caches(monkeypatch: pytest.MonkeyPatch):
    """`from managers import CodeManager` path should lazy-load class and cache it."""
    calls: list[str] = []

    fake_module = ModuleType("managers.code_manager")

    class FakeCodeManager:
        pass

    fake_module.CodeManager = FakeCodeManager

    def fake_import(module_path: str):
        calls.append(module_path)
        return fake_module

    managers.__dict__.pop("CodeManager", None)
    monkeypatch.setattr(managers, "import_module", fake_import)

    value = managers.__getattr__("CodeManager")

    assert value is FakeCodeManager
    assert managers.CodeManager is FakeCodeManager
    assert calls == ["managers.code_manager"]


def test_getattr_resolves_module_name_for_monkeypatch_access(
    monkeypatch: pytest.MonkeyPatch,
):
    """`managers.package_info` style access should return underlying module object."""
    calls: list[str] = []
    fake_module = ModuleType("managers.package_info")

    def fake_import(module_path: str):
        calls.append(module_path)
        return fake_module

    managers.__dict__.pop("package_info", None)
    monkeypatch.setattr(managers, "import_module", fake_import)

    value = managers.__getattr__("package_info")

    assert value is fake_module
    assert managers.package_info is fake_module
    assert calls == ["managers.package_info"]


def test_getattr_raises_attribute_error_for_unknown_name():
    with pytest.raises(AttributeError, match="has no attribute 'UnknownManager'"):
        managers.__getattr__("UnknownManager")
