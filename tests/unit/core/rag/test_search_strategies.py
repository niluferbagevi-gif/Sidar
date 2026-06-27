"""Unit coverage for RAG search strategy objects."""

from __future__ import annotations

from core.rag.strategies import BM25OnlyStrategy, HybridStrategy, VectorOnlyStrategy


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str]] = []
        self._pgvector_available = False
        self._chroma_available = False
        self._bm25_available = False
        self.collection = None
        self.pgvector_results: list[dict[str, object]] = []
        self.chroma_results: list[dict[str, object]] = []
        self.bm25_results: list[dict[str, object]] = []

    def _pgvector_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("pgvector_search", query, top_k, session_id))
        return True, "pgvector"

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("chroma_search", query, top_k, session_id))
        return True, "chroma"

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("bm25_search", query, top_k, session_id))
        return True, "bm25"

    def _fetch_pgvector(self, query: str, top_k: int, session_id: str) -> list[dict[str, object]]:
        self.calls.append(("fetch_pgvector", query, top_k, session_id))
        return self.pgvector_results

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list[dict[str, object]]:
        self.calls.append(("fetch_chroma", query, top_k, session_id))
        return self.chroma_results

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list[dict[str, object]]:
        self.calls.append(("fetch_bm25", query, top_k, session_id))
        return self.bm25_results

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        self.calls.append(("keyword_search", query, top_k, session_id))
        return False, "keyword fallback"

    def _format_results_from_struct(
        self, results: list[dict[str, object]], query: str, source_name: str
    ) -> tuple[bool, str]:
        ordered_ids = ",".join(str(item["id"]) for item in results)
        return True, f"{source_name}:{query}:{ordered_ids}"


def _doc(doc_id: str) -> dict[str, object]:
    return {"id": doc_id, "title": doc_id, "source": "", "snippet": doc_id}


def test_vector_strategy_prefers_pgvector() -> None:
    store = FakeStore()
    store._pgvector_available = True

    result = VectorOnlyStrategy(store).search("q", 3, "s")

    assert result == (True, "pgvector")
    assert store.calls == [("pgvector_search", "q", 3, "s")]


def test_vector_strategy_uses_chroma_when_pgvector_unavailable() -> None:
    store = FakeStore()
    store._chroma_available = True
    store.collection = object()

    result = VectorOnlyStrategy(store).search("q", 2, "s")

    assert result == (True, "chroma")
    assert store.calls == [("chroma_search", "q", 2, "s")]


def test_bm25_strategy_reports_unavailable_index() -> None:
    store = FakeStore()

    result = BM25OnlyStrategy(store).search("q", 2, "s")

    assert result == (False, "BM25 kullanılamıyor — SQLite FTS5 başlatılamadı.")
    assert store.calls == []


def test_hybrid_strategy_merges_vector_and_bm25_with_rrf() -> None:
    store = FakeStore()
    store._pgvector_available = True
    store._bm25_available = True
    store.pgvector_results = [_doc("shared"), _doc("vector-only")]
    store.bm25_results = [_doc("shared"), _doc("bm25-only")]

    result = HybridStrategy(store).search("sidar", 3, "global")

    assert result == (True, "Hibrit RRF (pgvector + BM25):sidar:shared,vector-only,bm25-only")
    assert store.calls == [
        ("fetch_pgvector", "sidar", 3, "global"),
        ("fetch_bm25", "sidar", 3, "global"),
    ]


def test_hybrid_strategy_falls_back_to_keyword_when_no_candidates() -> None:
    store = FakeStore()
    store._bm25_available = True

    result = HybridStrategy(store).search("missing", 5, "global")

    assert result == (False, "keyword fallback")
    assert store.calls == [
        ("fetch_chroma", "missing", 5, "global"),
        ("fetch_bm25", "missing", 5, "global"),
        ("keyword_search", "missing", 5, "global"),
    ]


def test_hybrid_strategy_logs_when_bm25_is_only_available_candidate(caplog) -> None:
    store = FakeStore()
    store._bm25_available = True
    store.bm25_results = [_doc("bm25-only")]

    with caplog.at_level("INFO", logger="core.rag.strategies"):
        result = HybridStrategy(store).search("sidar", 2, "s1")

    assert result == (True, "Hibrit RRF (ChromaDB + BM25):sidar:bm25-only")
    assert "reason=vector_candidates_empty" in caplog.text


def test_bm25_strategy_logs_explicit_fallback_selection(caplog) -> None:
    store = FakeStore()
    store._bm25_available = True

    with caplog.at_level("INFO", logger="core.rag.strategies"):
        result = BM25OnlyStrategy(store).search("sidar", 2, "s1")

    assert result == (True, "bm25")
    assert "reason=explicit_bm25 mode" in caplog.text
