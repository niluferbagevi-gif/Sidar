"""
Sidar Project — Core Modülleri

Bu paket ajan altyapısının temel bileşenlerini dışa aktarır:
- ConversationMemory : Thread-safe, kalıcı ve opsiyonel Fernet şifrelemeli konuşma belleği
- LLMClient         : Ollama ve Gemini için asenkron, streaming LLM istemcisi
- DocumentStore     : ChromaDB + BM25 + Keyword hibrit RAG belgesi deposu
"""

__version__ = "2.7.0"

from .llm_client import LLMClient
from .memory import ConversationMemory
from .rag import DocumentStore

# Geriye dönük/kolaylaştırıcı alias'lar
MemoryManager = ConversationMemory
RAGManager = DocumentStore

# Tek kaynak: core dışına açılacak sınıf sembolleri burada tutulur.
_EXPORTED_CORE_SYMBOLS = (
    ConversationMemory,
    LLMClient,
    DocumentStore,
)

__all__ = [sym.__name__ for sym in _EXPORTED_CORE_SYMBOLS] + ["__version__"]
__all__ += ["MemoryManager", "RAGManager"]
