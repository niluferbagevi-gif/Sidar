"""Backward-compatible import shim for RAG configuration defaults.

New code should import ``config_rag_defaults`` to avoid confusing these static
configuration defaults with ``core.config_rag_store`` runtime store settings or
``core.rag`` RAG implementation modules.
"""

from __future__ import annotations

from config_rag_defaults import (  # noqa: F401 - re-exported compatibility surface.
    RAG_CHUNK_OVERLAP_DEFAULT,
    RAG_CHUNK_SIZE_DEFAULT,
    RAG_FILE_THRESHOLD_DEFAULT,
    RAG_TOP_K_DEFAULT,
    SEMANTIC_CACHE_THRESHOLD_DEFAULT,
)
