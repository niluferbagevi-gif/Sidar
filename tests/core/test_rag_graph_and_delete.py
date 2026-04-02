from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from core.rag import DocumentStore


class _DummyCollection:
    def __init__(self) -> None:
        self.deleted_where = None

    def delete(self, where):
        self.deleted_where = where


class _DummyGraph:
    def __init__(self) -> None:
        self.rebuild_called_with = None

    def rebuild(self, root):
        self.rebuild_called_with = root
        return {"nodes": 4, "edges": 7}


def test_delete_document_removes_index_and_chroma_records(tmp_path):
    store = DocumentStore.__new__(DocumentStore)
    collection = _DummyCollection()

    store._index = {
        "doc-1": {"title": "Plan", "session_id": "global", "parent_id": "parent-1"}
    }
    store._write_lock = threading.RLock()
    store.store_dir = tmp_path
    (tmp_path / "doc-1.txt").write_text("hello", encoding="utf-8")
    store._chroma_available = True
    store.collection = collection
    store._pgvector_available = False
    store._bm25_available = False
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None

    result = store.delete_document("doc-1", session_id="global")

    assert "Belge silindi" in result
    assert "doc-1" not in store._index
    assert collection.deleted_where == {"parent_id": "parent-1"}
    assert not (tmp_path / "doc-1.txt").exists()


def test_search_sync_auto_falls_back_to_bm25_when_rrf_raises(monkeypatch):
    store = DocumentStore.__new__(DocumentStore)
    store.cfg = SimpleNamespace(RAG_TOP_K=3)
    store.default_top_k = 3
    store._index = {"doc-1": {"session_id": "global"}}
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = False

    monkeypatch.setattr(store, "_rrf_search", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rrf fail")))
    monkeypatch.setattr(store, "_bm25_search", lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}"))

    ok, payload = store._search_sync("dependency graph", mode="auto", session_id="global")

    assert ok is True
    assert payload == "bm25:dependency graph:3:global"


def test_rebuild_graph_index_marks_graph_ready_and_reports_summary(tmp_path):
    store = DocumentStore.__new__(DocumentStore)
    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_index = _DummyGraph()
    store._graph_ready = False

    ok, message = store.rebuild_graph_index()

    assert ok is True
    assert "nodes=4" in message
    assert "edges=7" in message
    assert store._graph_index.rebuild_called_with == tmp_path.resolve()
    assert store._graph_ready is True
