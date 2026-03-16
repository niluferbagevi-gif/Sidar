"""
Sidar Project — Core Modülleri

Bu paket ajan altyapısının temel bileşenlerini dışa aktarır:
- ConversationMemory : Thread-safe, kalıcı ve opsiyonel Fernet şifrelemeli konuşma belleği
- LLMClient         : Ollama ve Gemini için asenkron, streaming LLM istemcisi
- DocumentStore     : ChromaDB + BM25 + Keyword hibrit RAG belgesi deposu
"""

from importlib import import_module

__version__ = "2.7.0"


class _ExportedSymbolName:
    def __init__(self, name: str) -> None:
        self.__name__ = name


ConversationMemory = _ExportedSymbolName("ConversationMemory")
LLMClient = _ExportedSymbolName("LLMClient")
DocumentStore = _ExportedSymbolName("DocumentStore")
Database = _ExportedSymbolName("Database")
LLMMetricsCollector = _ExportedSymbolName("LLMMetricsCollector")

# Geriye dönük/kolaylaştırıcı alias'lar
MemoryManager = ConversationMemory
RAGManager = DocumentStore
DatabaseManager = Database

# Tek kaynak: core dışına açılacak sınıf sembolleri burada tutulur.
_EXPORTED_CORE_SYMBOLS = (
    ConversationMemory,
    LLMClient,
    DocumentStore,
    Database,
    LLMMetricsCollector,
)

__all__ = [sym.__name__ for sym in _EXPORTED_CORE_SYMBOLS] + ["__version__"]
__all__ += ["MemoryManager", "RAGManager", "DatabaseManager"]


_LAZY_IMPORTS = {
    "ConversationMemory": ("core.memory", "ConversationMemory"),
    "LLMClient": ("core.llm_client", "LLMClient"),
    "DocumentStore": ("core.rag", "DocumentStore"),
    "Database": ("core.db", "Database"),
    "LLMMetricsCollector": ("core.llm_metrics", "LLMMetricsCollector"),
    "MemoryManager": ("core.memory", "ConversationMemory"),
    "RAGManager": ("core.rag", "DocumentStore"),
    "DatabaseManager": ("core.db", "Database"),
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value