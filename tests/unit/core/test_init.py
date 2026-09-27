"""``core`` paketinin lazy sembol dışa aktarımları için unit testler."""

from types import SimpleNamespace

import pytest

import core as core_init


def _clear_core_cache(*names: str) -> None:
    for name in names:
        core_init.__dict__.pop(name, None)


def test_load_symbol_returns_requested_attribute_and_caches_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load symbol returns requested attribute and caches global."""
    sentinel = object()
    export_name = "TestTargetClass"
    module_name = "core.fake_module"
    _clear_core_cache(export_name)

    def fake_import(requested_module: str):
        assert requested_module == module_name
        return SimpleNamespace(TargetClass=sentinel)

    monkeypatch.setitem(core_init._SYMBOL_EXPORTS, export_name, (module_name, "TargetClass"))
    monkeypatch.setattr(core_init, "import_module", fake_import)

    resolved = core_init._load_symbol(export_name)

    assert resolved is sentinel
    assert core_init.__dict__[export_name] is sentinel
    _clear_core_cache(export_name)


def test_load_symbol_returns_missing_dependency_proxy_for_missing_requested_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load symbol returns missing dependency proxy for missing requested module."""
    export_name = "MissingTargetClass"
    module_name = "core.fake_missing_module"
    _clear_core_cache(export_name)

    def fake_import(_requested_module: str):
        raise ModuleNotFoundError(
            f"No module named {module_name!r}",
            name=module_name,
        )

    monkeypatch.setitem(core_init._SYMBOL_EXPORTS, export_name, (module_name, "TargetClass"))
    monkeypatch.setattr(core_init, "import_module", fake_import)

    proxy_cls = core_init._load_symbol(export_name)

    assert proxy_cls.__dict__.get("__name__") == "TargetClass"
    assert core_init.__dict__[export_name] is proxy_cls
    with pytest.raises(RuntimeError, match="opsiyonel bağımlılıklar"):
        proxy_cls()
    _clear_core_cache(export_name)


def test_load_symbol_reraises_transitive_module_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load symbol reraises transitive module not found."""
    export_name = "BrokenTargetClass"
    module_name = "core.fake_broken_module"
    _clear_core_cache(export_name)

    def fake_import(_requested_module: str):
        raise ModuleNotFoundError(
            "No module named 'transitive_dependency'",
            name="transitive_dependency",
        )

    monkeypatch.setitem(core_init._SYMBOL_EXPORTS, export_name, (module_name, "TargetClass"))
    monkeypatch.setattr(core_init, "import_module", fake_import)

    with pytest.raises(ModuleNotFoundError, match="transitive_dependency"):
        core_init._load_symbol(export_name)

    assert export_name not in core_init.__dict__


def test_getattr_unknown_name_raises_attribute_error() -> None:
    """Getattr unknown name raises attribute error."""
    with pytest.raises(AttributeError, match="UnknownCoreExport"):
        core_init.__getattr__("UnknownCoreExport")


def test_getattr_alias_export_caches_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """Getattr alias export caches global."""
    sentinel = object()
    symbol_name = "AliasTargetSymbol"
    alias_name = "AliasTargetManager"
    module_name = "core.fake_alias_module"
    _clear_core_cache(symbol_name, alias_name)

    def fake_import(requested_module: str):
        assert requested_module == module_name
        return SimpleNamespace(Target=sentinel)

    monkeypatch.setitem(core_init._SYMBOL_EXPORTS, symbol_name, (module_name, "Target"))
    monkeypatch.setitem(core_init._ALIAS_EXPORTS, alias_name, symbol_name)
    monkeypatch.setattr(core_init, "import_module", fake_import)

    resolved = core_init.__getattr__(alias_name)

    assert resolved is sentinel
    assert core_init.__dict__[symbol_name] is sentinel
    assert core_init.__dict__[alias_name] is sentinel
    _clear_core_cache(symbol_name, alias_name)


def test_init_aliases_and_public_exports_are_wired() -> None:
    """Init aliases and public exports are wired."""
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
