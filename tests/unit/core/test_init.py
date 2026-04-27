from types import SimpleNamespace

import pytest

import core as core_init


def test_optional_import_returns_requested_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()

    def fake_import(module_name: str):
        assert module_name == "core.fake_module"
        return SimpleNamespace(TargetClass=sentinel)

    monkeypatch.setattr(core_init, "import_module", fake_import)

    resolved = core_init._optional_import("core.fake_module", "TargetClass")

    assert resolved is sentinel


def test_optional_import_returns_proxy_when_dependency_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import(_module_name: str):
        raise ImportError("dependency missing")

    monkeypatch.setattr(core_init, "import_module", fake_import)

    proxy_cls = core_init._optional_import("core.fake_module", "TargetClass")

    assert proxy_cls.__dict__.get("__name__") == "TargetClass"
    with pytest.raises(RuntimeError, match="opsiyonel bağımlılıklar"):
        proxy_cls()


def test_optional_module_returns_none_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_init, "import_module", lambda _name: (_ for _ in ()).throw(ImportError("boom"))
    )

    assert core_init._optional_module("core.fake_module") is None


def test_init_aliases_and_public_exports_are_wired() -> None:
    assert core_init.MemoryManager is core_init.ConversationMemory
    assert core_init.RAGManager is core_init.DocumentStore
    assert core_init.DatabaseManager is core_init.Database

    for symbol in (
        "ConversationMemory",
        "LLMClient",
        "DocumentStore",
        "Database",
        "LLMMetricsCollector",
        "get_llm_metrics_collector",
        "MemoryManager",
        "RAGManager",
        "DatabaseManager",
    ):
        assert symbol in core_init.__all__
