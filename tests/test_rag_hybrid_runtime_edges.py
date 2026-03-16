from types import SimpleNamespace
from pathlib import Path

from core.rag import DocumentStore


def _mk_cfg(**overrides):
    base = dict(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
        RAG_VECTOR_BACKEND="chroma",
        DATABASE_URL="sqlite+aiosqlite:///tmp.db",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _store_without_external_backends(tmp_path: Path, cfg=None):
    old = DocumentStore._check_import
    try:
        DocumentStore._check_import = lambda self, _name: False
        return DocumentStore(tmp_path / "rag", cfg=cfg or _mk_cfg())
    finally:
        DocumentStore._check_import = old


def test_pgvector_backend_init_stays_disabled_when_deps_missing(tmp_path):
    store = _store_without_external_backends(
        tmp_path,
        cfg=_mk_cfg(RAG_VECTOR_BACKEND="pgvector", DATABASE_URL="postgresql://u:p@localhost/db"),
    )

    assert store._chroma_available is False
    assert store._pgvector_available is False


def test_rrf_search_falls_back_to_keyword_when_sources_are_empty(tmp_path, monkeypatch):
    store = _store_without_external_backends(tmp_path)

    monkeypatch.setattr(store, "_fetch_chroma", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(store, "_fetch_bm25", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(store, "_keyword_search", lambda *_args, **_kwargs: (True, "kw-fallback"))

    assert store._rrf_search("q", 3, "s1") == (True, "kw-fallback")


def test_rrf_search_merges_vector_and_bm25_without_duplicate_loss(tmp_path, monkeypatch):
    store = _store_without_external_backends(tmp_path)
    vector = [{"id": "A", "title": "A", "source": "v", "snippet": "a", "score": 1.0}]
    bm25 = [
        {"id": "A", "title": "A", "source": "b", "snippet": "a", "score": 0.9},
        {"id": "B", "title": "B", "source": "b", "snippet": "b", "score": 0.8},
    ]

    monkeypatch.setattr(store, "_fetch_chroma", lambda *_args, **_kwargs: vector)
    monkeypatch.setattr(store, "_fetch_bm25", lambda *_args, **_kwargs: bm25)

    captured = {}

    def _fmt(results, query, source_name):
        captured["ids"] = [r["id"] for r in results]
        captured["source"] = source_name
        return True, "ok"

    monkeypatch.setattr(store, "_format_results_from_struct", _fmt)

    ok, _ = store._rrf_search("q", 2, "s1")
    assert ok is True
    assert captured["ids"] == ["A", "B"]
    assert "Hibrit RRF" in captured["source"]


def test_fetch_pgvector_returns_empty_on_runtime_failures(tmp_path, monkeypatch):
    store = _store_without_external_backends(tmp_path)
    store._pgvector_available = True
    store.pg_engine = object()

    monkeypatch.setattr(store, "_pgvector_embed_texts", lambda *_args, **_kwargs: [])
    assert store._fetch_pgvector("q", 3, "s1") == []
