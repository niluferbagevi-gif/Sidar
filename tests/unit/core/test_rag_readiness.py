from pathlib import Path

from core.rag.readiness import RAGReadinessState, build_readiness_report


def test_rag_readiness_state_requires_vector_and_bm25_indexes() -> None:
    state = RAGReadinessState(vector_ready=True, bm25_ready=True)

    assert state.ready is True
    state.bm25_ready = False
    assert state.ready is False


def test_build_readiness_report_marks_database_environment_blocker(tmp_path: Path) -> None:
    report = build_readiness_report(
        rag_dir=tmp_path,
        document_count=3,
        index_exists=True,
        database_env_status="fail",
    )

    assert report == {
        "rag_dir": str(tmp_path),
        "document_count": 3,
        "index_exists": True,
        "blocked_by": "database_env",
        "message": "pgvector backend is blocked until database_env is fixed",
    }
