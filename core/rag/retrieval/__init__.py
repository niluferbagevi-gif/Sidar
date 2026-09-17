"""Retrieval orchestration helpers for the RAG compatibility facade."""

from core.rag.retrieval.store_registry import SharedStoreRegistry, build_store_cache_key

__all__ = ["SharedStoreRegistry", "build_store_cache_key"]
