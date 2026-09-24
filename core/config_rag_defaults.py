"""RAG and semantic-cache defaults for Sidar configuration."""

from __future__ import annotations

SEMANTIC_CACHE_THRESHOLD_DEFAULT: float = 0.90
RAG_TOP_K_DEFAULT: int = 3
RAG_CHUNK_SIZE_DEFAULT: int = 1000
RAG_CHUNK_OVERLAP_DEFAULT: int = 200
RAG_FILE_THRESHOLD_DEFAULT: int = 20_000
