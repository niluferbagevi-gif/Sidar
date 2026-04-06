from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import core.rag as rag


def _make_store_stub(tmp_path: Path) -> rag.DocumentStore:
    store = rag.DocumentStore.__new__(rag.DocumentStore)
    store.cfg = SimpleNamespace(RAG_CHUNK_SIZE=12, RAG_CHUNK_OVERLAP=3)
    store._chunk_size = 12
    store._chunk_overlap = 3
    store.store_dir = tmp_path
    store.index_file = tmp_path / "index.json"
    store._index = {}
    return store


def test_graph_index_basic_node_edge_operations(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_edge("a.py", "b.py", kind="imports")

    assert graph.neighbors("a.py") == ["b.py"]
    assert graph.reverse_neighbors("b.py") == ["a.py"]
    assert graph.edge_kinds[("a.py", "b.py")] == {"imports"}

    graph.clear()
    assert graph.nodes == {}
    assert graph.edges == {}


def test_graph_index_normalizers_and_extract_str_literal(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    nested = tmp_path / "src" / "api.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("print('x')", encoding="utf-8")

    assert rag.GraphIndex._normalize_node_id(tmp_path, nested) == "src/api.py"
    assert rag.GraphIndex._endpoint_node_id("get", "health") == "endpoint:GET /health"

    import ast

    assert graph._extract_str_literal(ast.parse("'abc'").body[0].value) == "abc"
    assert graph._extract_str_literal(ast.parse("123").body[0].value) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/users", "/api/users"),
        ("https://localhost:8080/v1/x", "/v1/x"),
        ("http://127.0.0.1:9000", "/"),
        ("users", None),
        ("https://example.com/api", None),
        ("/api/{id}", None),
    ],
)
def test_graph_index_normalize_endpoint_path(tmp_path: Path, raw: str, expected: str | None) -> None:
    graph = rag.GraphIndex(tmp_path)

    assert graph._normalize_endpoint_path(raw) == expected


def test_graph_index_python_and_script_import_candidates(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("", encoding="utf-8")
    current = pkg / "caller.py"
    current.write_text("", encoding="utf-8")

    py_candidates = rag.GraphIndex._python_import_candidates(current, "mod", 0, root)
    assert (pkg / "mod.py").resolve() in py_candidates

    js_file = pkg / "util.js"
    js_file.write_text("", encoding="utf-8")
    script_candidates = rag.GraphIndex._script_import_candidates(current, "./util", root)
    assert js_file.resolve() in script_candidates


def test_graph_index_parse_python_source_extracts_deps_defs_calls(tmp_path: Path) -> None:
    root = tmp_path
    app_file = root / "app.py"
    dep = root / "dep.py"
    dep.write_text("", encoding="utf-8")
    app_file.write_text("", encoding="utf-8")

    content = """
import dep

@app.get('/health')
def health():
    return {'ok': True}

def call_it():
    requests.get('/api/ping')
"""
    graph = rag.GraphIndex(root)
    deps, defs, calls = graph._parse_python_source(app_file, content)

    assert dep.resolve() in deps
    assert defs[0]["endpoint_id"] == "endpoint:GET /health"
    assert calls[0]["endpoint_id"] == "endpoint:GET /api/ping"


def test_graph_index_parse_python_source_handles_syntax_error(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    deps, defs, calls = graph._parse_python_source(tmp_path / "bad.py", "def broken(:\n")

    assert deps == [] and defs == [] and calls == []


def test_graph_index_extract_script_calls_deduplicates(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    content = """
fetch('/api/items', { method: 'POST' })
fetch('/api/items', { method: 'POST' })
new WebSocket('ws://localhost/ws/stream')
"""

    calls = graph._extract_script_endpoint_calls(content)

    ids = {c["endpoint_id"] for c in calls}
    assert "endpoint:POST /api/items" in ids
    assert "endpoint:WS /ws/stream" in ids
    assert len(calls) == 2


def test_graph_index_rebuild_resolve_search_and_impact(tmp_path: Path) -> None:
    root = tmp_path
    (root / "dep.py").write_text("", encoding="utf-8")
    (root / "api.py").write_text(
        "import dep\n@app.get('/health')\ndef health():\n    return 'ok'\nrequests.get('/health')\n",
        encoding="utf-8",
    )
    (root / "caller.js").write_text("fetch('/health')", encoding="utf-8")

    graph = rag.GraphIndex(root)
    summary = graph.rebuild()

    assert summary["nodes"] >= 4
    assert summary["edges"] >= 3
    assert graph.resolve_node_id("API.PY") == "api.py"
    assert graph.resolve_node_id("health") == "endpoint:GET /health"

    path = graph.explain_dependency_path("caller.js", "dep.py")
    assert path == ["caller.js", "endpoint:GET /health", "api.py", "dep.py"]

    impact = graph.impact_analysis("dep.py", max_depth=5)
    assert impact["risk_level"] == "high"
    assert "api.py" in impact["review_targets"]

    related = graph.search_related("api health", top_k=3)
    assert related and related[0]["score"] >= 1


def test_graph_index_collect_bfs_and_extract_dependencies_non_python(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    adjacency = {"a": {"b", "c"}, "b": {"d"}, "c": set(), "d": set()}

    assert graph._collect_bfs("a", adjacency, max_depth=2) == {"b": 1, "c": 1, "d": 2}
    assert graph._collect_bfs("x", adjacency, max_depth=2) == {}

    file_path = tmp_path / "ui.js"
    dep = tmp_path / "mod.js"
    dep.write_text("", encoding="utf-8")
    content = "import './mod'; fetch('/ok')"
    deps, defs, calls = graph._extract_dependencies(file_path, content)
    assert dep.resolve() in deps
    assert defs == []
    assert calls[0]["path"] == "/ok"


def test_embed_texts_for_semantic_cache_empty() -> None:
    assert rag.embed_texts_for_semantic_cache([]) == []


def test_build_embedding_function_returns_none_without_gpu() -> None:
    assert rag._build_embedding_function(use_gpu=False) is None


def test_document_store_helper_methods(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    assert rag.DocumentStore._normalize_pg_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert rag.DocumentStore._format_vector_for_sql([0.1, 2, 3.333333333]) == "[0.10000000,2.00000000,3.33333333]"

    chunks = store._recursive_chunk_text("class A\ndef x():\n    pass\n" * 4, size=20, overlap=5)
    assert chunks
    assert max(len(c) for c in chunks) >= 20

    assert store._chunk_text("abcdef", chunk_size=0) == []
    chunked = store._chunk_text("abcdefghijklmno", chunk_size=5, chunk_overlap=-2)
    assert chunked


def test_document_store_validate_url_safe_accepts_and_blocks() -> None:
    rag.DocumentStore._validate_url_safe("https://example.com/resource")

    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("ftp://example.com/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://127.0.0.1/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("https://localhost/a")


def test_document_store_index_get_delete_and_status(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    class _DummyLock:
        def __enter__(self) -> "_DummyLock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._bm25_available = True
    store._vector_backend = "chroma"
    store._use_gpu = False
    store._gpu_device = 0
    store._graph_rag_enabled = False

    doc_id = "abc123"
    (tmp_path / f"{doc_id}.txt").write_text("body", encoding="utf-8")
    store._index[doc_id] = {"title": "Doc", "source": "src", "session_id": "s1", "size": 4, "tags": ["t"]}

    docs = store.get_index_info(session_id="s1")
    assert docs[0]["id"] == doc_id
    assert store.doc_count == 1

    ok, text = store.get_document(doc_id, session_id="s1")
    assert ok is True
    assert "Doc" in text

    denied_ok, denied = store.get_document(doc_id, session_id="s2")
    assert denied_ok is False
    assert "yetkiniz yok" in denied

    result = store.delete_document(doc_id, session_id="s1")
    assert "Belge silindi" in result
    assert store.doc_count == 0
    assert "BM25" in store.status()


def test_document_store_clean_html_with_and_without_bleach(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<script>alert(1)</script><p>Hello&nbsp; <b>World</b></p>"

    monkeypatch.setattr(rag, "_BLEACH_AVAILABLE", False)
    cleaned = rag.DocumentStore._clean_html(html)
    assert "alert" not in cleaned
    assert "Hello" in cleaned and "World" in cleaned

    class _FakeBleach:
        @staticmethod
        def clean(_html: str, **_: object) -> str:
            return "<ignored>Clean Text</ignored>"

    monkeypatch.setattr(rag, "_BLEACH_AVAILABLE", True)
    monkeypatch.setattr(rag, "_bleach", _FakeBleach)
    assert rag.DocumentStore._clean_html(html) == "<ignored>Clean Text</ignored>"


def test_document_store_consolidate_session_documents_skip_paths(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    # keep_recent_docs eşiğinin altında: direkt skip
    store._index = {"a": {"session_id": "s1", "created_at": 1}}
    skip_by_count = store.consolidate_session_documents("s1", keep_recent_docs=2)
    assert skip_by_count["status"] == "skipped"
    assert skip_by_count["removed_docs"] == 0

    # Dokümanlar var ama removable yok (pinned / access_count>1): yine skip
    store._index = {
        "a": {"session_id": "s1", "created_at": 1, "tags": ["pinned"]},
        "b": {"session_id": "s1", "created_at": 2, "access_count": 10},
        "c": {"session_id": "s1", "created_at": 3, "tags": ["memory-summary"]},
    }
    skip_no_removable = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert skip_no_removable["status"] == "skipped"
    assert skip_no_removable["removed_docs"] == 0


def test_document_store_consolidate_session_documents_completed_flow(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "digest-old": {"session_id": "s1", "source": "memory://nightly-digest/2026-01-01", "created_at": 1},
        "keep-new": {"session_id": "s1", "title": "Keep", "created_at": 99, "access_count": 2},
        "drop-1": {"session_id": "s1", "title": "Drop1", "created_at": 3, "access_count": 0, "preview": "foo"},
        "drop-2": {"session_id": "s1", "title": "Drop2", "created_at": 2, "access_count": 0, "preview": "bar"},
    }

    deleted: list[tuple[str, str]] = []
    store.delete_document = lambda doc_id, sid: deleted.append((doc_id, sid)) or "ok"  # type: ignore[assignment]
    store._add_document_sync = lambda **_kwargs: "summary-1"  # type: ignore[assignment]

    result = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert result["status"] == "completed"
    assert result["summary_doc_id"] == "summary-1"
    assert result["removed_docs"] == 3
    # eski digest + removable dokümanlar silinmeli
    assert deleted.count(("digest-old", "s1")) >= 1
    assert ("drop-1", "s1") in deleted
    assert ("drop-2", "s1") in deleted


def test_document_store_list_documents_empty_and_populated(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    assert "boş" in store.list_documents(session_id="none")

    store._index = {
        "doc1": {"title": "Title 1", "source": "src://a", "size": 2048, "tags": ["x"], "session_id": "s1"},
        "doc2": {"title": "Title 2", "source": "src://b", "size": 512, "tags": [], "session_id": "s2"},
    }
    listed = store.list_documents(session_id="s1")
    assert "Title 1" in listed
    assert "src://a" in listed
    assert "Title 2" not in listed


def test_document_store_status_engine_variants(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {}
    store._bm25_available = True
    store._chroma_available = False
    store._graph_rag_enabled = False

    store._pgvector_available = True
    store._vector_backend = "chroma"
    store._use_gpu = False
    store._gpu_device = 0
    assert "pgvector" in store.status()

    store._pgvector_available = False
    store._vector_backend = "pgvector"
    assert "pgvector (pasif)" in store.status()

    store._vector_backend = "chroma"
    store._chroma_available = True
    store._use_gpu = True
    store._gpu_device = 1
    status = store.status()
    assert "ChromaDB (Chunking + GPU cuda:1)" in status
    assert "BM25 (SQLite FTS5)" in status
    assert "Anahtar Kelime" in status
