"""Unit tests for core package optional import helpers and aliases."""

from __future__ import annotations

import types

import pytest

import core


def test_optional_import_success_uses_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.SimpleNamespace(ExpectedSymbol=object())

    def _fake_import(name: str):
        assert name == "fake.module"
        return module

    monkeypatch.setattr(core, "import_module", _fake_import)

    resolved = core._optional_import("fake.module", "ExpectedSymbol")
    assert resolved is module.ExpectedSymbol


def test_optional_import_failure_returns_proxy_raising_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_import_error(_: str):
        raise ImportError("missing optional dependency")

    monkeypatch.setattr(core, "import_module", _raise_import_error)

    proxy_cls = core._optional_import("missing.module", "MissingClass")

    with pytest.raises(RuntimeError, match="MissingClass"):
        proxy_cls()


def test_optional_module_returns_none_when_module_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_runtime_error(_: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(core, "import_module", _raise_runtime_error)

    assert core._optional_module("missing.module") is None


def test_core_alias_symbols_are_wired_to_primary_exports() -> None:
    assert core.MemoryManager is core.ConversationMemory
    assert core.RAGManager is core.DocumentStore
    assert core.DatabaseManager is core.Database
