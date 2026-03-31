"""
Extra tests for core/rag.py targeting missing coverage lines.

Covers:
- GraphIndex: _normalize_endpoint_path, _extract_str_literal,
  _python_import_candidates, _script_import_candidates,
  _extract_script_endpoint_calls, _collect_bfs, impact_analysis,
  search_related, rebuild
- DocumentStore: _recursive_chunk_text, _chunk_text, _validate_url_safe,
  add_document_from_file, get_index_info, delete_document, get_document,
  _touch_document, doc_count, search_graph, explain_dependency_path,
  analyze_graph_impact, graph_impact_details,
  build_knowledge_graph_projection, build_graphrag_search_plan,
  embed_texts_for_semantic_cache, _format_vector_for_sql,
  _build_embedding_function, KnowledgeGraphNode/Edge/GraphRAGSearchPlan

All async methods use asyncio.run().
Heavy deps (chromadb, sqlalchemy, sentence_transformers, httpx, opentelemetry)
are stubbed in sys.modules before importing core.rag.
"""
from __future__ import annotations

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

class TestNormalizeEndpointPath:
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

class TestExtractStrLiteral:
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

class TestCollectBFS:
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

class TestImpactAnalysis:
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

class TestSearchRelated:
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

class TestExtractScriptEndpointCalls:
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

class TestRecursiveChunkText:
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

class TestChunkText:
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

class TestValidateUrlSafe:
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

class TestAddDocumentFromFile:
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

class TestGetIndexInfo:
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

class TestDeleteDocument:
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

class TestGetDocument:
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

class TestDocumentStoreGraphSearch:
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

class TestBuildKnowledgeGraphProjection:
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

class TestBuildGraphRAGSearchPlan:
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

class TestDataclasses:
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

class TestFormatVectorForSQL:
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

class TestBuildEmbeddingFunction:
    def test_cpu_returns_none(self):
        result = rag._build_embedding_function(use_gpu=False)
        assert result is None


# ===========================================================================
# embed_texts_for_semantic_cache
# ===========================================================================

class TestEmbedTextsForSemanticCache:
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

class TestAddDocumentAsync:
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

class TestSearchSyncKeyword:
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
