from core.rag.readiness import RAGReadinessState


def test_readiness_ready_requires_vector_and_bm25_backends() -> None:
    assert RAGReadinessState().ready is False
    assert RAGReadinessState(vector_ready=True, bm25_ready=True).ready is True
