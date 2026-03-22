import sys
import types

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store

def test_add_document_from_file_rejects_empty_text_files(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_final_empty_file")
    store = _new_store(rag_mod, tmp_path)
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   \n\n", encoding="utf-8")

    monkeypatch.setattr(rag_mod.Config, "BASE_DIR", tmp_path, raising=False)

    ok, message = store.add_document_from_file(str(empty_file))

    assert ok is False
    assert "Dosya boş" in message

def test_search_sync_vector_mode_prefers_chroma_when_available(tmp_path):
    rag_mod = _load_rag_module("rag_final_vector_chroma")
    store = _new_store(rag_mod, tmp_path)
    store._index = {"doc-1": {"session_id": "s1", "title": "Doc", "source": "src", "tags": []}}
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._chroma_search = lambda query, top_k, session_id: (True, f"chroma:{query}:{top_k}:{session_id}")

    assert store._search_sync("needle", top_k=2, mode="vector", session_id="s1") == (True, "chroma:needle:2:s1")

def test_fetch_pgvector_returns_empty_on_connection_drop(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_final_pg_disconnect")
    store = _new_store(rag_mod, tmp_path)
    warnings = []

    class _BrokenEngine:
        def begin(self):
            raise ConnectionError("pgvector socket closed")

    store._pgvector_available = True
    store.pg_engine = _BrokenEngine()
    store._pgvector_embed_texts = lambda texts: [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(rag_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))
    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))

    assert store._fetch_pgvector("needle", top_k=2, session_id="s1") == []
    assert any("pgvector arama hatası" in msg and "socket closed" in msg for msg in warnings)

def test_search_sync_auto_falls_back_to_keyword_when_chroma_disconnects(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_final_chroma_fallback")
    store = _new_store(rag_mod, tmp_path)
    warnings = []

    store._index = {"doc-1": {"session_id": "s1", "title": "Doc", "source": "src", "tags": []}}
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = False

    monkeypatch.setattr(store, "_chroma_search", lambda *_a, **_k: (_ for _ in ()).throw(ConnectionError("chroma transport lost")))
    monkeypatch.setattr(store, "_keyword_search", lambda query, top_k, session_id: (True, f"keyword:{query}:{top_k}:{session_id}"))
    monkeypatch.setattr(rag_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    ok, text = store._search_sync("fallback query", top_k=3, mode="auto", session_id="s1")

    assert ok is True
    assert text == "keyword:fallback query:3:s1"
    assert any("ChromaDB arama hatası" in msg and "transport lost" in msg for msg in warnings)

def test_chunk_text_handles_overlap_larger_than_chunk_size_without_overflow(tmp_path):
    rag_mod = _load_rag_module("rag_final_chunk_bounds")
    store = _new_store(rag_mod, tmp_path)

    chunks = store._chunk_text("abcdef", chunk_size=1, chunk_overlap=5)

    assert len(chunks) == 6
    assert chunks[0] == "a"
    assert chunks[-1] == "abcdef"
    assert chunks[-1].endswith("f")