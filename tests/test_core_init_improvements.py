from pathlib import Path


def test_core_init_uses_single_source_symbol_exports():
    src = Path("core/__init__.py").read_text(encoding="utf-8")
    assert "_EXPORTED_CORE_SYMBOLS = (" in src
    assert "__all__ = [sym.__name__ for sym in _EXPORTED_CORE_SYMBOLS] + [\"__version__\"]" in src
    assert "DocumentStore" in src


def test_core_init_exports_memory_and_rag_aliases():
    src = Path("core/__init__.py").read_text(encoding="utf-8")
    assert "MemoryManager = ConversationMemory" in src
    assert "RAGManager = DocumentStore" in src
    assert '__all__ += ["MemoryManager", "RAGManager", "DatabaseManager"]' in src

def test_core_optional_import_and_module_runtime_fallbacks(monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("core_init_under_test", Path("core/__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "import_module", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("missing")))
    proxy = mod._optional_import("x.y", "DemoClass")
    try:
        proxy()
        assert False
    except RuntimeError as exc:
        assert "opsiyonel bağımlılıklar" in str(exc)

    assert mod._optional_module("x.y") is None