import importlib.util
import sys
import types
from pathlib import Path


def _load_rag_module(module_name: str = "rag_edge_under_test"):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 80
        RAG_CHUNK_OVERLAP = 20
        RAG_VECTOR_BACKEND = "chroma"
        AI_PROVIDER = "openai"
        RAG_LOCAL_ENABLE_HYBRID = False
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False
        DATABASE_URL = ""
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

    cfg_mod.Config = _Cfg
    prev_cfg = sys.modules.get("config")
    sys.modules["config"] = cfg_mod
    try:
        spec = importlib.util.spec_from_file_location(module_name, Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev_cfg is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev_cfg


def test_build_embedding_function_import_error_falls_back_to_none(monkeypatch):
    rag_mod = _load_rag_module("rag_edge_embedding")

    real_import = __import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("chromadb") or name == "torch":
            raise ImportError("missing for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _blocked_import)
    assert rag_mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True) is None


def test_pgvector_backend_missing_dependency_disables_engine(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pgvector")
    DocumentStore = rag_mod.DocumentStore

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=80,
        RAG_CHUNK_OVERLAP=20,
        RAG_VECTOR_BACKEND="pgvector",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=384,
        PGVECTOR_EMBEDDING_MODEL="all-MiniLM-L6-v2",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    def _fake_check_import(self, module_name: str) -> bool:
        return module_name == "chromadb"

    monkeypatch.setattr(DocumentStore, "_check_import", _fake_check_import)
    store = DocumentStore(tmp_path / "rag_pgvector_missing", cfg=cfg)

    assert store._vector_backend == "pgvector"
    assert store._pgvector_available is False
    assert store._chroma_available is False


def test_recursive_chunk_text_handles_very_long_single_token(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_chunk")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(tmp_path / "rag_chunk", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))
    chunks = store._recursive_chunk_text("x" * 10_000, size=64, overlap=8)

    assert len(chunks) > 100
    assert all(len(chunk) <= 64 for chunk in chunks)


def test_fetch_pgvector_gracefully_handles_malformed_embedding_result(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pg_fetch")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(tmp_path / "rag_pg_fetch", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))

    store._pgvector_available = True
    store.pg_engine = object()
    store._pgvector_embed_texts = lambda _texts: []

    assert store._fetch_pgvector("test", top_k=3, session_id="s1") == []



def test_embed_texts_semantic_cache_missing_dependency_returns_empty(monkeypatch):
    rag_mod = _load_rag_module("rag_edge_semantic_cache")

    real_import = __import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers":
            raise ImportError("missing sentence_transformers")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _blocked_import)
    assert rag_mod.embed_texts_for_semantic_cache(["alpha", "beta"]) == []


def test_document_store_missing_chromadb_module_falls_back(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_missing_chromadb")
    DocumentStore = rag_mod.DocumentStore

    monkeypatch.setitem(sys.modules, "chromadb", None)
    store = DocumentStore(
        tmp_path / "rag_no_chromadb",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    assert store._chroma_available is False


def test_chunk_text_forces_split_on_very_long_single_word(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_chunk_word")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_chunk_word",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=50, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    chunks = store._chunk_text("z" * 5000)
    assert len(chunks) > 50
    assert all(1 <= len(c) <= 50 for c in chunks)


def test_search_auto_falls_back_when_chroma_query_raises(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_query_fail")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_query_fail",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=60, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    doc_id = "d1"
    content = "needle inside content"
    (tmp_path / "rag_query_fail" / f"{doc_id}.txt").write_text(content, encoding="utf-8")
    store._index = {doc_id: {"title": "Doc", "source": "", "tags": [], "session_id": "s1"}}

    class _BrokenCollection:
        def count(self):
            return 1

        def query(self, **_kwargs):
            raise RuntimeError("collection dropped")

    store.collection = _BrokenCollection()
    store._chroma_available = True
    store._bm25_available = False

    ok, out = store._search_sync("needle", top_k=2, mode="auto", session_id="s1")
    assert ok is True
    assert "needle" in out.lower()



def test_pgvector_init_and_upsert_paths_with_stubbed_dependencies(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pgvector_init")
    DocumentStore = rag_mod.DocumentStore

    class _Conn:
        def __init__(self):
            self.executed = []

        def execute(self, stmt, params=None):
            self.executed.append((str(stmt), params))

    class _Begin:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self._conn

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def __init__(self):
            self.conn = _Conn()

        def begin(self):
            return _Begin(self.conn)

    fake_engine = _Engine()

    sqlalchemy_mod = types.SimpleNamespace(
        create_engine=lambda *_a, **_k: fake_engine,
        text=lambda s: s,
    )

    class _SentenceTransformer:
        def __init__(self, _model_name):
            pass

        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_mod)
    monkeypatch.setitem(sys.modules, "pgvector", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_SentenceTransformer))
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _m: True)

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=2,
        PGVECTOR_EMBEDDING_MODEL="stub",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    store = DocumentStore(tmp_path / "rag_pgvector_init", cfg=cfg)
    assert store._pgvector_available is True

    store._upsert_pgvector_chunks(
        doc_id="doc1",
        parent_id="parent1",
        session_id="s1",
        title="T",
        source="src",
        chunks=["chunk-a", "chunk-b"],
    )

    assert any("INSERT INTO rag_embeddings" in stmt for stmt, _ in fake_engine.conn.executed)


def test_pgvector_upsert_and_delete_exception_paths_are_swallowed(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pgvector_exceptions")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_pgvector_ex",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    store._pgvector_available = True

    class _BoomEngine:
        def begin(self):
            raise RuntimeError("db down")

    store.pg_engine = _BoomEngine()

    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda s: s))
    store._pgvector_embed_texts = lambda texts: [[0.1] for _ in texts]

    # should not raise
    store._upsert_pgvector_chunks("d1", "p1", "s1", "t", "src", ["x"])
    store._delete_pgvector_parent("p1", "s1")



def test_rag_module_sets_otel_trace_none_when_opentelemetry_missing(monkeypatch):
    real_import = __import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("opentelemetry"):
            raise ImportError("otel missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _blocked_import)
    rag_mod = _load_rag_module("rag_edge_no_otel")
    assert rag_mod._otel_trace is None


def test_embed_texts_semantic_cache_empty_input_short_circuit():
    rag_mod = _load_rag_module("rag_edge_semantic_empty")
    assert rag_mod.embed_texts_for_semantic_cache([]) == []


def test_embed_texts_semantic_cache_success_with_tolist_and_iterable(monkeypatch):
    rag_mod = _load_rag_module("rag_edge_semantic_success")

    class _WithToList:
        def __init__(self, data):
            self._data = data

        def tolist(self):
            return self._data

    class _SentenceTransformer:
        def __init__(self, _model_name):
            pass

        def encode(self, texts, normalize_embeddings=True):
            return _WithToList([[0.1, 0.2] for _ in texts])

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_SentenceTransformer))
    vecs = rag_mod.embed_texts_for_semantic_cache(["a", "b"])
    assert vecs == [[0.1, 0.2], [0.1, 0.2]]

    class _SentenceTransformerList:
        def __init__(self, _model_name):
            pass

        def encode(self, texts, normalize_embeddings=True):
            return [(0.3, 0.4) for _ in texts]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_SentenceTransformerList))
    vecs2 = rag_mod.embed_texts_for_semantic_cache(["x"])
    assert vecs2 == [[0.3, 0.4]]


def test_search_auto_fallback_chain_recovers_to_bm25(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_fallback_chain")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_fallback_chain",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    store._index = {"d1": {"session_id": "s1", "title": "Doc", "source": "", "tags": []}}
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = True

    def _boom_rrf(*_a, **_k):
        raise RuntimeError("rrf boom")

    def _boom_pg(*_a, **_k):
        raise RuntimeError("pg boom")

    def _boom_chroma(*_a, **_k):
        raise RuntimeError("chroma boom")

    store._rrf_search = _boom_rrf
    store._pgvector_search = _boom_pg
    store._chroma_search = _boom_chroma
    store._bm25_search = lambda *_a, **_k: (True, "bm25-fallback")

    assert store._search_sync("needle", top_k=2, mode="auto", session_id="s1") == (True, "bm25-fallback")


def test_fetch_chroma_uses_count_exception_fallback_and_session_filter(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_chroma_count_fail")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_chroma_count_fail",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    seen = {}

    class _Collection:
        def count(self):
            raise RuntimeError("count failed")

        def query(self, **kwargs):
            seen.update(kwargs)
            return {
                "ids": [["c1", "c2"]],
                "documents": [["chunk 1", "chunk 2"]],
                "metadatas": [[
                    {"parent_id": "p1", "title": "T1", "source": "s"},
                    {"parent_id": "p2", "title": "T2", "source": "s"},
                ]],
            }

    store.collection = _Collection()
    out = store._fetch_chroma("hello", top_k=2, session_id="session-x")

    assert len(out) == 2
    assert seen["where"] == {"session_id": "session-x"}
    assert seen["n_results"] == 4


def test_chunk_text_prefers_explicit_args_over_config(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_chunk_config_override")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_chunk_config_override",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=100, RAG_CHUNK_OVERLAP=30, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    chunks = store._chunk_text("a" * 120, chunk_size=40, chunk_overlap=5)
    assert chunks
    assert all(len(c) <= 40 for c in chunks)


def test_search_auto_local_provider_prefers_single_engine(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_local_auto")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
        AI_PROVIDER="ollama",
        RAG_LOCAL_ENABLE_HYBRID=False,
    )
    store = DocumentStore(tmp_path / "rag_local_auto", cfg=cfg)

    store._index = {"d1": {"session_id": "s1", "title": "Doc", "source": "", "tags": []}}
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._bm25_search = lambda *_a, **_k: (True, "bm25-local")

    assert store._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "bm25-local")

def test_fetch_pgvector_deduplicates_parent_rows_and_uses_local_limit(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pg_fetch_success")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_pg_fetch_success",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    seen = {}

    class _Result:
        def fetchall(self):
            return [
                types.SimpleNamespace(parent_id="p1", title="Doc 1", source="src", chunk_content="chunk-1", distance=0.2),
                types.SimpleNamespace(parent_id="p1", title="Doc 1 dupe", source="src", chunk_content="chunk-1b", distance=0.1),
                types.SimpleNamespace(parent_id="p2", title=None, source=None, chunk_content=None, distance=1.4),
            ]

    class _Conn:
        def execute(self, stmt, params):
            seen["stmt"] = stmt
            seen["params"] = params
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
    store._is_local_llm_provider = True
    store._pgvector_embed_texts = lambda texts: [[0.1, 0.2] for _ in texts]

    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))

    out = store._fetch_pgvector("needle", top_k=2, session_id="s1")

    assert [row["id"] for row in out] == ["p1", "p2"]
    assert out[0]["score"] == 0.8
    assert out[1]["title"] == "?"
    assert out[1]["source"] == ""
    assert out[1]["snippet"] == ""
    assert out[1]["score"] == 0.0
    assert seen["params"]["lim"] == 4
    assert seen["params"]["session_id"] == "s1"
    assert seen["params"]["qvec"] == "[0.10000000,0.20000000]"


def test_fetch_pgvector_returns_empty_and_warns_on_engine_error(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pg_fetch_error")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(
        tmp_path / "rag_pg_fetch_error",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    warnings = []

    class _BoomEngine:
        def begin(self):
            raise RuntimeError("db read failed")

    store._pgvector_available = True
    store.pg_engine = _BoomEngine()
    store._pgvector_embed_texts = lambda texts: [[0.1] for _ in texts]

    monkeypatch.setattr(rag_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))
    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(text=lambda sql: sql))

    assert store._fetch_pgvector("needle", top_k=2, session_id="s1") == []
    assert any("pgvector arama hatası" in msg for msg in warnings)


def test_pgvector_init_failure_disables_backend_when_embedding_model_load_fails(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pg_init_fail")
    DocumentStore = rag_mod.DocumentStore

    errors = []

    class _Conn:
        def execute(self, *_args, **_kwargs):
            return None

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *args):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _name: True)
    monkeypatch.setattr(rag_mod.logger, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setitem(sys.modules, "sqlalchemy", types.SimpleNamespace(create_engine=lambda *_a, **_k: _Engine(), text=lambda sql: sql))

    class _BrokenSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("model load failed")

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_BrokenSentenceTransformer))

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=2,
        PGVECTOR_EMBEDDING_MODEL="broken-model",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    store = DocumentStore(tmp_path / "rag_pg_init_fail", cfg=cfg)

    assert store._vector_backend == "pgvector"
    assert store._pgvector_available is False
    assert any("pgvector başlatma hatası" in msg for msg in errors)


def test_rag_module_uses_bleach_when_available(monkeypatch):
    bleach_stub = types.SimpleNamespace(
        clean=lambda html, **_kwargs: "  kept <b>text</b>  &amp; more  "
    )
    monkeypatch.setitem(sys.modules, "bleach", bleach_stub)

    rag_mod = _load_rag_module("rag_edge_bleach_present")

    assert rag_mod._BLEACH_AVAILABLE is True
    assert rag_mod.DocumentStore._clean_html("<p>ignored</p>") == "kept <b>text</b> &amp; more"


def test_add_document_from_file_rejects_paths_outside_allowed_roots(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_file_outside_roots")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    project_root = tmp_path / "project"
    temp_root = tmp_path / "sandbox-temp"
    project_root.mkdir()
    temp_root.mkdir()

    monkeypatch.setattr(rag_mod.Config, "BASE_DIR", project_root, raising=False)
    monkeypatch.setattr(rag_mod.tempfile, "gettempdir", lambda: str(temp_root))

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("external content", encoding="utf-8")

    store = DocumentStore(project_root / "rag_store", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))
    ok, message = store.add_document_from_file(str(outside_file))

    assert ok is False
    assert "proje dizini dışında" in message


def test_add_document_from_file_rejects_blocked_sensitive_paths(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_file_blocked_parts")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    project_root = tmp_path / "project"
    project_root.mkdir()

    monkeypatch.setattr(rag_mod.Config, "BASE_DIR", project_root, raising=False)
    monkeypatch.setattr(rag_mod.tempfile, "gettempdir", lambda: str(tmp_path / "sandbox-temp"))

    blocked_file = project_root / "sessions" / "notes.txt"
    blocked_file.parent.mkdir()
    blocked_file.write_text("sensitive", encoding="utf-8")

    store = DocumentStore(project_root / "rag_store", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))
    ok, message = store.add_document_from_file(str(blocked_file))

    assert ok is False
    assert "güvenlik politikası" in message