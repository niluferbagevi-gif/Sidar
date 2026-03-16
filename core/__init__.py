"""
Sidar Project — Core Modülleri

Bu paket ajan altyapısının temel bileşenlerini dışa aktarır:
- ConversationMemory : Thread-safe, kalıcı ve opsiyonel Fernet şifrelemeli konuşma belleği
- LLMClient         : Ollama ve Gemini için asenkron, streaming LLM istemcisi
- DocumentStore     : ChromaDB + BM25 + Keyword hibrit RAG belgesi deposu
"""

from importlib import import_module

__version__ = "2.7.0"


def _optional_import(module_name: str, attr_name: str):
    """Opsiyonel bağımlılık eksik olsa da çekirdek paketin import edilebilmesini sağlar."""
    try:
        module = import_module(module_name)
        return getattr(module, attr_name)
    except Exception:
        class _MissingDependencyProxy:  # pragma: no cover - yalnızca bağımlılık eksikse çalışır
            __name__ = attr_name

            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    f"'{attr_name}' kullanımı için opsiyonel bağımlılıklar yüklü olmalıdır."
                )

        return _MissingDependencyProxy


LLMClient = _optional_import("core.llm_client", "LLMClient")
ConversationMemory = _optional_import("core.memory", "ConversationMemory")
DocumentStore = _optional_import("core.rag", "DocumentStore")
Database = _optional_import("core.db", "Database")

# Metrik toplayıcı sembollerini doğrudan hedef modülden çöz.
# Böylece __import__/fromlist kaynaklı kırılganlıklar ortadan kalkar.
LLMMetricsCollector = _optional_import("core.llm_metrics", "LLMMetricsCollector")
get_llm_metrics_collector = _optional_import("core.llm_metrics", "get_llm_metrics_collector")

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
