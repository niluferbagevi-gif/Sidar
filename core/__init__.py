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


def _optional_module(module_name: str):
    """Alt modül import'u başarısız olsa da çekirdek paketinin yüklenmesini engellemez."""
    try:
        return import_module(module_name)
    except Exception:
        return None


# Testlerde monkeypatch("core.<module>....") kullanımını desteklemek için
# alt modülleri paket seviyesinde erişilebilir kıl.
memory = _optional_module("core.memory")
llm_client = _optional_module("core.llm_client")
db = _optional_module("core.db")
rag = _optional_module("core.rag")
llm_metrics = _optional_module("core.llm_metrics")
multimodal = _optional_module("core.multimodal")
voice = _optional_module("core.voice")
active_learning = _optional_module("core.active_learning")


LLMClient = _optional_import("core.llm_client", "LLMClient")
ConversationMemory = _optional_import("core.memory", "ConversationMemory")
DocumentStore = _optional_import("core.rag", "DocumentStore")
Database = _optional_import("core.db", "Database")
MultimodalPipeline = _optional_import("core.multimodal", "MultimodalPipeline")
VoicePipeline = _optional_import("core.voice", "VoicePipeline")

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
    MultimodalPipeline,
    VoicePipeline,
    LLMMetricsCollector,
)

# Testlerdeki Mock nesnelerinin __name__ özniteliğine sahip olmaması
# nedeniyle reload sırasında çökmeyi önlemek için statik tanımlama:
__all__ = [
    "ConversationMemory",
    "LLMClient",
    "DocumentStore",
    "Database",
    "MultimodalPipeline",
    "VoicePipeline",
    "LLMMetricsCollector",
    "__version__",
    "MemoryManager",
    "RAGManager",
    "DatabaseManager",
    "get_llm_metrics_collector",
]
