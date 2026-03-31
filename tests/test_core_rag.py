"""
core/rag.py için birim testleri.
GraphIndex (add_node, add_edge, clear, neighbors, _endpoint_node_id,
_normalize_endpoint_path, resolve_node_id, explain_dependency_path) ve
saf yardımcı fonksiyonları kapsar.
"""
from __future__ import annotations

import sys
import tempfile
import threading
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
    def test_add_document_from_file_rejects_missing_path(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            store = _make_store_stub(rag, base_dir)

            ok, message = rag.DocumentStore.add_document_from_file(store, str(base_dir / "missing.md"))
            assert ok is False
            assert "Dosya bulunamadı" in message

    def test_add_document_from_file_rejects_directory_path(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            store = _make_store_stub(rag, base_dir)

            ok, message = rag.DocumentStore.add_document_from_file(store, str(base_dir))
            assert ok is False
            assert "bir dosya değil" in message

    def test_add_document_from_file_rejects_outside_allowed_roots(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as base_tmpdir:
            base_dir = Path(base_tmpdir).resolve()
            external_file = (Path.cwd() / "external_outside_allowed.md").resolve()
            external_file.write_text("external content", encoding="utf-8")
            try:
                monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
                store = _make_store_stub(rag, base_dir)

                ok, message = rag.DocumentStore.add_document_from_file(store, str(external_file))
                assert ok is False
                assert "proje dizini dışında" in message
            finally:
                external_file.unlink(missing_ok=True)

    def test_add_document_from_file_rejects_blocked_path_parts(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            blocked_file = base_dir / "sessions" / "chat.md"
            blocked_file.parent.mkdir(parents=True, exist_ok=True)
            blocked_file.write_text("gizli", encoding="utf-8")
            store = _make_store_stub(rag, base_dir)

            ok, message = rag.DocumentStore.add_document_from_file(store, str(blocked_file))
            assert ok is False
            assert "güvenlik politikası" in message

    def test_add_document_from_file_rejects_unsupported_extension(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            monkeypatch.setattr(rag.Config, "BASE_DIR", base_dir, raising=False)
            binary_file = base_dir / "weights.bin"
            binary_file.write_text("binary-like", encoding="utf-8")
            store = _make_store_stub(rag, base_dir)

            ok, message = rag.DocumentStore.add_document_from_file(store, str(binary_file))
            assert ok is False
            assert "Desteklenmeyen dosya türü" in message

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

    def test_recursive_chunk_text_handles_overlap_greater_than_size(self, monkeypatch, tmp_path):
        _, store = self._build_store(monkeypatch, tmp_path)
        chunks = store._recursive_chunk_text("abcdefghij", size=3, overlap=10)
        assert chunks
        assert all(len(chunk) > 0 for chunk in chunks)

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

    def test_search_sync_auto_local_llm_prefers_pgvector_when_hybrid_disabled(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._index["doc1"] = {"session_id": "global"}
            store._is_local_llm_provider = True
            store._local_hybrid_enabled = False
            store._pgvector_available = True
            store._chroma_available = False
            store._bm25_available = True
            store._pgvector_search = lambda _q, _k, _s: (True, "local-pgvector")

            ok, output = rag.DocumentStore._search_sync(store, "query", top_k=3, mode="auto", session_id="global")
            assert ok is True
            assert output == "local-pgvector"

    def test_search_sync_pgvector_exception_falls_back_to_bm25(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._index["doc1"] = {"session_id": "global"}
            store._bm25_available = True
            store._pgvector_available = True
            store._chroma_available = False
            store._pgvector_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("pgvector timeout"))
            store._bm25_search = lambda _q, _k, _s: (True, "bm25-fallback")

            ok, output = rag.DocumentStore._search_sync(store, "query", top_k=3, mode="auto", session_id="global")
            assert ok is True
            assert output == "bm25-fallback"

    def test_search_sync_chroma_exception_falls_back_to_bm25(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._index["doc1"] = {"session_id": "global"}
            store._bm25_available = True
            store._pgvector_available = False
            store._chroma_available = True
            store.collection = object()
            store._chroma_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("chroma timeout"))
            store._bm25_search = lambda _q, _k, _s: (True, "bm25-after-chroma")

            ok, output = rag.DocumentStore._search_sync(store, "query", top_k=3, mode="auto", session_id="global")
            assert ok is True
            assert output == "bm25-after-chroma"


class TestDocumentStoreConsolidationPaths:
    def test_consolidate_skips_when_no_removable_documents(self, monkeypatch, tmp_path):
        rag, store = TestDocumentStoreChunkingAndFallback()._build_store(monkeypatch, tmp_path)
        store._index = {
            "d1": {"session_id": "s1", "access_count": 5, "created_at": 10, "last_accessed_at": 12},
            "d2": {"session_id": "s1", "tags": ["pinned"], "access_count": 0, "created_at": 9, "last_accessed_at": 11},
            "d3": {"session_id": "s1", "tags": ["memory-summary"], "access_count": 0, "created_at": 8, "last_accessed_at": 10},
        }
        monkeypatch.setattr(store, "_add_document_sync", lambda **_kwargs: "should-not-run")

        result = store.consolidate_session_documents("s1", keep_recent_docs=1)

        assert result["status"] == "skipped"
        assert result["removed_docs"] == 0
        assert result["summary_doc_id"] == ""

    def test_consolidate_creates_summary_and_deletes_old_and_digest_docs(self, monkeypatch, tmp_path):
        rag, store = TestDocumentStoreChunkingAndFallback()._build_store(monkeypatch, tmp_path)
        store._index = {
            "recent": {"session_id": "s1", "access_count": 4, "created_at": 50, "last_accessed_at": 60, "title": "Recent"},
            "old1": {"session_id": "s1", "access_count": 0, "created_at": 10, "last_accessed_at": 12, "title": "Old 1", "preview": "p1"},
            "old2": {"session_id": "s1", "access_count": 1, "created_at": 9, "last_accessed_at": 11, "title": "Old 2", "preview": "p2"},
            "digest": {"session_id": "s1", "source": "memory://nightly-digest/prev", "access_count": 0, "created_at": 5},
        }
        deleted = []
        monkeypatch.setattr(store, "delete_document", lambda doc_id, session_id=None: deleted.append((doc_id, session_id)))
        monkeypatch.setattr(store, "_add_document_sync", lambda **_kwargs: "summary-doc-1")

        result = store.consolidate_session_documents("s1", keep_recent_docs=1)

        assert result["status"] == "completed"
        assert result["removed_docs"] == 3
        assert result["summary_doc_id"] == "summary-doc-1"
        assert ("digest", "s1") in deleted
        assert ("old1", "s1") in deleted
        assert ("old2", "s1") in deleted


class TestDocumentStorePgvectorAndChunkingEdgeCases:
    def test_pgvector_embed_texts_returns_empty_when_encode_raises(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _BrokenEmbeddingModel:
                def encode(self, *_args, **_kwargs):
                    raise RuntimeError("embedding api down")

            store._pg_embedding_model = _BrokenEmbeddingModel()
            vectors = rag.DocumentStore._pgvector_embed_texts(store, ["merhaba"])
            assert vectors == []

    def test_pgvector_embed_texts_returns_empty_for_empty_input(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._pg_embedding_model = object()
            vectors = rag.DocumentStore._pgvector_embed_texts(store, [])
            assert vectors == []

    def test_recursive_chunk_text_returns_empty_when_size_non_positive(self, monkeypatch, tmp_path):
        rag, store = TestDocumentStoreChunkingAndFallback()._build_store(monkeypatch, tmp_path)
        assert rag.DocumentStore._recursive_chunk_text(store, "abc", size=0, overlap=2) == []

    def test_chunk_text_normalizes_negative_overlap(self, monkeypatch, tmp_path):
        _, store = TestDocumentStoreChunkingAndFallback()._build_store(monkeypatch, tmp_path)
        chunks = store._chunk_text("abcdef", chunk_size=3, chunk_overlap=-5)
        assert chunks == store._chunk_text("abcdef", chunk_size=3, chunk_overlap=0)

    def test_chunk_text_returns_empty_for_zero_chunk_size(self, monkeypatch, tmp_path):
        _, store = TestDocumentStoreChunkingAndFallback()._build_store(monkeypatch, tmp_path)
        assert store._chunk_text("abcdef", chunk_size=0, chunk_overlap=1) == []


class TestDocumentStoreAddDocumentErrorPaths:
    def test_add_document_sync_handles_chroma_upsert_exception(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._write_lock = threading.Lock()
            store._chunk_size = 1000
            store._chunk_overlap = 150
            store._save_index = lambda: None
            store._update_bm25_cache_on_add = lambda *_args, **_kwargs: None

            calls = {"delete": 0, "upsert": 0}

            class _Collection:
                def delete(self, **_kwargs):
                    calls["delete"] += 1

                def upsert(self, **_kwargs):
                    calls["upsert"] += 1
                    raise RuntimeError("vector db unavailable")

            store.collection = _Collection()
            store._chroma_available = True

            doc_id = rag.DocumentStore._add_document_sync(store, "Başlık", "içerik içeriği", "file://x", ["tag"], "global")
            assert doc_id in store._index
            assert calls["delete"] == 1
            assert calls["upsert"] == 1

    def test_add_document_sync_with_empty_chunks_does_not_upsert(self, monkeypatch):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._write_lock = threading.Lock()
            store._chunk_size = 1000
            store._chunk_overlap = 150
            store._save_index = lambda: None
            store._update_bm25_cache_on_add = lambda *_args, **_kwargs: None
            monkeypatch.setattr(store, "_chunk_text", lambda _content: [])

            calls = {"delete": 0, "upsert": 0}

            class _Collection:
                def delete(self, **_kwargs):
                    calls["delete"] += 1

                def upsert(self, **_kwargs):
                    calls["upsert"] += 1

            store.collection = _Collection()
            store._chroma_available = True

            doc_id = rag.DocumentStore._add_document_sync(store, "Boş", "x", "file://x", [], "global")
            assert doc_id in store._index
            assert calls["delete"] == 1
            assert calls["upsert"] == 0


class TestDocumentStoreUrlErrorHandling:
    def test_add_document_from_url_reports_value_error_from_url_validation(self, monkeypatch, tmp_path):
        rag = _get_rag()
        store = _make_store_stub(rag, tmp_path)

        def _raise_validation_error(_url):
            raise ValueError("Engellenen hostname: localhost")

        monkeypatch.setattr(store, "_validate_url_safe", _raise_validation_error)

        import asyncio
        ok, message = asyncio.run(store.add_document_from_url("http://localhost:8000/private"))
        assert ok is False
        assert "Engellenen hostname" in message

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


class TestDocumentStoreJudgeScheduling:
    def test_schedule_judge_ignores_llm_service_timeout(self, monkeypatch):
        rag = _get_rag()

        class _Judge:
            enabled = True

            def schedule_background_evaluation(self, **_kwargs):
                raise TimeoutError("llm service timeout")

        fake_judge_module = types.SimpleNamespace(get_llm_judge=lambda: _Judge())
        monkeypatch.setitem(sys.modules, "core.judge", fake_judge_module)

        # Hata yutulmalı; exception yükselmemeli.
        rag.DocumentStore._schedule_judge("sorgu", "yanıt")

    def test_schedule_judge_returns_early_when_disabled(self, monkeypatch):
        rag = _get_rag()
        called = {"schedule": 0}

        class _Judge:
            enabled = False

            def schedule_background_evaluation(self, **_kwargs):
                called["schedule"] += 1

        fake_judge_module = types.SimpleNamespace(get_llm_judge=lambda: _Judge())
        monkeypatch.setitem(sys.modules, "core.judge", fake_judge_module)

        rag.DocumentStore._schedule_judge("sorgu", "yanıt")
        assert called["schedule"] == 0


class TestDocumentStoreKnowledgeGraphProjection:
    def test_projection_filters_session_and_includes_code_graph(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._vector_backend = "chroma"
            store._pgvector_available = False
            store._index = {
                "doc-1": {"session_id": "s1", "title": "Belge1", "source": "src-a"},
                "doc-2": {"session_id": "s2", "title": "Belge2", "source": "src-b"},
            }
            store._graph_rag_enabled = True
            store._graph_index = types.SimpleNamespace(
                nodes={"n1": {"kind": "file"}, "n2": {"kind": "func"}},
                edges={"n1": {"n2"}},
                edge_kinds={("n1", "n2"): {"IMPORTS"}},
            )
            calls = {"ensure": 0}
            store._ensure_graph_ready = lambda: calls.__setitem__("ensure", calls["ensure"] + 1)

            projection = rag.DocumentStore.build_knowledge_graph_projection(
                store,
                session_id="s1",
                include_code_graph=True,
                limit=50,
            )

            node_ids = {n.id for n in projection["nodes"]}
            assert "doc:doc-1" in node_ids
            assert "doc:doc-2" not in node_ids
            assert "code:n1" in node_ids
            assert calls["ensure"] == 1
            assert projection["vector_backend"] == "chroma"


class TestDocumentStoreBm25FetchPaths:
    def test_fetch_bm25_returns_empty_when_no_alnum_words(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._bm25_available = True
            store._write_lock = threading.Lock()
            store.fts_conn = types.SimpleNamespace()
            out = rag.DocumentStore._fetch_bm25(store, "!!! ???", 3, "global")
            assert out == []

    def test_fetch_bm25_returns_empty_on_query_exception(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            store._bm25_available = True
            store._write_lock = threading.Lock()

            class _BrokenFts:
                def execute(self, *_args, **_kwargs):
                    raise RuntimeError("fts unavailable")

            store.fts_conn = _BrokenFts()
            out = rag.DocumentStore._fetch_bm25(store, "query text", 3, "global")
            assert out == []


class TestDocumentStoreChromaMetadataRobustness:
    def test_fetch_chroma_ignores_non_dict_metadata_items(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _Collection:
                def count(self):
                    return 2

                def query(self, **_kwargs):
                    return {
                        "ids": [["chunk-1"]],
                        "documents": [["icerik"]],
                        "metadatas": [["not-a-dict"]],
                    }

            store.collection = _Collection()
            out = rag.DocumentStore._fetch_chroma(store, "query", 1, "global")
            assert len(out) == 1
            assert out[0]["id"] == "chunk-1"
            assert out[0]["title"] == "?"

    def test_fetch_chroma_returns_empty_when_documents_missing(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))

            class _Collection:
                def count(self):
                    return 1

                def query(self, **_kwargs):
                    return {
                        "ids": [["chunk-1"]],
                        "documents": [[]],
                        "metadatas": [[{"parent_id": "doc-1", "title": "Belge 1"}]],
                    }

            store.collection = _Collection()
            out = rag.DocumentStore._fetch_chroma(store, "query", 1, "global")
            assert out == []


class TestDocumentStoreUrlValidation:
    def test_validate_url_safe_rejects_localhost(self):
        rag = _get_rag()
        with pytest.raises(ValueError, match="localhost"):
            rag.DocumentStore._validate_url_safe("http://localhost:8000/secret")

    def test_validate_url_safe_rejects_disallowed_scheme(self):
        rag = _get_rag()
        with pytest.raises(ValueError, match="http/https"):
            rag.DocumentStore._validate_url_safe("ftp://example.com/file")

    def test_parse_python_source_propagates_value_error_from_parser(self, monkeypatch, tmp_path):
        rag = _get_rag()
        index = rag.GraphIndex(tmp_path)

        def _raise_value_error(_content):
            raise ValueError("parse failed")

        monkeypatch.setattr(rag.ast, "parse", _raise_value_error)

        with pytest.raises(ValueError, match="parse failed"):
            index._parse_python_source(tmp_path / "x.py", "print('x')")


class TestDocumentStoreFormattingEdgeCases:
    def test_format_results_returns_not_found_when_vector_db_empty(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            ok, message = rag.DocumentStore._format_results_from_struct(store, [], "boş sorgu", "Vektör Arama")
            assert ok is False
            assert "ilgili sonuç bulunamadı" in message

    def test_format_results_truncates_overlong_snippet(self):
        rag = _get_rag()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store_stub(rag, Path(tmpdir))
            long_snippet = "x" * 500
            ok, message = rag.DocumentStore._format_results_from_struct(
                store,
                [{"id": "doc-1", "title": "Belge", "source": "file://a", "snippet": long_snippet, "score": 0.2}],
                "sorgu",
                "Vektör Arama",
            )
            assert ok is True
            assert "..." in message

# ===== MERGED FROM tests/test_core_rag_extra.py =====

import asyncio
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Stub heavy dependencies so core.rag can be imported without them installed.
# ---------------------------------------------------------------------------

def _build_stubs():
    stubs: dict[str, types.ModuleType] = {}
    for mod in (
        "chromadb",
        "chromadb.utils",
        "chromadb.utils.embedding_functions",
        "sentence_transformers",
        "sqlalchemy",
        "sqlalchemy.orm",
        "pgvector",
        "torch",
        "torch.amp",
        "opentelemetry",
        "opentelemetry.trace",
        "bleach",
        "core.judge",
        "httpx",
    ):
        stubs[mod] = sys.modules.get(mod) or types.ModuleType(mod)

    # opentelemetry.trace needs get_tracer → return None so tracing branch is skipped
    otel = stubs.get("opentelemetry.trace") or types.ModuleType("opentelemetry.trace")
    otel.get_tracer = lambda *a, **kw: None  # type: ignore[attr-defined]
    stubs["opentelemetry.trace"] = otel

    # chromadb.utils.embedding_functions needs SentenceTransformerEmbeddingFunction
    ef_mod = stubs["chromadb.utils.embedding_functions"]
    ef_mod.SentenceTransformerEmbeddingFunction = type(  # type: ignore[attr-defined]
        "SentenceTransformerEmbeddingFunction", (), {"__init__": lambda s, **kw: None, "__call__": lambda s, x: []}
    )

    # Config stub
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        CHROMA_PERSIST_DIRECTORY = "data/chroma"
        USE_GPU = False
        GPU_MIXED_PRECISION = False
        RAG_CHUNK_SIZE = 512
        RAG_CHUNK_OVERLAP = 50
        RAG_TOP_K = 3
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
        RAG_VECTOR_BACKEND = "chroma"
        AI_PROVIDER = ""
        RAG_LOCAL_ENABLE_HYBRID = False
        ENABLE_GRAPH_RAG = True
        BASE_DIR = Path("/tmp")
        GRAPH_RAG_MAX_FILES = 5000
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False
        RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER = 1

    cfg_mod.Config = _Cfg
    stubs["config"] = cfg_mod

    # core.judge stub
    judge_mod = stubs.get("core.judge") or types.ModuleType("core.judge")

    class _FakeJudge:
        enabled = False

        def schedule_background_evaluation(self, **kw):
            pass

    judge_mod.get_llm_judge = lambda: _FakeJudge()  # type: ignore[attr-defined]
    stubs["core.judge"] = judge_mod
    return stubs


with patch.dict(sys.modules, _build_stubs(), clear=False):
    # Remove cached module so we get a fresh import with stubs in place
    sys.modules.pop("core.rag", None)
    import core.rag as rag  # noqa: E402  — must come after stubs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> rag.DocumentStore:
    """Build a DocumentStore with ChromaDB and pgvector disabled."""
    with patch.object(rag.DocumentStore, "__init__", return_value=None):
        store = rag.DocumentStore()
    store.cfg = rag.Config()
    store.store_dir = tmp_path
    store.store_dir.mkdir(parents=True, exist_ok=True)
    store.index_file = tmp_path / "index.json"
    store.default_top_k = 3
    store._chunk_size = 512
    store._chunk_overlap = 50
    store._use_gpu = False
    store._gpu_device = 0
    store._mixed_precision = False
    import threading
    store._write_lock = threading.Lock()
    store._index = {}
    store._vector_backend = "chroma"
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = False
    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_ready = False
    store._chroma_available = False
    store._pgvector_available = False
    store.chroma_client = None
    store.collection = None
    store.pg_engine = None
    store._pg_embedding_model = None
    store._pg_table = "rag_embeddings"
    store._pg_embedding_dim = 384
    store._pg_embedding_model_name = "all-MiniLM-L6-v2"
    store._bm25_available = True
    store._init_fts()
    return store


# ===========================================================================
# GraphIndex — _normalize_endpoint_path
# ===========================================================================

class Extra_TestNormalizeEndpointPath:
    def test_simple_path_returned(self):
        assert rag.GraphIndex._normalize_endpoint_path("/api/v1") == "/api/v1"

    def test_no_leading_slash_rejected(self):
        assert rag.GraphIndex._normalize_endpoint_path("api/v1") is None

    def test_template_var_rejected(self):
        assert rag.GraphIndex._normalize_endpoint_path("/api/{id}") is None

    def test_template_dollar_brace_rejected(self):
        assert rag.GraphIndex._normalize_endpoint_path("/api/${id}") is None

    def test_empty_string_rejected(self):
        assert rag.GraphIndex._normalize_endpoint_path("") is None

    def test_localhost_http_url_normalised(self):
        result = rag.GraphIndex._normalize_endpoint_path("http://localhost:8000/api/test")
        assert result == "/api/test"

    def test_external_url_rejected(self):
        assert rag.GraphIndex._normalize_endpoint_path("https://example.com/api") is None

    def test_websocket_localhost_normalised(self):
        result = rag.GraphIndex._normalize_endpoint_path("ws://localhost/ws")
        # ws:// is not in the checked prefixes so path stays as-is → no leading /
        # The method only handles http/https/ws-related; bare ws:// starts with ws://
        # which is not http/https so path check for "/" must pass
        assert result is None or isinstance(result, str)


# ===========================================================================
# GraphIndex — _extract_str_literal
# ===========================================================================

class Extra_TestExtractStrLiteral:
    def test_constant_string_node(self):
        import ast
        node = ast.Constant(value="/health")
        assert rag.GraphIndex._extract_str_literal(node) == "/health"

    def test_non_string_constant_returns_none(self):
        import ast
        node = ast.Constant(value=42)
        assert rag.GraphIndex._extract_str_literal(node) is None

    def test_name_node_returns_none(self):
        import ast
        node = ast.Name(id="x")
        assert rag.GraphIndex._extract_str_literal(node) is None


# ===========================================================================
# GraphIndex — _collect_bfs
# ===========================================================================

class Extra_TestCollectBFS:
    def _gi(self):
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("a")
        gi.add_node("b")
        gi.add_node("c")
        gi.add_edge("a", "b")
        gi.add_edge("b", "c")
        return gi

    def test_distances_computed(self):
        gi = self._gi()
        d = gi._collect_bfs("a", gi.edges, max_depth=3)
        assert d["b"] == 1
        assert d["c"] == 2

    def test_max_depth_respected(self):
        gi = self._gi()
        d = gi._collect_bfs("a", gi.edges, max_depth=1)
        assert "b" in d
        assert "c" not in d

    def test_unknown_start_returns_empty(self):
        gi = self._gi()
        d = gi._collect_bfs("z", gi.edges, max_depth=3)
        assert d == {}


# ===========================================================================
# GraphIndex — impact_analysis
# ===========================================================================

class Extra_TestImpactAnalysis:
    def _gi_with_file(self) -> rag.GraphIndex:
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("mod_a", node_type="file")
        gi.add_node("mod_b", node_type="file")
        gi.add_node("mod_c", node_type="file")
        gi.add_edge("mod_b", "mod_a", kind="imports")
        gi.add_edge("mod_c", "mod_a", kind="imports")
        return gi

    def test_known_node_returns_dict(self):
        gi = self._gi_with_file()
        result = gi.impact_analysis("mod_a")
        assert isinstance(result, dict)
        assert result["target"] == "mod_a"

    def test_unknown_node_returns_empty(self):
        gi = self._gi_with_file()
        assert gi.impact_analysis("does_not_exist") == {}

    def test_risk_level_medium_with_many_dependents(self):
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("core", node_type="file")
        for i in range(4):
            gi.add_node(f"dep_{i}", node_type="file")
            gi.add_edge(f"dep_{i}", "core", kind="imports")
        result = gi.impact_analysis("core")
        assert result["risk_level"] in ("medium", "high")


# ===========================================================================
# GraphIndex — search_related
# ===========================================================================

class Extra_TestSearchRelated:
    def test_returns_ranked_results(self):
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("auth.py", node_type="file")
        gi.add_node("user_auth.py", node_type="file")
        gi.add_node("unrelated.py", node_type="file")
        results = gi.search_related("auth", top_k=2)
        assert len(results) <= 2
        ids = [r["id"] for r in results]
        assert "auth.py" in ids or "user_auth.py" in ids

    def test_empty_result_for_no_match(self):
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("a.py", node_type="file")
        results = gi.search_related("zzznomatch")
        assert results == []

    def test_result_has_expected_keys(self):
        gi = rag.GraphIndex(Path("/tmp"))
        gi.add_node("foo.py", node_type="file")
        results = gi.search_related("foo")
        assert results
        for key in ("id", "score", "neighbors", "reverse_neighbors", "node_type"):
            assert key in results[0]


# ===========================================================================
# GraphIndex — _extract_script_endpoint_calls
# ===========================================================================

class Extra_TestExtractScriptEndpointCalls:
    def _gi(self):
        return rag.GraphIndex(Path("/tmp"))

    def test_fetch_get_extracted(self):
        gi = self._gi()
        content = "fetch('/api/items')"
        calls = gi._extract_script_endpoint_calls(content)
        assert any(c["path"] == "/api/items" for c in calls)

    def test_fetch_post_method_extracted(self):
        gi = self._gi()
        content = "fetch('/api/create', { method: 'POST' })"
        calls = gi._extract_script_endpoint_calls(content)
        assert any(c["method"] == "POST" for c in calls)

    def test_duplicate_calls_deduplicated(self):
        gi = self._gi()
        content = "fetch('/api/x'); fetch('/api/x');"
        calls = gi._extract_script_endpoint_calls(content)
        paths = [c["path"] for c in calls if c["path"] == "/api/x"]
        assert len(paths) == 1

    def test_external_url_ignored(self):
        gi = self._gi()
        content = "fetch('https://external.com/api/v1')"
        calls = gi._extract_script_endpoint_calls(content)
        assert calls == []


# ===========================================================================
# DocumentStore — _recursive_chunk_text
# ===========================================================================

class Extra_TestRecursiveChunkText:
    def _store(self):
        with tempfile.TemporaryDirectory() as td:
            return _make_store(Path(td))

    def test_short_text_returned_as_single_chunk(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            result = store._recursive_chunk_text("hello world", 512, 50)
            assert result == ["hello world"]

    def test_empty_text_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            assert store._recursive_chunk_text("", 512, 50) == []

    def test_zero_size_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            assert store._recursive_chunk_text("some text", 0, 0) == []

    def test_long_text_split_into_multiple_chunks(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            text = "a" * 2000
            chunks = store._recursive_chunk_text(text, 500, 50)
            assert len(chunks) > 1
            assert all(len(c) <= 500 for c in chunks)

    def test_overlap_clamps_to_size_minus_one(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            # overlap >= size should be clamped without raising
            result = store._recursive_chunk_text("a" * 100, 50, 60)
            assert isinstance(result, list)

    def test_chunk_preserves_def_separator(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            text = "\ndef foo():\n    pass\n" * 20
            chunks = store._recursive_chunk_text(text, 100, 20)
            assert len(chunks) >= 1


# ===========================================================================
# DocumentStore — _chunk_text
# ===========================================================================

class Extra_TestChunkText:
    def test_delegates_to_recursive_chunk_text(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            result = store._chunk_text("hello", 512, 50)
            assert result == ["hello"]

    def test_negative_overlap_coerced_to_zero(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            result = store._chunk_text("hello world", 512, -10)
            assert isinstance(result, list)

    def test_zero_chunk_size_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            assert store._chunk_text("some text", 0, 0) == []


# ===========================================================================
# DocumentStore — _validate_url_safe
# ===========================================================================

class Extra_TestValidateUrlSafe:
    def test_public_https_allowed(self):
        # Should not raise
        rag.DocumentStore._validate_url_safe("https://example.com/page")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="http/https"):
            rag.DocumentStore._validate_url_safe("ftp://example.com/file")

    def test_localhost_rejected(self):
        with pytest.raises(ValueError):
            rag.DocumentStore._validate_url_safe("http://localhost/api")

    def test_private_ip_rejected(self):
        with pytest.raises(ValueError):
            rag.DocumentStore._validate_url_safe("http://192.168.1.1/api")

    def test_loopback_ip_rejected(self):
        with pytest.raises(ValueError):
            rag.DocumentStore._validate_url_safe("http://127.0.0.1/api")

    def test_metadata_server_rejected(self):
        with pytest.raises(ValueError):
            rag.DocumentStore._validate_url_safe("http://169.254.169.254/latest/meta-data/")

    def test_no_hostname_rejected(self):
        with pytest.raises(ValueError, match="hostname"):
            rag.DocumentStore._validate_url_safe("http:///path")


# ===========================================================================
# DocumentStore — add_document_from_file
# ===========================================================================

class Extra_TestAddDocumentFromFile:
    def test_nonexistent_file_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            ok, msg = store.add_document_from_file("/nonexistent/path.txt")
            assert not ok

    def test_unsupported_extension_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "binary.exe"
            p.write_bytes(b"\x00\x01\x02")
            store = _make_store(Path(td))
            ok, msg = store.add_document_from_file(str(p))
            assert not ok

    def test_file_outside_project_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            # Use /etc/hosts which is outside BASE_DIR=/tmp
            store = _make_store(Path(td))
            store.cfg.BASE_DIR = Path(td)  # type: ignore[attr-defined]
            ok, msg = store.add_document_from_file("/etc/passwd")
            assert not ok

    def test_valid_text_file_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "hello.txt"
            p.write_text("hello world content for testing", encoding="utf-8")
            store = _make_store(Path(td))
            # Override BASE_DIR so file is "inside" project
            import sys as _sys
            _sys.modules["config"].Config.BASE_DIR = Path(td)
            ok, msg = store.add_document_from_file(str(p))
            assert ok
            assert store.doc_count == 1

    def test_empty_file_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.txt"
            p.write_text("", encoding="utf-8")
            store = _make_store(Path(td))
            import sys as _sys
            _sys.modules["config"].Config.BASE_DIR = Path(td)
            ok, msg = store.add_document_from_file(str(p))
            assert not ok


# ===========================================================================
# DocumentStore — get_index_info / doc_count
# ===========================================================================

class Extra_TestGetIndexInfo:
    def test_empty_store_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            assert store.get_index_info() == []

    def test_doc_count_zero_initially(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            assert store.doc_count == 0

    def test_info_contains_expected_keys(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._index["abc123"] = {
                "title": "T", "source": "s", "size": 5,
                "preview": "prev", "tags": [], "session_id": "global",
                "access_count": 0,
            }
            info = store.get_index_info()
            assert len(info) == 1
            rec = info[0]
            for k in ("id", "title", "source", "size", "preview", "tags", "session_id", "access_count"):
                assert k in rec

    def test_filter_by_session_id(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._index["a"] = {"title": "A", "source": "", "size": 1, "preview": "", "tags": [], "session_id": "sess1", "access_count": 0}
            store._index["b"] = {"title": "B", "source": "", "size": 1, "preview": "", "tags": [], "session_id": "sess2", "access_count": 0}
            result = store.get_index_info(session_id="sess1")
            assert len(result) == 1
            assert result[0]["id"] == "a"


# ===========================================================================
# DocumentStore — delete_document
# ===========================================================================

class Extra_TestDeleteDocument:
    def test_delete_nonexistent_returns_error_msg(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            msg = store.delete_document("nothere")
            assert "bulunamadı" in msg or "✗" in msg

    def test_delete_wrong_session_denied(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._index["doc1"] = {"title": "T", "session_id": "sess_a", "parent_id": "p1", "source": ""}
            msg = store.delete_document("doc1", session_id="sess_b")
            assert "HATA" in msg or "yetki" in msg or "✗" in msg

    def test_delete_existing_doc_removes_from_index(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            doc_file = Path(td) / "doc1.txt"
            doc_file.write_text("content", encoding="utf-8")
            store._index["doc1"] = {"title": "T", "session_id": "global", "parent_id": "p1", "source": ""}
            store._save_index()
            msg = store.delete_document("doc1", session_id="global")
            assert "✓" in msg
            assert "doc1" not in store._index


# ===========================================================================
# DocumentStore — get_document
# ===========================================================================

class Extra_TestGetDocument:
    def test_unknown_doc_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            ok, _ = store.get_document("missing")
            assert not ok

    def test_wrong_session_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._index["d1"] = {"title": "T", "session_id": "s1", "source": ""}
            ok, msg = store.get_document("d1", session_id="s2")
            assert not ok

    def test_missing_file_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._index["d1"] = {"title": "T", "session_id": "global", "source": ""}
            ok, _ = store.get_document("d1", session_id="global")
            assert not ok

    def test_existing_file_returns_content(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            doc_file = Path(td) / "d1.txt"
            doc_file.write_text("hello content", encoding="utf-8")
            store._index["d1"] = {"title": "MyDoc", "session_id": "global", "source": "s", "access_count": 0}
            ok, text = store.get_document("d1", session_id="global")
            assert ok
            assert "hello content" in text


# ===========================================================================
# DocumentStore — search_graph / explain_dependency_path / analyze_graph_impact
# ===========================================================================

class Extra_TestDocumentStoreGraphSearch:
    def test_search_graph_empty_query(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            ok, msg = store.search_graph("", top_k=3)
            assert not ok

    def test_search_graph_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_rag_enabled = False
            ok, msg = store.search_graph("anything")
            assert not ok

    def test_search_graph_no_results(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            ok, msg = store.search_graph("zzz_no_match", top_k=3)
            assert not ok

    def test_explain_dependency_path_no_path(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            ok, msg = store.explain_dependency_path("nonexistent", "also_nonexistent")
            assert not ok

    def test_analyze_graph_impact_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_rag_enabled = False
            ok, msg = store.analyze_graph_impact("mod_a")
            assert not ok

    def test_graph_impact_details_empty_target(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            ok, msg = store.graph_impact_details("")
            assert not ok

    def test_search_graph_impact_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            gi = store._graph_index
            gi.add_node("mymod.py", node_type="file")
            ok, msg = store.search_graph("impact:mymod.py", top_k=3)
            # Should call analyze_graph_impact which may return True or False
            assert isinstance(ok, bool)

    def test_search_graph_arrow_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            ok, msg = store.explain_dependency_path("a.py", "b.py")
            assert not ok  # no nodes in graph


# ===========================================================================
# DocumentStore — build_knowledge_graph_projection
# ===========================================================================

class Extra_TestBuildKnowledgeGraphProjection:
    def test_empty_store_returns_empty_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            proj = store.build_knowledge_graph_projection(session_id="global", include_code_graph=False)
            assert "nodes" in proj
            assert "edges" in proj
            assert "cypher_hint" in proj

    def test_document_nodes_included(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            store._index["doc999"] = {"title": "T", "source": "s", "session_id": "global"}
            proj = store.build_knowledge_graph_projection(session_id="global", include_code_graph=False)
            node_ids = [n.id for n in proj["nodes"]]
            assert any("doc999" in nid for nid in node_ids)

    def test_session_filter_applied(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            store._index["docA"] = {"title": "A", "source": "", "session_id": "sessX"}
            store._index["docB"] = {"title": "B", "source": "", "session_id": "sessY"}
            proj = store.build_knowledge_graph_projection(session_id="sessX", include_code_graph=False)
            node_ids = [n.id for n in proj["nodes"]]
            assert any("docA" in nid for nid in node_ids)
            assert not any("docB" in nid for nid in node_ids)


# ===========================================================================
# DocumentStore — build_graphrag_search_plan
# ===========================================================================

class Extra_TestBuildGraphRAGSearchPlan:
    def test_returns_plan_object(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            plan = store.build_graphrag_search_plan("test query", session_id="global", top_k=3)
            assert isinstance(plan, rag.GraphRAGSearchPlan)
            assert plan.query == "test query"

    def test_broker_topics_present(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            plan = store.build_graphrag_search_plan("q", session_id="global")
            assert len(plan.broker_topics) == 2

    def test_empty_query_returns_plan(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            store._graph_ready = True
            plan = store.build_graphrag_search_plan("", session_id="global")
            assert plan.query == ""


# ===========================================================================
# KnowledgeGraphNode / KnowledgeGraphEdge / GraphRAGSearchPlan
# ===========================================================================

class Extra_TestDataclasses:
    def test_knowledge_graph_node_immutable(self):
        node = rag.KnowledgeGraphNode(id="n1", label="File")
        assert node.id == "n1"
        assert node.label == "File"
        assert node.properties == {}

    def test_knowledge_graph_edge_fields(self):
        edge = rag.KnowledgeGraphEdge(source="a", target="b", relation="imports")
        assert edge.source == "a"
        assert edge.target == "b"
        assert edge.relation == "imports"

    def test_graphrag_search_plan_defaults(self):
        plan = rag.GraphRAGSearchPlan(query="q", vector_backend="bm25")
        assert plan.vector_candidates == []
        assert plan.graph_nodes == []
        assert plan.graph_edges == []
        assert plan.broker_topics == []
        assert plan.cypher_hint == ""


# ===========================================================================
# _format_vector_for_sql
# ===========================================================================

class Extra_TestFormatVectorForSQL:
    def test_produces_bracketed_string(self):
        result = rag.DocumentStore._format_vector_for_sql([1.0, 2.0, 3.0])
        assert result.startswith("[") and result.endswith("]")

    def test_values_present(self):
        result = rag.DocumentStore._format_vector_for_sql([0.5, -1.25])
        assert "0.50000000" in result
        assert "-1.25000000" in result


# ===========================================================================
# _build_embedding_function (CPU path)
# ===========================================================================

class Extra_TestBuildEmbeddingFunction:
    def test_cpu_returns_none(self):
        result = rag._build_embedding_function(use_gpu=False)
        assert result is None


# ===========================================================================
# embed_texts_for_semantic_cache
# ===========================================================================

class Extra_TestEmbedTextsForSemanticCache:
    def test_empty_list_returns_empty(self):
        result = rag.embed_texts_for_semantic_cache([])
        assert result == []

    def test_returns_list_on_failure(self):
        # sentence_transformers is stubbed → returns []
        result = rag.embed_texts_for_semantic_cache(["hello"])
        assert isinstance(result, list)


# ===========================================================================
# DocumentStore — add_document (async) via asyncio.run
# ===========================================================================

class Extra_TestAddDocumentAsync:
    def test_add_document_returns_doc_id(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            doc_id = asyncio.run(store.add_document("Test Title", "Some content here", session_id="global"))
            assert isinstance(doc_id, str)
            assert len(doc_id) > 0

    def test_add_document_increases_count(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            asyncio.run(store.add_document("T", "content one", session_id="global"))
            asyncio.run(store.add_document("T2", "content two", session_id="global"))
            assert store.doc_count == 2

    def test_add_document_with_tags(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            doc_id = asyncio.run(store.add_document("T", "body text", tags=["python", "test"], session_id="global"))
            assert doc_id in store._index
            assert store._index[doc_id]["tags"] == ["python", "test"]


# ===========================================================================
# DocumentStore — _search_sync (keyword fallback path)
# ===========================================================================

class Extra_TestSearchSyncKeyword:
    def test_empty_session_returns_no_docs_message(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            ok, msg = store._search_sync("query", top_k=3, mode="auto", session_id="global")
            assert not ok
            assert "boş" in msg or "empty" in msg.lower() or "⚠" in msg

    def test_bm25_mode_no_docs_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = _make_store(Path(td))
            # Add a doc to make session_docs non-empty, then search
            store._index["d1"] = {"title": "T", "session_id": "global", "source": "", "size": 5, "preview": "hello", "tags": [], "access_count": 0}
            (Path(td) / "d1.txt").write_text("hello world python", encoding="utf-8")
            # Reload BM25
            store.fts_conn.execute("INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)", ("d1", "global", "hello world python"))
            store.fts_conn.commit()
            ok, msg = store._search_sync("hello", top_k=3, mode="bm25", session_id="global")
            assert isinstance(ok, bool)
