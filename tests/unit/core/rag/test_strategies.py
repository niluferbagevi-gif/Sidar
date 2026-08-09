from __future__ import annotations

from typing import Any

from core.rag.strategies import BM25OnlyStrategy, HybridStrategy, VectorOnlyStrategy


class FakeRagSearchStore:
    def __init__(self) -> None:
        self._pgvector_available = False
        self._chroma_available = False
        self._bm25_available = False
        self.collection: object | None = None
        self.calls: list[tuple[str, str, int, str]] = []
        self.pgvector_results: list[dict[str, Any]] = []
        self.chroma_results: list[dict[str, Any]] = []
        self.bm25_results: list[dict[str, Any]] = []
        self.keyword_response: tuple[bool, str] = (True, "keyword fallback")

    def _pgvector_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("pgvector_search", query, top_k, session_id))
        return True, "pgvector search"

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("chroma_search", query, top_k, session_id))
        return True, "chroma search"

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("bm25_search", query, top_k, session_id))
        return True, "bm25 search"

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("keyword_search", query, top_k, session_id))
        return self.keyword_response

    def _format_results_from_struct(
        self,
        results: list[dict[str, Any]],
        query: str,
        source_name: str,
    ) -> tuple[bool, str]:
        self.calls.append(("format", query, len(results), source_name))
        return True, source_name

    def _fetch_pgvector(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        self.calls.append(("fetch_pgvector", query, top_k, session_id))
        return self.pgvector_results

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        self.calls.append(("fetch_chroma", query, top_k, session_id))
        return self.chroma_results

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        self.calls.append(("fetch_bm25", query, top_k, session_id))
        return self.bm25_results


def test_vector_only_uses_chroma_when_pgvector_disabled_and_collection_ready() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()

    assert VectorOnlyStrategy(store).search("query", 3, "s1") == (True, "chroma search")
    assert store.calls == [("chroma_search", "query", 3, "s1")]


def test_vector_only_reports_unavailable_when_chroma_collection_missing() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = None

    ok, message = VectorOnlyStrategy(store).search("query", 3, "s1")

    assert ok is False
    assert "Vektör arama kullanılamıyor" in message
    assert store.calls == []


def test_bm25_only_reports_unavailable_when_bm25_disabled() -> None:
    store = FakeRagSearchStore()
    store._bm25_available = False

    ok, message = BM25OnlyStrategy(store).search("query", 3, "s1")

    assert ok is False
    assert "BM25 kullanılamıyor" in message
    assert store.calls == []


def test_hybrid_uses_keyword_fallback_when_vector_and_bm25_are_empty() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = False
    store.chroma_results = []
    store.bm25_results = []
    store.keyword_response = (True, "keyword results")

    assert HybridStrategy(store).search("query", 3, "s1") == (True, "keyword results")
    assert store.calls == [
        ("fetch_chroma", "query", 3, "s1"),
        ("fetch_bm25", "query", 3, "s1"),
        ("keyword_search", "query", 3, "s1"),
    ]


def test_hybrid_formats_bm25_only_results_with_chroma_source_when_pgvector_disabled() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = False
    store.chroma_results = []
    store.bm25_results = [{"id": "bm25-1", "content": "body"}]

    assert HybridStrategy(store).search("query", 3, "s1") == (True, "Hibrit RRF (ChromaDB + BM25)")
    assert store.calls[-1] == ("format", "query", 1, "Hibrit RRF (ChromaDB + BM25)")


def test_vector_only_prefers_pgvector_when_available() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()

    assert VectorOnlyStrategy(store).search("query", 3, "s1") == (True, "pgvector search")
    assert store.calls == [("pgvector_search", "query", 3, "s1")]


def test_bm25_only_delegates_when_bm25_available() -> None:
    store = FakeRagSearchStore()
    store._bm25_available = True

    assert BM25OnlyStrategy(store).search("query", 3, "s1") == (True, "bm25 search")
    assert store.calls == [("bm25_search", "query", 3, "s1")]


def test_hybrid_merges_pgvector_and_bm25_results_with_pgvector_source() -> None:
    store = FakeRagSearchStore()
    store._pgvector_available = True
    store.pgvector_results = [{"id": "shared", "content": "vector"}]
    store.bm25_results = [
        {"id": "shared", "content": "bm25 duplicate"},
        {"id": "bm25-only", "content": "bm25"},
    ]

    ok, source_name = HybridStrategy(store).search("query", 5, "s1")

    assert ok is True
    assert source_name == "Hibrit RRF (pgvector + BM25)"
    assert ("fetch_pgvector", "query", 5, "s1") in store.calls
    assert store.calls[-1] == ("format", "query", 2, "Hibrit RRF (pgvector + BM25)")
