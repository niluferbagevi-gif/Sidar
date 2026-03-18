import sys
import types
from pathlib import Path

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store


def test_rag_gpu_oom_and_init_failures_fallback_cleanly(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_gap_gpu_oom")

    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")
    ef_mod.SentenceTransformerEmbeddingFunction = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("CUDA out of memory"))
    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch_mod.float16 = "fp16"
    torch_mod.autocast = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("autocast should not run"))

    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    assert mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True) is None

    DocumentStore = mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, name: name == "chromadb")
    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(PersistentClient=lambda **_k: (_ for _ in ()).throw(RuntimeError("chroma init failed"))))

    store = DocumentStore(
        tmp_path / "rag_chroma_fail",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )
    assert store._chroma_available is False


def test_rag_bm25_and_pgvector_init_failures_disable_backends(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_gap_backend_init_fail")
    DocumentStore = mod.DocumentStore

    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _name: True)

    sqlite3_mod = types.ModuleType("sqlite3")
    sqlite3_mod.Row = object
    sqlite3_mod.connect = lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full"))
    monkeypatch.setitem(sys.modules, "sqlite3", sqlite3_mod)

    class _Conn:
        def execute(self, stmt, *_args, **_kwargs):
            if "CREATE EXTENSION IF NOT EXISTS vector" in str(stmt):
                raise RuntimeError("pgvector extension missing")
            return None

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(create_engine=lambda *_a, **_k: _Engine(), text=lambda sql: sql))
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=lambda *_a, **_k: object()))

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=2,
        PGVECTOR_EMBEDDING_MODEL="mini",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    store = DocumentStore(tmp_path / "rag_pgvector_missing_ext", cfg=cfg)
    assert store._pgvector_available is False
    assert store._bm25_available is False


def test_pgvector_helper_early_return_paths_and_formatting(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_gap_pgvector_helpers")
    store = _new_store(mod, tmp_path)

    store._pg_embedding_model = None
    assert store._pgvector_embed_texts(["hello"]) == []

    store._pgvector_available = False
    store.pg_engine = None
    assert store._fetch_pgvector("q", 2, "s1") == []
    store._upsert_pgvector_chunks("d1", "p1", "s1", "t", "src", ["chunk"])
    store._delete_pgvector_parent("p1", "s1")

    deleted = {}

    class _Conn:
        def execute(self, stmt, params):
            deleted["stmt"] = stmt
            deleted["params"] = params
            return None

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    store._pgvector_available = True
    store.pg_engine = _Engine()
    store._pg_table = "rag_embeddings"
    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))
    store._delete_pgvector_parent("parent-1", "session-1")
    assert deleted["params"] == {"parent_id": "parent-1", "session_id": "session-1"}

    seen = {}
    store._fetch_pgvector = lambda query, top_k, session_id: seen.update({"query": query, "top_k": top_k, "session_id": session_id}) or [{"id": "p1", "title": "Doc", "source": "S", "snippet": "N", "score": 0.9}]
    ok, text = store._pgvector_search("needle", 2, "sess")
    assert ok is True
    assert "Vektör Arama (pgvector)" in text
    assert seen == {"query": "needle", "top_k": 2, "session_id": "sess"}


def test_upsert_pgvector_returns_when_embeddings_are_empty(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_gap_pgvector_upsert_empty")
    store = _new_store(mod, tmp_path)

    class _Engine:
        def begin(self):
            raise AssertionError("db begin should not run when vectors are empty")

    store._pgvector_available = True
    store.pg_engine = _Engine()
    store._pgvector_embed_texts = lambda _texts: []
    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))

    store._upsert_pgvector_chunks("d1", "p1", "s1", "Title", "src", ["chunk-1"])


def test_add_document_sync_forwards_pgvector_chunks_and_delete_document_uses_parent_session(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_gap_add_delete_pgvector")
    store = _new_store(mod, tmp_path)

    captured = {}
    store._pgvector_available = True
    store._chunk_text = lambda text: ["part-1", "part-2"]
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None
    store._upsert_pgvector_chunks = lambda doc_id, parent_id, session_id, title, source, chunks: captured.update(
        {
            "doc_id": doc_id,
            "parent_id": parent_id,
            "session_id": session_id,
            "title": title,
            "source": source,
            "chunks": chunks,
        }
    )

    doc_id = store._add_document_sync("Title", "x" * 200, source="src", session_id="tenant-1")
    assert captured["doc_id"] == doc_id
    assert captured["session_id"] == "tenant-1"
    assert captured["chunks"] == ["part-1", "part-2"]

    deleted = {}
    store.collection = None
    store._delete_pgvector_parent = lambda parent_id, session_id: deleted.update({"parent_id": parent_id, "session_id": session_id})
    message = store.delete_document(doc_id, session_id="tenant-1")
    assert "Belge silindi" in message
    assert deleted == {"parent_id": captured["parent_id"], "session_id": "tenant-1"}


def test_validate_url_safe_rejects_invalid_host_and_internal_targets(tmp_path):
    mod = _load_rag_module("rag_gap_validate_url")
    store = _new_store(mod, tmp_path)

    try:
        store._validate_url_safe("file:///tmp/secret.txt")
        raise AssertionError("expected invalid scheme error")
    except ValueError as exc:
        assert "http/https" in str(exc)

    try:
        store._validate_url_safe("https:///missing-host")
        raise AssertionError("expected missing hostname error")
    except ValueError as exc:
        assert "hostname" in str(exc)

    try:
        store._validate_url_safe("http://127.0.0.1/private")
        raise AssertionError("expected internal network error")
    except ValueError as exc:
        assert "İç ağ" in str(exc)

    try:
        store._validate_url_safe("https://localhost/app")
        raise AssertionError("expected blocked host error")
    except ValueError as exc:
        assert "Engellenen hostname" in str(exc)


def test_local_auto_mode_prefers_pgvector_or_chroma_and_falls_back_to_keyword(tmp_path):
    mod = _load_rag_module("rag_gap_local_auto")
    store = _new_store(mod, tmp_path)

    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._index = {"d1": {"session_id": "s1", "title": "Doc", "source": "", "tags": []}}

    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._pgvector_search = lambda *_a, **_k: (True, "pg-only")
    assert store._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "pg-only")

    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._chroma_search = lambda *_a, **_k: (True, "chroma-only")
    assert store._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "chroma-only")

    store._chroma_available = False
    store.collection = None
    store._bm25_available = False
    store._keyword_search = lambda *_a, **_k: (True, "keyword-only")
    assert store._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "keyword-only")


def test_fetch_chroma_and_status_pgvector_paths(tmp_path):
    mod = _load_rag_module("rag_gap_fetch_chroma_status")
    store = _new_store(mod, tmp_path)

    class _Collection:
        def count(self):
            return 10

        def query(self, **kwargs):
            assert kwargs["n_results"] == 4
            assert kwargs["where"] == {"session_id": "s1"}
            return {
                "ids": [["c1", "c2"]],
                "documents": [["chunk-1", "chunk-2"]],
                "metadatas": [[
                    {"parent_id": "p1", "title": "Doc 1", "source": "src"},
                    {"parent_id": "p2", "title": "Doc 2", "source": "src2"},
                ]],
            }

    store.collection = _Collection()
    store.cfg.RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER = 4
    store._is_local_llm_provider = False
    found = store._fetch_chroma("needle", top_k=2, session_id="s1")
    assert [row["id"] for row in found] == ["p1", "p2"]

    store._pgvector_available = True
    store._vector_backend = "pgvector"
    store._index = {"d1": {}}
    status = store.status()
    assert "pgvector" in status
    assert "Motorlar" in status
