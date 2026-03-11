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