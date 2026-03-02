"""
Sidar Project — Core Modülleri

Bu paket ajan altyapısının temel bileşenlerini dışa aktarır:
- ConversationMemory : Thread-safe, kalıcı ve opsiyonel Fernet şifrelemeli konuşma belleği
- LLMClient         : Ollama ve Gemini için asenkron, streaming LLM istemcisi
- DocumentStore     : ChromaDB + BM25 + Keyword hibrit RAG belgesi deposu
"""

__version__ = "2.6.1"

from .memory import ConversationMemory
from .llm_client import LLMClient
from .rag import DocumentStore

__all__ = ["ConversationMemory", "LLMClient", "DocumentStore", "__version__"] 