"""RAG readiness helpers shared across initialization and health checks."""

from dataclasses import dataclass


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
