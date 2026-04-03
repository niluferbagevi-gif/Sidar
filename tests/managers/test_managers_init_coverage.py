from __future__ import annotations

import importlib
import sys
import types

import pytest


@pytest.fixture
def managers_module():
    for mod_name in ("managers", "managers.code_manager"):
        sys.modules.pop(mod_name, None)

    code_manager_stub = types.ModuleType("managers.code_manager")
    code_manager_stub.CodeManager = type("CodeManager", (), {})
    sys.modules["managers.code_manager"] = code_manager_stub

    module = importlib.import_module("managers")
    yield module

    sys.modules.pop("managers", None)
    sys.modules.pop("managers.code_manager", None)


def test_managers_init_lazy_getattr_resolves_and_caches_symbol(managers_module, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_import_module = managers_module.import_module

    def tracking_import_module(module_path: str):
        calls.append(module_path)
        return real_import_module(module_path)

    monkeypatch.setattr(managers_module, "import_module", tracking_import_module)

    resolved = managers_module.__getattr__("CodeManager")

    assert resolved.__name__ == "CodeManager"
    assert calls == ["managers.code_manager"]
    assert managers_module.CodeManager is resolved


def test_managers_init_getattr_raises_for_unknown_symbol(managers_module) -> None:
    with pytest.raises(AttributeError):
        managers_module.__getattr__("UnknownManager")
