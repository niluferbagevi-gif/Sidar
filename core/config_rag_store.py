"""RAG document-store and vector-backend settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

import config_rag
from core.config_env_helpers import get_int_env, get_web_scrape_max_chars


@dataclass(frozen=True)
class RagStoreSettings:
    """Document-store and pgvector settings used by RAG components."""

    web_fetch_max_chars: int
    web_scrape_max_chars: int
    rag_top_k: int
    rag_chunk_size: int
    rag_chunk_overlap: int
    rag_file_threshold: int
    rag_vector_backend: str
    pgvector_table: str
    pgvector_embedding_dim: int
    pgvector_embedding_model: str


def load_rag_store_settings() -> RagStoreSettings:
    """Load RAG store and scrape limit settings from environment variables."""
    web_fetch_max_chars = get_int_env("WEB_FETCH_MAX_CHARS", 12000)
    return RagStoreSettings(
        web_fetch_max_chars=web_fetch_max_chars,
        web_scrape_max_chars=get_web_scrape_max_chars(web_fetch_max_chars),
        rag_top_k=get_int_env("RAG_TOP_K", config_rag.RAG_TOP_K_DEFAULT),
        rag_chunk_size=get_int_env("RAG_CHUNK_SIZE", config_rag.RAG_CHUNK_SIZE_DEFAULT),
        rag_chunk_overlap=get_int_env("RAG_CHUNK_OVERLAP", config_rag.RAG_CHUNK_OVERLAP_DEFAULT),
        rag_file_threshold=get_int_env("RAG_FILE_THRESHOLD", config_rag.RAG_FILE_THRESHOLD_DEFAULT),
        rag_vector_backend=os.getenv("RAG_VECTOR_BACKEND", "chroma"),
        pgvector_table=os.getenv("PGVECTOR_TABLE", "rag_embeddings"),
        pgvector_embedding_dim=get_int_env("PGVECTOR_EMBEDDING_DIM", 384),
        pgvector_embedding_model=os.getenv("PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    )
