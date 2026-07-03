"""Search strategy implementations for Sidar's RAG document store."""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RagSearchStore(Protocol):
    """Structural contract required by RAG search strategies."""

    _pgvector_available: bool
    _chroma_available: bool
    _bm25_available: bool
    collection: Any

    def _pgvector_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]: ...

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]: ...

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]: ...

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]: ...

    def _format_results_from_struct(
        self,
        results: list[dict[str, Any]],
        query: str,
        source_name: str,
    ) -> tuple[bool, str]: ...

    def _fetch_pgvector(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]: ...

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]: ...

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]: ...


class VectorOnlyStrategy:
    """Run a single vector backend search with pgvector preferred over ChromaDB."""

    def __init__(self, store: RagSearchStore) -> None:
        self.store = store

    def search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        """Execute vector-only retrieval for the configured document store."""
        if getattr(self.store, "_pgvector_available", False):
            return self.store._pgvector_search(query, top_k, session_id)
        if getattr(self.store, "_chroma_available", False) and getattr(
            self.store, "collection", None
        ):
            return self.store._chroma_search(query, top_k, session_id)
        return False, "Vektör arama kullanılamıyor — pgvector/ChromaDB hazır değil."


class BM25OnlyStrategy:
    """Run a single SQLite FTS/BM25 backend search."""

    def __init__(self, store: RagSearchStore) -> None:
        self.store = store

    def search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        """Execute BM25-only retrieval when the FTS index is available."""
        if getattr(self.store, "_bm25_available", False):
            logger.info(
                "RAG BM25 fallback/search selected: reason=explicit_bm25 mode, session_id=%s",
                session_id,
            )
            return self.store._bm25_search(query, top_k, session_id)
        return False, "BM25 kullanılamıyor — SQLite FTS5 başlatılamadı."


class HybridStrategy:
    """Merge vector and BM25 candidates with reciprocal-rank fusion."""

    def __init__(self, store: RagSearchStore) -> None:
        self.store = store

    def search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        """Execute hybrid vector + BM25 retrieval using reciprocal-rank fusion."""
        vector_results = self._fetch_vector_results(query, top_k, session_id)
        bm25_results = self.store._fetch_bm25(query, top_k, session_id)
        if bm25_results and not vector_results:
            logger.info(
                "RAG BM25 fallback/search selected: reason=vector_candidates_empty, session_id=%s",
                session_id,
            )

        if not vector_results and not bm25_results:
            logger.info(
                "RAG keyword fallback selected: reason=no_vector_or_bm25_candidates, session_id=%s",
                session_id,
            )
            return self.store._keyword_search(query, top_k, session_id)

        k = 60
        rrf_scores: dict[str, float] = {}
        docs_map: dict[str, dict[str, Any]] = {}

        for rank, res in enumerate(vector_results):
            doc_id = res["id"]
            docs_map[doc_id] = dict(res)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, res in enumerate(bm25_results):
            doc_id = res["id"]
            docs_map.setdefault(doc_id, dict(res))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        ranked_docs = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        final_results = []
        for doc_id, score in ranked_docs:
            doc_info = docs_map[doc_id]
            doc_info["score"] = score
            final_results.append(doc_info)

        return self.store._format_results_from_struct(
            final_results,
            query,
            source_name=f"Hibrit RRF ({self._vector_name()} + BM25)",
        )

    def _fetch_vector_results(
        self, query: str, top_k: int, session_id: str
    ) -> list[dict[str, Any]]:
        if getattr(self.store, "_pgvector_available", False):
            return self.store._fetch_pgvector(query, top_k, session_id)
        return self.store._fetch_chroma(query, top_k, session_id)

    def _vector_name(self) -> str:
        return "pgvector" if getattr(self.store, "_pgvector_available", False) else "ChromaDB"
