"""Runtime RAG readiness is independent from metadata seed success."""

from __future__ import annotations

from core.rag import DocumentStore


def _store(*, vector_ready: bool, bm25_ready: bool, seeded: bool = True) -> DocumentStore:
    store = DocumentStore.__new__(DocumentStore)
    store._vector_backend = "pgvector"
    store._pgvector_available = vector_ready
    store._bm25_available = bm25_ready
    store._bm25_init_done = bm25_ready
    store._vector_initialization_enabled = vector_ready
    store._graph_rag_enabled = True
    store._graph_ready = False
    store._entity_graph = {"nodes": [{"id": "entity"}]} if seeded else {}
    store._index = {"doc": {"title": "seeded metadata"}} if seeded else {}
    return store


def test_metadata_seed_does_not_claim_vector_runtime_readiness() -> None:
    report = _store(vector_ready=False, bm25_ready=True).runtime_readiness_report()

    assert report["metadata_seeded"] is True
    assert report["ready"] is False
    assert report["components"]["rag_vector"]["status"] == "unavailable"
    assert report["components"]["rag_bm25"]["status"] == "healthy"


def test_runtime_readiness_requires_vector_and_bm25() -> None:
    report = _store(vector_ready=True, bm25_ready=True).runtime_readiness_report()

    assert report["ready"] is True
    assert report["document_count"] == 1
    assert report["components"]["rag_vector"]["backend"] == "pgvector"


def test_runtime_readiness_chroma_ready_with_collection() -> None:
    store = _store(vector_ready=False, bm25_ready=True)
    store._vector_backend = "chroma"
    store._chroma_available = True
    store.collection = object()

    report = store.runtime_readiness_report()

    assert report["ready"] is True
    assert report["components"]["rag_vector"] == {
        "healthy": True,
        "status": "healthy",
        "backend": "chroma",
    }


def test_runtime_readiness_chroma_unavailable_without_collection() -> None:
    store = _store(vector_ready=False, bm25_ready=True)
    store._vector_backend = "chroma"
    store._chroma_available = True
    store.collection = None

    report = store.runtime_readiness_report()

    assert report["ready"] is False
    assert report["components"]["rag_vector"] == {
        "healthy": False,
        "status": "unavailable",
        "backend": "chroma",
    }
