"""Integration coverage for RAG backend switching consistency."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.rag import DocumentStore


@pytest.mark.asyncio
async def test_rag_auto_search_switches_pgvector_chroma_bm25_consistently(tmp_path) -> None:
    cfg = SimpleNamespace(
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        RAG_LOCAL_ENABLE_HYBRID=False,
        AI_PROVIDER="openai",
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=16,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="postgresql://user:pass@localhost/db",
    )
    store = DocumentStore(tmp_path / "rag_switch", cfg=cfg, initialize_vector=False)
    store._add_document_sync(
        "Switch Doc", "alpha beta gamma", source="test://switch", session_id="s1"
    )

    store._vector_backend = "pgvector"
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._pgvector_search = lambda q, k, s: (True, f"pg:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._chroma_search = lambda q, k, s: (True, f"chroma:{q}:{k}:{s}")  # type: ignore[method-assign]

    assert await store.search("alpha", 2, mode="auto", session_id="s1") == (True, "pg:alpha:2:s1")

    store._pgvector_available = False
    store._vector_backend = "chroma"
    assert await store.search("alpha", 2, mode="auto", session_id="s1") == (
        True,
        "chroma:alpha:2:s1",
    )

    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    ok, message = await store.search("alpha", 2, mode="auto", session_id="s1")

    assert ok is True
    assert "BM25" in message
    assert "Switch Doc" in message


@pytest.mark.asyncio
async def test_rag_auto_search_falls_through_failed_vectors_to_bm25(tmp_path) -> None:
    cfg = SimpleNamespace(
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        RAG_LOCAL_ENABLE_HYBRID=False,
        AI_PROVIDER="openai",
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=16,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="postgresql://user:pass@localhost/db",
    )
    store = DocumentStore(tmp_path / "rag_failover", cfg=cfg, initialize_vector=False)
    store._add_document_sync(
        "Fallback Doc", "delta epsilon", source="test://fallback", session_id="s1"
    )
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._vector_backend = "pgvector"
    store._pgvector_search = lambda *_args: (_ for _ in ()).throw(RuntimeError("pg down"))  # type: ignore[method-assign]
    store._chroma_search = lambda *_args: (_ for _ in ()).throw(RuntimeError("chroma down"))  # type: ignore[method-assign]
    store._fetch_pgvector = lambda *_args: (_ for _ in ()).throw(RuntimeError("pg fetch down"))  # type: ignore[method-assign]
    store._fetch_chroma = lambda *_args: (_ for _ in ()).throw(RuntimeError("chroma fetch down"))  # type: ignore[method-assign]

    ok, message = await store.search("delta", 2, mode="auto", session_id="s1")

    assert ok is True
    assert "BM25" in message
    assert "Fallback Doc" in message
