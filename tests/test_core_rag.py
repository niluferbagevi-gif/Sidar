"""
core/rag.py için birim testleri.
GraphIndex (add_node, add_edge, clear, neighbors, _endpoint_node_id,
_normalize_endpoint_path, resolve_node_id, explain_dependency_path) ve
saf yardımcı fonksiyonları kapsar.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

import pytest


def _get_rag():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        CHROMA_PERSIST_DIRECTORY = "data/chroma"
        USE_GPU = False
        GPU_MIXED_PRECISION = False
        CHUNK_SIZE = 512
        CHUNK_OVERLAP = 50
        RETRIEVAL_TOP_K = 5
        EMBEDDING_MODEL = ""

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "core.rag" in sys.modules:
        del sys.modules["core.rag"]
    import core.rag as rag
    return rag


# ══════════════════════════════════════════════════════════════
# GraphIndex — init
# ══════════════════════════════════════════════════════════════

class TestGraphIndexInit:
    def test_nodes_empty_initially(self):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"))
        assert gi.nodes == {}

    def test_edges_empty_initially(self):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"))
        assert gi.edges == {}

    def test_root_dir_resolved(self):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"))
        assert gi.root_dir == Path("/tmp").resolve()

    def test_max_files_default(self):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"))
        assert gi.max_files == 5000

    def test_max_files_custom(self):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"), max_files=100)
        assert gi.max_files == 100


# ══════════════════════════════════════════════════════════════
# GraphIndex — add_node / add_edge / clear
# ══════════════════════════════════════════════════════════════

class TestGraphIndexMutation:
    def _make(self):
        rag = _get_rag()
        return rag.GraphIndex(Path("/tmp"))

    def test_add_node_appears_in_nodes(self):
        gi = self._make()
        gi.add_node("a")
        assert "a" in gi.nodes

    def test_add_node_with_attributes(self):
        gi = self._make()
        gi.add_node("a", file_type=".py", node_type="file")
        assert gi.nodes["a"]["file_type"] == ".py"

    def test_add_node_ignores_none_attributes(self):
        gi = self._make()
        gi.add_node("a", file_type=None)
        assert "file_type" not in gi.nodes.get("a", {})

    def test_add_node_idempotent(self):
        gi = self._make()
        gi.add_node("a", foo="bar")
        gi.add_node("a", baz="qux")
        assert gi.nodes["a"]["foo"] == "bar"
        assert gi.nodes["a"]["baz"] == "qux"

    def test_add_edge_both_nodes_exist(self):
        gi = self._make()
        gi.add_node("a")
        gi.add_node("b")
        gi.add_edge("a", "b")
        assert "b" in gi.edges["a"]

    def test_add_edge_creates_reverse(self):
        gi = self._make()
        gi.add_edge("a", "b")
        assert "a" in gi.reverse_edges["b"]

    def test_add_edge_kind_recorded(self):
        gi = self._make()
        gi.add_edge("a", "b", kind="imports")
        assert "imports" in gi.edge_kinds[("a", "b")]

    def test_clear_empties_all(self):
        gi = self._make()
        gi.add_node("a")
        gi.add_edge("a", "b")
        gi.clear()
        assert gi.nodes == {}
        assert gi.edges == {}
        assert gi.reverse_edges == {}
        assert gi.edge_kinds == {}


# ══════════════════════════════════════════════════════════════
# GraphIndex — neighbors / reverse_neighbors
# ══════════════════════════════════════════════════════════════

class TestGraphIndexNeighbors:
    def _make(self):
        rag = _get_rag()
        return rag.GraphIndex(Path("/tmp"))

    def test_neighbors_returns_sorted_list(self):
        gi = self._make()
        gi.add_edge("a", "c")
        gi.add_edge("a", "b")
        neighbors = gi.neighbors("a")
        assert neighbors == ["b", "c"]

    def test_reverse_neighbors(self):
        gi = self._make()
        gi.add_edge("a", "b")
        gi.add_edge("c", "b")
        rev = gi.reverse_neighbors("b")
        assert "a" in rev
        assert "c" in rev

    def test_neighbors_empty_for_unknown_node(self):
        gi = self._make()
        assert gi.neighbors("nonexistent") == []

    def test_reverse_neighbors_empty_for_unknown_node(self):
        gi = self._make()
        assert gi.reverse_neighbors("nonexistent") == []


# ══════════════════════════════════════════════════════════════
# GraphIndex._endpoint_node_id
# ══════════════════════════════════════════════════════════════

class TestEndpointNodeId:
    def _make(self):
        rag = _get_rag()
        return rag.GraphIndex(Path("/tmp"))

    def test_get_endpoint(self):
        gi = self._make()
        result = gi._endpoint_node_id("GET", "/api/users")
        assert result == "endpoint:GET /api/users"

    def test_post_endpoint(self):
        gi = self._make()
        assert gi._endpoint_node_id("POST", "/login") == "endpoint:POST /login"

    def test_method_uppercased(self):
        gi = self._make()
        result = gi._endpoint_node_id("get", "/path")
        assert "GET" in result

    def test_path_without_slash_gets_slash_prefix(self):
        gi = self._make()
        result = gi._endpoint_node_id("GET", "api/users")
        assert result.startswith("endpoint:GET /")


# ══════════════════════════════════════════════════════════════
# GraphIndex._normalize_endpoint_path
# ══════════════════════════════════════════════════════════════

class TestNormalizeEndpointPath:
    def _norm(self, url):
        rag = _get_rag()
        gi = rag.GraphIndex(Path("/tmp"))
        return gi._normalize_endpoint_path(url)

    def test_simple_path_returned(self):
        assert self._norm("/api/users") == "/api/users"

    def test_empty_returns_none(self):
        assert self._norm("") is None

    def test_template_literal_returns_none(self):
        assert self._norm("/api/${id}") is None

    def test_localhost_url_extracts_path(self):
        result = self._norm("http://localhost:3000/api/users")
        assert result == "/api/users"

    def test_external_url_returns_none(self):
        assert self._norm("https://api.example.com/users") is None

    def test_path_without_slash_returns_none(self):
        assert self._norm("api/users") is None

    def test_slash_only_returns_slash(self):
        assert self._norm("/") == "/"


# ══════════════════════════════════════════════════════════════
# GraphIndex.resolve_node_id
# ══════════════════════════════════════════════════════════════

class TestResolveNodeId:
    def _make(self):
        rag = _get_rag()
        return rag.GraphIndex(Path("/tmp"))

    def test_exact_match_returned(self):
        gi = self._make()
        gi.add_node("core/foo.py")
        assert gi.resolve_node_id("core/foo.py") == "core/foo.py"

    def test_case_insensitive_match(self):
        gi = self._make()
        gi.add_node("core/Foo.py")
        assert gi.resolve_node_id("core/foo.py") == "core/Foo.py"

    def test_empty_returns_none(self):
        gi = self._make()
        assert gi.resolve_node_id("") is None

    def test_ambiguous_returns_none(self):
        gi = self._make()
        gi.add_node("core/foo.py")
        gi.add_node("other/foo.py")
        result = gi.resolve_node_id("foo.py")
        # Two matches → ambiguous → None
        assert result is None

    def test_suffix_match(self):
        gi = self._make()
        gi.add_node("core/utils/foo.py")
        result = gi.resolve_node_id("foo.py")
        assert result == "core/utils/foo.py"


# ══════════════════════════════════════════════════════════════
# GraphIndex.rebuild
# ══════════════════════════════════════════════════════════════

class TestGraphIndexRebuild:
    def test_rebuild_on_empty_dir(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            gi = rag.GraphIndex(Path(tmpdir))
            result = gi.rebuild()
            assert result["nodes"] == 0
            assert result["edges"] == 0

    def test_rebuild_finds_python_files(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "foo.py").write_text("x = 1")
            (Path(tmpdir) / "bar.py").write_text("y = 2")
            gi = rag.GraphIndex(Path(tmpdir))
            result = gi.rebuild()
            assert result["nodes"] >= 2

    def test_rebuild_skips_pycache(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "__pycache__"
            cache_dir.mkdir()
            (cache_dir / "foo.cpython-311.pyc").write_bytes(b"")
            gi = rag.GraphIndex(Path(tmpdir))
            result = gi.rebuild()
            assert result["nodes"] == 0  # .pyc not in SUPPORTED_EXTENSIONS


def _make_store_stub(rag_module, tmpdir: Path):
    store = rag_module.DocumentStore.__new__(rag_module.DocumentStore)
    store.store_dir = tmpdir
    store.cfg = types.SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=1)
    store._is_local_llm_provider = False
    store._bm25_available = False
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = None
    store._index = {}
    return store


class TestDocumentStoreVectorFetch:
    def test_fetch_chroma_returns_empty_when_ids_missing(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _Collection:
                def count(self):
                    return 7

                def query(self, **_kwargs):
                    return {"ids": [[]], "documents": [[]], "metadatas": [[]]}

            store.collection = _Collection()
            result = rag.DocumentStore._fetch_chroma(store, "sidar", 3, "global")
            assert result == []

    def test_fetch_chroma_falls_back_to_chunk_id_when_parent_id_missing(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _Collection:
                def count(self):
                    return 10

                def query(self, **_kwargs):
                    return {
                        "ids": [["chunk_1", "chunk_2"]],
                        "documents": [["parca-1", "parca-2"]],
                        "metadatas": [[{}, {"parent_id": "doc-2", "title": "Belge", "source": "file://x"}]],
                    }

            store.collection = _Collection()
            result = rag.DocumentStore._fetch_chroma(store, "sidar", 5, "global")
            assert len(result) == 2
            assert result[0]["id"] == "chunk_1"
            assert result[1]["id"] == "doc-2"
            assert result[1]["snippet"] == "parca-2"

    def test_fetch_pgvector_returns_empty_when_embedding_fails(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._pgvector_available = True
            store.pg_engine = object()
            store._pg_table = "rag_embeddings"
            monkeypatch.setattr(store, "_pgvector_embed_texts", lambda _texts: [])
            result = rag.DocumentStore._fetch_pgvector(store, "query", 3, "global")
            assert result == []

    def test_fetch_pgvector_returns_empty_when_db_query_raises(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._pgvector_available = True
            store._pg_table = "rag_embeddings"
            monkeypatch.setattr(store, "_pgvector_embed_texts", lambda _texts: [[0.1, 0.2]])

            class _BrokenConn:
                def execute(self, *_a, **_k):
                    raise RuntimeError("db connection lost")

            class _BrokenEngine:
                def connect(self):
                    class _CM:
                        def __enter__(self_inner):
                            return _BrokenConn()

                        def __exit__(self_inner, exc_type, exc, tb):
                            return False

                    return _CM()

            store.pg_engine = _BrokenEngine()
            result = rag.DocumentStore._fetch_pgvector(store, "query", 3, "global")
            assert result == []


class TestDocumentStoreFileInputValidation:
    def test_add_document_from_file_rejects_empty_content(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            empty_file = base_dir / "bos.md"
            empty_file.write_text("   \n\t", encoding="utf-8")

            store = _make_store_stub(rag, base_dir)
            ok, message = rag.DocumentStore.add_document_from_file(store, str(empty_file))
            assert ok is False
            assert "Dosya boş" in message

    def test_add_document_from_file_handles_read_error(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            valid_file = base_dir / "dokuman.md"
            valid_file.write_text("icerik", encoding="utf-8")

            store = _make_store_stub(rag, base_dir)
            monkeypatch.setattr(
                rag.Path,
                "read_text",
                lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read failed")),
            )
            ok, message = rag.DocumentStore.add_document_from_file(store, str(valid_file))
            assert ok is False
            assert "Dosya eklenemedi" in message


class TestDocumentStoreChunkingAndFallback:
    def _build_store(self, monkeypatch, tmp_path):
        rag = _get_rag()
        monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _name: False)
        monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: None)
        return rag, rag.DocumentStore(store_dir=tmp_path)

    def test_recursive_chunk_text_handles_empty_and_boundaries(self, monkeypatch, tmp_path):
        _, store = self._build_store(monkeypatch, tmp_path)
        assert store._recursive_chunk_text("", size=10, overlap=2) == []
        chunks = store._recursive_chunk_text("abcdefghi", size=4, overlap=1)
        assert len(chunks) >= 3
        assert all(len(chunk) <= 4 for chunk in chunks)

    def test_chunk_text_uses_explicit_chunk_settings(self, monkeypatch, tmp_path):
        _, store = self._build_store(monkeypatch, tmp_path)
        chunks = store._chunk_text("x" * 15, chunk_size=5, chunk_overlap=2)
        assert chunks
        assert max(len(c) for c in chunks) <= 5

    def test_init_chroma_marks_backend_unavailable_on_exception(self, monkeypatch, tmp_path):
        rag, store = self._build_store(monkeypatch, tmp_path)
        store._chroma_available = True
        fake_chromadb = types.SimpleNamespace(
            PersistentClient=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db down"))
        )
        monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
        monkeypatch.setattr(rag, "_build_embedding_function", lambda **_kwargs: None)
        store._init_chroma()
        assert store._chroma_available is False

    def test_search_sync_returns_empty_context_message_when_session_has_no_docs(self, monkeypatch, tmp_path):
        _, store = self._build_store(monkeypatch, tmp_path)
        ok, message = store._search_sync("test query", session_id="session-a")
        assert ok is False
        assert "belge deposu boş" in message

    def test_vector_mode_returns_unavailable_when_no_vector_backend(self, monkeypatch, tmp_path):
        _, store = self._build_store(monkeypatch, tmp_path)
        store._index["doc1"] = {"session_id": "global"}
        ok, message = store._search_sync("query", mode="vector", session_id="global")
        assert ok is False
        assert "Vektör arama kullanılamıyor" in message


class TestDocumentStoreSearchEdgeCases:
    def test_fetch_chroma_count_error_still_returns_results(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _Collection:
                def count(self):
                    raise RuntimeError("count unavailable")

                def query(self, **_kwargs):
                    return {
                        "ids": [["chunk-1"]],
                        "documents": [["parca-1"]],
                        "metadatas": [[{"parent_id": "doc-1", "title": "Belge 1"}]],
                    }

            store.collection = _Collection()
            results = rag.DocumentStore._fetch_chroma(store, "sorgu", 2, "global")
            assert len(results) == 1
            assert results[0]["id"] == "doc-1"

    def test_search_sync_rrf_error_falls_back_to_pgvector(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._index["doc1"] = {"session_id": "global"}
            store._bm25_available = True
            store._pgvector_available = True
            store._chroma_available = False
            store._rrf_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rrf down"))
            store._pgvector_search = lambda _q, _k, _s: (True, "pgvector-result")

            ok, output = rag.DocumentStore._search_sync(store, "query", top_k=3, mode="auto", session_id="global")
            assert ok is True
            assert output == "pgvector-result"

    def test_search_sync_no_vector_and_no_bm25_exits_keyword(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._index["doc1"] = {"session_id": "global"}
            store._bm25_available = False
            store._pgvector_available = False
            store._chroma_available = False
            store.collection = None
            store._keyword_search = lambda _q, _k, _s: (True, "keyword-exit")

            ok, output = rag.DocumentStore._search_sync(store, "query", top_k=3, mode="auto", session_id="global")
            assert ok is True
            assert output == "keyword-exit"


class TestDocumentStoreUrlErrorHandling:
    def test_add_document_from_url_handles_timeout(self, monkeypatch, tmp_path):
        rag = _get_rag()
        store = _make_store_stub(rag, tmp_path)
        monkeypatch.setattr(store, "_validate_url_safe", lambda _url: None)

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                raise TimeoutError("request timed out")

        fake_httpx = types.SimpleNamespace(AsyncClient=_FakeAsyncClient)
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

        import asyncio
        ok, message = asyncio.run(store.add_document_from_url("https://example.com/doc"))
        assert ok is False
        assert "URL belge eklenemedi" in message

    def test_add_document_from_url_http_error_is_reported(self, monkeypatch, tmp_path):
        rag = _get_rag()
        store = _make_store_stub(rag, tmp_path)
        monkeypatch.setattr(store, "_validate_url_safe", lambda _url: None)

        class _Resp:
            text = "<html><title>Fail</title></html>"

            def raise_for_status(self):
                raise RuntimeError("413 payload too large")

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                return _Resp()

        fake_httpx = types.SimpleNamespace(AsyncClient=_FakeAsyncClient)
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

        import asyncio
        ok, message = asyncio.run(store.add_document_from_url("https://example.com/too-large"))
        assert ok is False
        assert "413 payload too large" in message


class TestSemanticCacheEmbeddings:
    def test_embed_texts_for_semantic_cache_returns_empty_on_model_error(self, monkeypatch):
        rag = _get_rag()

        class _BrokenModel:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("model load failed")

        fake_st_module = types.SimpleNamespace(SentenceTransformer=_BrokenModel)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)
        vectors = rag.embed_texts_for_semantic_cache(["merhaba dünya"])
        assert vectors == []

    def test_embed_texts_for_semantic_cache_returns_vectors_from_model(self, monkeypatch):
        rag = _get_rag()

        class _FakeVectors:
            def tolist(self):
                return [[0.1, 0.2, 0.3]]

        class _Model:
            def __init__(self, *_args, **_kwargs):
                pass

            def encode(self, texts, normalize_embeddings=True):
                assert texts == ["sorgu"]
                assert normalize_embeddings is True
                return _FakeVectors()

        fake_st_module = types.SimpleNamespace(SentenceTransformer=_Model)
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)

        vectors = rag.embed_texts_for_semantic_cache(["sorgu"])
        assert vectors == [[0.1, 0.2, 0.3]]


class TestDocumentStoreUrlValidation:
    def test_validate_url_safe_rejects_localhost(self):
        rag = _get_rag()
        with pytest.raises(ValueError, match="localhost"):
            rag.DocumentStore._validate_url_safe("http://localhost:8000/secret")

    def test_validate_url_safe_rejects_disallowed_scheme(self):
        rag = _get_rag()
        with pytest.raises(ValueError, match="http/https"):
            rag.DocumentStore._validate_url_safe("ftp://example.com/file")
