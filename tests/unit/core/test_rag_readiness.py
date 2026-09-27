"""``core.rag.readiness`` modülü için unit testler."""

from core.rag.readiness import RAGReadinessState


def test_readiness_ready_requires_vector_and_bm25_backends() -> None:
    """Readiness ready requires vector and bm25 backends."""
    assert RAGReadinessState().ready is False
    assert RAGReadinessState(vector_ready=True, bm25_ready=True).ready is True
