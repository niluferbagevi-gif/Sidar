"""RAG readiness helpers shared across initialization and health checks."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RAGReadinessState:
    """Mutable readiness snapshot used by startup/health probes."""

    vector_ready: bool = False
    bm25_ready: bool = False
    graph_ready: bool = False

    @property
    def ready(self) -> bool:
        return self.vector_ready and self.bm25_ready


__all__ = ["RAGReadinessState"]


def build_readiness_report(
    *,
    rag_dir: Path,
    document_count: int,
    index_exists: bool,
    database_env_status: str = "pass",
) -> dict[str, Any]:
    """Return doctor-facing readiness payload with stable keys."""
    blocked_by = "database_env" if database_env_status == "fail" else None
    message = (
        "pgvector backend is blocked until database_env is fixed"
        if blocked_by
        else "RAG readiness calculated"
    )
    return {
        "rag_dir": str(rag_dir),
        "document_count": int(document_count),
        "index_exists": bool(index_exists),
        "blocked_by": blocked_by,
        "message": message,
    }


__all__.append("build_readiness_report")
