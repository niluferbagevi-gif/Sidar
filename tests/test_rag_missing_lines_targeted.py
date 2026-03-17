import asyncio
import builtins
import importlib.util
import sys
import types
from pathlib import Path

from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def test_module_sets_otel_trace_none_when_import_fails(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry":
            raise ImportError("otel missing")
        return real_import(name, globals, locals, fromlist, level)

    cfg_mod = types.ModuleType("config")
    cfg_mod.Config = type("_Cfg", (), {})

    monkeypatch.setattr(builtins, "__import__", _import)
    prev_cfg = sys.modules.get("config")
    sys.modules["config"] = cfg_mod
    try:
        spec = importlib.util.spec_from_file_location("rag_no_otel", Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
    finally:
        if prev_cfg is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev_cfg

    assert mod._otel_trace is None


def test_embed_texts_for_semantic_cache_branches(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    assert mod.embed_texts_for_semantic_cache([]) == []

    class _Vec:
        def tolist(self):
            return [[0.1, 0.2]]

    class _Model:
        def __init__(self, _name):
            pass

        def encode(self, _texts, normalize_embeddings=True):
            return _Vec()

    sent_mod = types.ModuleType("sentence_transformers")
    sent_mod.SentenceTransformer = _Model
    monkeypatch.setitem(sys.modules, "sentence_transformers", sent_mod)
    assert mod.embed_texts_for_semantic_cache(["abc"]) == [[0.1, 0.2]]

    class _ModelList(_Model):
        def encode(self, _texts, normalize_embeddings=True):
            return ((1, 2),)

    sent_mod.SentenceTransformer = _ModelList
    assert mod.embed_texts_for_semantic_cache(["abc"]) == [[1, 2]]

    class _BrokenModel(_Model):
        def __init__(self, _name):
            raise RuntimeError("broken")

    sent_mod.SentenceTransformer = _BrokenModel
    assert mod.embed_texts_for_semantic_cache(["abc"]) == []


def test_pgvector_helpers_init_and_upsert_delete_paths(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    assert st._normalize_pg_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert st._format_vector_for_sql([1, 2.5]) == "[1.00000000,2.50000000]"

    st.cfg.DATABASE_URL = "postgresql://user:pass@host/db"
    st._check_import = lambda name: False
    st._init_pgvector()

    st._check_import = lambda name: True
    sent_mod = types.ModuleType("sentence_transformers")
    sent_mod.SentenceTransformer = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no model"))
    monkeypatch.setitem(sys.modules, "sentence_transformers", sent_mod)
    sql_mod = types.ModuleType("sqlalchemy")
    sql_mod.create_engine = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no engine"))
    sql_mod.text = lambda q: q
    monkeypatch.setitem(sys.modules, "sqlalchemy", sql_mod)
    st._init_pgvector()

    # _pgvector_embed_texts empty-model branch
    st._pg_embedding_model = None
    assert st._pgvector_embed_texts(["x"]) == []

    class _Rows(list):
        pass

    class _Conn:
        def __init__(self):
            self.calls = []

        def execute(self, query, params=None):
            self.calls.append((query, params))
            return _Rows()

    class _Ctx:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self.conn

        def __exit__(self, *args):
            return False

    conn = _Conn()

    class _Engine:
        def begin(self):
            return _Ctx(conn)

    st.pg_engine = _Engine()
    st._pg_table = "rag_chunks"
    st._pgvector_available = True
    st._pgvector_embed_texts = lambda chunks: [[0.1, 0.2] for _ in chunks]
    st._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c1", "c2"])
    assert len(conn.calls) == 2

    # vectors empty -> early return
    st._pgvector_embed_texts = lambda chunks: []
    st._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c1"])

    # exception branch in upsert
    class _BadEngine:
        def begin(self):
            raise RuntimeError("db down")

    st.pg_engine = _BadEngine()
    st._pgvector_embed_texts = lambda chunks: [[0.1, 0.2]]
    st._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c1"])

    # delete early return + exception
    st._pgvector_available = False
    st._delete_pgvector_parent("p", "s")
    st._pgvector_available = True
    st._delete_pgvector_parent("p", "s")


def test_validate_url_and_status_pgvector_branches(tmp_path):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    try:
        st._validate_url_safe("ftp://example.com")
        assert False
    except ValueError as exc:
        assert "http/https" in str(exc)

    try:
        st._validate_url_safe("https:///abc")
        assert False
    except ValueError as exc:
        assert "hostname" in str(exc)

    try:
        st._validate_url_safe("https://127.0.0.1")
        assert False
    except ValueError as exc:
        assert "İç ağ" in str(exc)

    try:
        st._validate_url_safe("https://localhost")
        assert False
    except ValueError as exc:
        assert "Engellenen" in str(exc)

    st._validate_url_safe("https://example.com")

    st._index = {}
    st._pgvector_available = True
    st._vector_backend = "pgvector"
    st._chroma_available = False
    st._bm25_available = False
    assert "pgvector" in st.status()


def test_add_delete_search_and_pgvector_fetch_paths(tmp_path):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    called = {"upsert": 0, "delete": 0}
    st._pgvector_available = True
    st._upsert_pgvector_chunks = lambda *args, **kwargs: called.__setitem__("upsert", called["upsert"] + 1)
    doc_id = asyncio.run(st.add_document("T", "icerik", session_id="s1"))
    assert called["upsert"] == 1

    st._delete_pgvector_parent = lambda *args, **kwargs: called.__setitem__("delete", called["delete"] + 1)
    msg = st.delete_document(doc_id, session_id="s1")
    assert "silindi" in msg and called["delete"] == 1

    st._index = {"d1": {"session_id": "s1", "title": "A", "source": "", "tags": []}}
    st._is_local_llm_provider = True
    st._local_hybrid_enabled = False

    st._pgvector_available = True
    st._pgvector_search = lambda *a: (True, "pg")
    assert st._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "pg")

    st._pgvector_available = False
    st._chroma_available = True
    st.collection = object()
    st._chroma_search = lambda *a: (True, "ch")
    assert st._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "ch")

    st._chroma_available = False
    st._bm25_available = False
    st._keyword_search = lambda *a: (True, "kw")
    assert st._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "kw")

    # pgvector try/except fallback to bm25
    st._is_local_llm_provider = False
    st._pgvector_available = True
    st._chroma_available = False
    st._bm25_available = True
    st._rrf_search = lambda *a: (_ for _ in ()).throw(RuntimeError("rrf fail"))
    st._pgvector_search = lambda *a: (_ for _ in ()).throw(RuntimeError("pg fail"))
    st._bm25_search = lambda *a: (True, "bm")
    assert st._search_sync("q", top_k=1, mode="auto", session_id="s1") == (True, "bm")

    # _fetch_pgvector success + exception + _pgvector_search
    class _Row:
        def __init__(self, parent_id, title, source, chunk_content, distance):
            self.parent_id = parent_id
            self.title = title
            self.source = source
            self.chunk_content = chunk_content
            self.distance = distance

    class _ExecRes:
        def fetchall(self):
            return [_Row("p1", "T", "S", "snip", 0.2)]

    class _Conn:
        def execute(self, *_a, **_k):
            return _ExecRes()

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *args):
            return False

    class _Engine:
        def begin(self):
            return _Ctx()

    sql_mod = types.ModuleType("sqlalchemy")
    sql_mod.text = lambda q: q
    sys.modules["sqlalchemy"] = sql_mod

    st.pg_engine = _Engine()
    st._pg_table = "rag_chunks"
    st._pgvector_embed_texts = lambda _t: [[0.1, 0.2]]
    found = st._fetch_pgvector("q", 1, "s1")
    assert found and found[0]["id"] == "p1"

    st._pgvector_embed_texts = lambda _t: []
    assert st._fetch_pgvector("q", 1, "s1") == []

    ok, text = mod.DocumentStore._pgvector_search(st, "q", 1, "s1")
    assert ok is False or "RAG Arama" in text
