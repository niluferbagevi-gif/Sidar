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


def test_fetch_pgvector_returns_empty_when_query_finds_no_rows(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_final_pg_empty_rows")
    store = _new_store(rag_mod, tmp_path)

    class _Result:
        def fetchall(self):
            return []

    class _Conn:
        def execute(self, stmt, params):
            return _Result()

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *args):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    store._pgvector_available = True
    store.pg_engine = _Engine()
    store._pg_table = "rag_embeddings"
    store._pgvector_embed_texts = lambda texts: [[0.1, 0.2] for _ in texts]

    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))

    assert store._fetch_pgvector("needle", top_k=2, session_id="s1") == []


def test_search_sync_bm25_mode_uses_bm25_backend_when_available(tmp_path):
    rag_mod = _load_rag_module("rag_final_bm25_mode")
    store = _new_store(rag_mod, tmp_path)
    store._index = {"doc-1": {"session_id": "s1", "title": "Doc", "source": "src", "tags": []}}
    store._bm25_available = True
    store._bm25_search = lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}")

    assert store._search_sync("needle", top_k=2, mode="bm25", session_id="s1") == (True, "bm25:needle:2:s1")


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


def test_chunk_text_accepts_explicit_chunk_size_larger_than_config(tmp_path):
    rag_mod = _load_rag_module("rag_final_large_explicit_chunk")
    store = _new_store(rag_mod, tmp_path)
    store.cfg.RAG_CHUNK_SIZE = 12
    store.cfg.RAG_CHUNK_OVERLAP = 3

    chunks = store._chunk_text("x" * 40, chunk_size=64, chunk_overlap=5)

    assert chunks == ["x" * 40]


def test_recursive_chunk_text_forces_split_for_oversized_single_word(tmp_path):
    rag_mod = _load_rag_module("rag_final_forced_single_word")
    store = _new_store(rag_mod, tmp_path)

    chunks = store._recursive_chunk_text("x" * 21, size=8, overlap=3)

    assert chunks == ["xxxxxxxx", "xxxxxxxx", "xxxxxxxx", "xxxxxx"]
    assert all(len(chunk) <= 8 for chunk in chunks)


def test_rrf_search_returns_explicit_no_results_when_all_backends_are_empty(tmp_path):
    rag_mod = _load_rag_module("rag_final_total_search_miss")
    store = _new_store(rag_mod, tmp_path)
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = True
    store._index = {}

    store._fetch_chroma = lambda *_a, **_k: []
    store._fetch_bm25 = lambda *_a, **_k: []
    store._keyword_search = lambda query, top_k, session_id: (
        False,
        f"'{query}' için belge deposunda ilgili sonuç bulunamadı.",
    )

    ok, message = store._rrf_search("tam başarısızlık", top_k=3, session_id="s1")

    assert ok is False
    assert "tam başarısızlık" in message
    assert "ilgili sonuç bulunamadı" in message