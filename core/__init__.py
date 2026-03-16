"""
Sidar Project — Core Modülleri

Bu paket ajan altyapısının temel bileşenlerini dışa aktarır:
- ConversationMemory : Thread-safe, kalıcı ve opsiyonel Fernet şifrelemeli konuşma belleği
- LLMClient         : Ollama ve Gemini için asenkron, streaming LLM istemcisi
- DocumentStore     : ChromaDB + BM25 + Keyword hibrit RAG belgesi deposu
"""

__version__ = "2.7.0"


def _optional_import(importer, fallback_name: str):
    """Opsiyonel bağımlılık eksik olsa da çekirdek paketin import edilebilmesini sağlar."""
    try:
        return importer()
    except Exception:
        class _MissingDependencyProxy:  # pragma: no cover - yalnızca bağımlılık eksikse çalışır
            __name__ = fallback_name

            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    f"'{fallback_name}' kullanımı için opsiyonel bağımlılıklar yüklü olmalıdır."
                )

        return _MissingDependencyProxy


LLMClient = _optional_import(lambda: __import__("core.llm_client", fromlist=["LLMClient"]).LLMClient, "LLMClient")
ConversationMemory = _optional_import(
    lambda: __import__("core.memory", fromlist=["ConversationMemory"]).ConversationMemory,
    "ConversationMemory",
)
DocumentStore = _optional_import(lambda: __import__("core.rag", fromlist=["DocumentStore"]).DocumentStore, "DocumentStore")
Database = _optional_import(lambda: __import__("core.db", fromlist=["Database"]).Database, "Database")
LLMMetricsCollector = _optional_import(
    lambda: __import__("core.llm_metrics", fromlist=["LLMMetricsCollector"]).LLMMetricsCollector,
    "LLMMetricsCollector",
)
get_llm_metrics_collector = _optional_import(
    lambda: __import__("core.llm_metrics", fromlist=["get_llm_metrics_collector"]).get_llm_metrics_collector,
    "get_llm_metrics_collector",
)

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
__all__ += ["get_llm_metrics_collector"]
