from __future__ import annotations

import core


def test_optional_import_returns_proxy_and_raises_runtime_error(monkeypatch) -> None:
    def _broken_import(_module_name: str):
        raise ImportError("missing optional dependency")

    monkeypatch.setattr(core, "import_module", _broken_import)

    missing_class = core._optional_import("core.some_missing_module", "SomeClass")

    try:
        missing_class()
    except RuntimeError as exc:
        assert "SomeClass" in str(exc)
        assert "opsiyonel bağımlılıklar" in str(exc)
    else:
        raise AssertionError("Missing dependency proxy must raise RuntimeError on instantiation")


def test_optional_module_returns_none_when_import_fails(monkeypatch) -> None:
    def _broken_import(_module_name: str):
        raise ModuleNotFoundError("module missing")

    monkeypatch.setattr(core, "import_module", _broken_import)

    assert core._optional_module("core.not_existing") is None
