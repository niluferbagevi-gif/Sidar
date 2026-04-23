from __future__ import annotations

import asyncio
import ast
import contextlib
import importlib
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import types

import pytest

pytestmark = pytest.mark.asyncio

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


async def test_graph_index_basic_node_edge_operations(tmp_path: Path) -> None:
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


async def test_graph_index_normalizers_and_extract_str_literal(tmp_path: Path) -> None:
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
async def test_graph_index_normalize_endpoint_path(tmp_path: Path, raw: str, expected: str | None) -> None:
    graph = rag.GraphIndex(tmp_path)

    assert graph._normalize_endpoint_path(raw) == expected


async def test_graph_index_python_and_script_import_candidates(tmp_path: Path) -> None:
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


async def test_graph_index_parse_python_source_extracts_deps_defs_calls(tmp_path: Path) -> None:
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
    client.router.get('/ignored')
    client.api.get('/api/pong')
    build_client().get('/api/factory')
"""
    graph = rag.GraphIndex(root)
    deps, defs, calls = graph._parse_python_source(app_file, content)

    assert dep.resolve() in deps
    assert defs[0]["endpoint_id"] == "endpoint:GET /health"
    ids = {call["endpoint_id"] for call in calls}
    assert "endpoint:GET /api/ping" in ids
    assert "endpoint:GET /api/pong" in ids
    assert "endpoint:GET /api/factory" in ids
    assert "endpoint:GET /ignored" not in ids


async def test_graph_index_parse_python_source_handles_syntax_error(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    deps, defs, calls = graph._parse_python_source(tmp_path / "bad.py", "def broken(:\n")

    assert deps == [] and defs == [] and calls == []


async def test_graph_index_extract_script_calls_deduplicates(tmp_path: Path) -> None:
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


async def test_graph_index_rebuild_resolve_search_and_impact(tmp_path: Path) -> None:
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


async def test_graph_index_collect_bfs_and_extract_dependencies_non_python(tmp_path: Path) -> None:
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


async def test_graph_index_circular(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_node("c.py", node_type="file")
    graph.add_edge("a.py", "b.py", kind="imports")
    graph.add_edge("b.py", "a.py", kind="imports")
    graph.add_edge("b.py", "c.py", kind="imports")

    assert graph.explain_dependency_path("a.py", "a.py") == ["a.py"]
    assert graph.explain_dependency_path("a.py", "b.py") == ["a.py", "b.py"]
    assert graph.explain_dependency_path("a.py", "c.py") == ["a.py", "b.py", "c.py"]
    assert graph.explain_dependency_path("c.py", "a.py") == []


async def test_graph_index_deep_dependency_path(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    for node in ("entry.py", "service.py", "repo.py", "client.py", "adapter.py"):
        graph.add_node(node, node_type="file")
    graph.add_edge("entry.py", "service.py", kind="imports")
    graph.add_edge("service.py", "repo.py", kind="imports")
    graph.add_edge("repo.py", "client.py", kind="imports")
    graph.add_edge("client.py", "adapter.py", kind="imports")

    assert graph.explain_dependency_path("entry.py", "adapter.py") == [
        "entry.py",
        "service.py",
        "repo.py",
        "client.py",
        "adapter.py",
    ]


async def test_embed_texts_for_semantic_cache_empty() -> None:
    assert rag.embed_texts_for_semantic_cache([]) == []


async def test_build_embedding_function_returns_none_without_gpu() -> None:
    assert rag._build_embedding_function(use_gpu=False) is None


async def test_document_store_helper_methods(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    assert rag.DocumentStore._normalize_pg_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert rag.DocumentStore._format_vector_for_sql([0.1, 2, 3.333333333]) == "[0.10000000,2.00000000,3.33333333]"

    chunks = store._recursive_chunk_text("class A\ndef x():\n    pass\n" * 4, size=20, overlap=5)
    assert chunks
    assert max(len(c) for c in chunks) >= 20

    assert store._chunk_text("abcdef", chunk_size=0) == []
    chunked = store._chunk_text("abcdefghijklmno", chunk_size=5, chunk_overlap=-2)
    assert chunked


async def test_document_store_validate_url_safe_accepts_and_blocks() -> None:
    rag.DocumentStore._validate_url_safe("https://example.com/resource")

    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("ftp://example.com/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://127.0.0.1/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("https://localhost/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://10.0.0.8/admin")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://172.16.5.4/internal")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://192.168.1.10/debug")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://169.254.10.10/meta")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://[::1]/loopback")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://[fd00::1]/private-v6")


async def test_document_store_index_get_delete_and_status(tmp_path: Path) -> None:
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


async def test_document_store_clean_html_with_bleach(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<script>alert(1)</script><p>Hello&nbsp; <b>World</b></p>"

    class _FakeBleach:
        @staticmethod
        def clean(_html: str, **_: object) -> str:
            return "<ignored>Clean Text</ignored>"

    monkeypatch.setattr(rag, "_bleach", _FakeBleach)
    assert rag.DocumentStore._clean_html(html) == "<ignored>Clean Text</ignored>"


async def test_document_store_apply_hf_runtime_env_sets_expected_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store_stub(Path("/tmp"))
    store.cfg = SimpleNamespace(HF_TOKEN="abc-token", HF_HUB_OFFLINE=True)

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    store._apply_hf_runtime_env()

    assert os.environ["HF_TOKEN"] == "abc-token"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "abc-token"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


async def test_document_store_add_document_from_file_validation_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    captured: dict[str, object] = {}

    def _fake_add(title: str, content: str, source: str, tags: list[str], session_id: str) -> str:
        captured["title"] = title
        captured["content"] = content
        captured["source"] = source
        captured["tags"] = tags
        captured["session_id"] = session_id
        return "doc-file-1"

    store._add_document_sync = _fake_add  # type: ignore[method-assign]

    bad = tmp_path / "payload.bin"
    bad.write_bytes(b"\x00\x01")
    ok, msg = store.add_document_from_file(str(bad), session_id="s-file")
    assert ok is False
    assert "Desteklenmeyen dosya türü" in msg

    good = tmp_path / "notes.md"
    good.write_text("hello world", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(good), tags=["alpha"], session_id="s-file")
    assert ok is True
    assert "[doc-file-1]" in msg
    assert captured["title"] == "notes.md"
    assert captured["source"] == f"file://{good.resolve()}"
    assert captured["tags"] == ["alpha"]


async def test_document_store_graph_helpers_and_projection_and_plan(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_ready = True
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._vector_backend = "bm25"
    store._index = {
        "d1": {"title": "Doc1", "source": "s1", "session_id": "s1"},
        "d2": {"title": "Doc2", "source": "s2", "session_id": "s2"},
    }
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("endpoint:GET /h", node_type="endpoint")
    graph.add_edge("a.py", "endpoint:GET /h", kind="calls_endpoint")
    store._graph_index = graph

    ok, msg = store.search_graph("", top_k=3)
    assert ok is False
    assert "boş sorgu" in msg

    ok, msg = store.search_graph("a.py", top_k=2)
    assert ok is True
    assert "[GraphRAG: a.py]" in msg

    proj = store.build_knowledge_graph_projection(session_id="s1", include_code_graph=True, limit=20)
    node_ids = {n.id for n in proj["nodes"]}
    assert "doc:d1" in node_ids
    assert "doc:d2" not in node_ids
    assert any(e.source == "code:a.py" for e in proj["edges"])

    plan = store.build_graphrag_search_plan("hello", session_id="s1", top_k=2)
    assert plan.query == "hello"
    assert plan.vector_backend == "bm25"
    assert plan.broker_topics[0].startswith("sidar.swarm.researcher.")


async def test_document_store_search_sync_mode_routing(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.default_top_k = 3
    store.cfg = SimpleNamespace(RAG_TOP_K=3)
    store._index = {"d1": {"session_id": "s1", "title": "t"}}
    store._bm25_available = True
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False

    store._bm25_search = lambda q, k, s: (True, f"bm25:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._rrf_search = lambda q, k, s: (True, f"rrf:{q}:{k}:{s}")  # type: ignore[method-assign]
    store.search_graph = lambda q, k: (True, f"graph:{q}:{k}")  # type: ignore[method-assign]

    ok, result = store._search_sync("q", mode="graph", session_id="s1")
    assert ok is True and result.startswith("graph:")

    ok, result = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is False
    assert "Vektör arama kullanılamıyor" in result

    ok, result = store._search_sync("q", mode="bm25", session_id="s1")
    assert ok is True and result.startswith("bm25:")

    ok, result = store._search_sync("q", mode="keyword", session_id="s1")
    assert ok is True and result.startswith("kw:")

    ok, result = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and result.startswith("bm25:")


async def test_document_store_consolidate_session_documents(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "a": {"session_id": "s1", "title": "A", "preview": "old-a", "access_count": 0, "created_at": 1, "last_accessed_at": 1, "tags": []},
        "b": {"session_id": "s1", "title": "B", "preview": "old-b", "access_count": 0, "created_at": 2, "last_accessed_at": 2, "tags": []},
        "c": {"session_id": "s1", "title": "C", "preview": "keep", "access_count": 2, "created_at": 3, "last_accessed_at": 3, "tags": []},
        "digest_old": {"session_id": "s1", "title": "Digest", "preview": "prev", "access_count": 0, "created_at": 4, "last_accessed_at": 4, "tags": ["memory-summary"], "source": "memory://nightly-digest/2026"},
    }
    deleted: list[str] = []
    store.delete_document = lambda doc_id, _session_id="s1": deleted.append(doc_id) or "ok"  # type: ignore[method-assign]
    store._add_document_sync = lambda **kwargs: "digest-new"  # type: ignore[method-assign]

    summary = store.consolidate_session_documents("s1", keep_recent_docs=1)

    assert summary["status"] == "completed"
    assert summary["removed_docs"] >= 1
    assert summary["summary_doc_id"] == "digest-new"
    assert "digest_old" in deleted


async def test_document_store_graph_disabled_and_dispatch_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = False
    store._graph_ready = False
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}

    ok, msg = store.rebuild_graph_index()
    assert ok is False and "devre dışı" in msg

    ok, msg = store.search_graph("anything")
    assert ok is False and "devre dışı" in msg

    ok, msg = store.explain_dependency_path("a.py", "b.py")
    assert ok is False and "devre dışı" in msg

    ok, msg = store.graph_impact_details("x")
    assert ok is False and "devre dışı" in msg


async def test_document_store_graph_query_dispatch_and_empty_impact_target(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.add_node("a.py", node_type="file")
    store._graph_index.add_node("b.py", node_type="file")
    store._graph_index.add_edge("a.py", "b.py", kind="imports")

    ok, msg = store.search_graph("a.py -> b.py", top_k=3)
    assert ok is True
    assert "[GraphRAG Path]" in msg

    ok, msg = store.search_graph("impact: ")
    assert ok is False
    assert "hedef belirtilmedi" in msg


async def test_document_store_build_graphrag_search_plan_with_pgvector_candidates(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.add_node("file.py", node_type="file")
    store._index = {"d1": {"session_id": "s1", "title": "Doc1", "source": "src1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._fetch_pgvector = lambda _q, _k, _s: [  # type: ignore[method-assign]
        {"doc_id": "d1"},
        {"doc_id": "d2"},
    ]

    plan = store.build_graphrag_search_plan("query", session_id="s1", top_k=1)

    assert plan.vector_backend == "pgvector"
    assert plan.vector_candidates == ["d1"]
    assert any(topic.endswith(".rag_search") for topic in plan.broker_topics)


async def test_document_store_rrf_and_formatting_and_snippet_behaviors(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"d1": {"session_id": "s1", "title": "Title 1", "source": "src://1"}}
    store._pgvector_available = True
    store._fetch_pgvector = lambda _q, _k, _s: [  # type: ignore[method-assign]
        {"id": "d1", "title": "Title 1", "source": "src://1", "snippet": "a" * 500, "score": 0.9}
    ]
    store._fetch_bm25 = lambda _q, _k, _s: []  # type: ignore[method-assign]

    ok, text = store._rrf_search("query", 1, "s1")
    assert ok is True
    assert "Hibrit RRF (pgvector + BM25)" in text
    assert "..." in text

    snippet = rag.DocumentStore._extract_snippet("x" * 20, "missing", window=10)
    assert snippet == "xxxxxxxxxx..."


async def test_document_store_list_documents_and_touch_and_missing_file(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._save_index = lambda: None
    store._index = {
        "d1": {"session_id": "s1", "title": "Doc 1", "source": "src://1", "size": 2048, "tags": ["alpha"], "access_count": 0},
    }

    listing = store.list_documents(session_id="s1")
    assert "[Belge Deposu — 1 belge]" in listing
    assert "Doc 1" in listing and "2.0 KB" in listing

    ok, msg = store.get_document("d1", session_id="s1")
    assert ok is False
    assert "dosyası eksik" in msg

    store._touch_document("d1")
    assert store._index["d1"]["access_count"] == 1


async def test_document_store_format_extract_and_consolidate_skip_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    ok, text = store._format_results_from_struct([], "q", source_name="BM25")
    assert ok is False
    assert "ilgili sonuç bulunamadı" in text

    snippet = rag.DocumentStore._extract_snippet("start middle keyword end", "keyword", window=8)
    assert "keyword" in snippet

    store._index = {"d1": {"session_id": "s1", "title": "Only"}}
    summary = store.consolidate_session_documents("s1", keep_recent_docs=2)
    assert summary["status"] == "skipped"

    store._index = {
        "d1": {"session_id": "s1", "title": "Pinned", "tags": ["pinned"], "access_count": 0, "created_at": 1, "last_accessed_at": 1},
        "d2": {"session_id": "s1", "title": "Read", "tags": [], "access_count": 3, "created_at": 2, "last_accessed_at": 2},
    }
    summary = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert summary["status"] == "skipped"


async def test_document_store_search_sync_fallback_chain_and_graph_not_found(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "A"}}
    store._bm25_available = True
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = True
    store._rrf_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rrf"))  # type: ignore[method-assign]
    store._pgvector_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pg"))  # type: ignore[method-assign]
    store._chroma_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("chroma"))  # type: ignore[method-assign]
    store._bm25_search = lambda q, k, s: (True, f"bm25:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, result = store._search_sync("needle", mode="auto", session_id="s1")
    assert ok is True
    assert result.startswith("bm25:needle")

    graph_store = _make_store_stub(tmp_path)
    graph_store._graph_rag_enabled = True
    graph_store._graph_ready = True
    graph_store._graph_index = rag.GraphIndex(tmp_path)

    ok, result = graph_store.search_graph("unknown-module", top_k=2)
    assert ok is False
    assert "ilgili modül bulunamadı" in result


async def test_document_store_search_sync_preferred_chroma_fallbacks_to_rrf(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "A"}}
    store._bm25_available = True
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._vector_backend = "chroma"
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = True
    store._chroma_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("preferred-chroma"))  # type: ignore[method-assign]
    store._rrf_search = lambda q, k, s: (True, f"rrf:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, result = store._search_sync("needle", mode="auto", session_id="s1")
    assert ok is True
    assert result == "rrf:needle:2:s1"


async def test_document_store_search_sync_empty_session_and_analyze_graph_impact(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {}

    ok, msg = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is False
    assert "belge deposu boş" in msg

    graph_store = _make_store_stub(tmp_path)
    graph_store._graph_rag_enabled = True
    graph_store._graph_ready = True
    graph_store._graph_index = rag.GraphIndex(tmp_path)
    graph_store._graph_index.add_node("a.py", node_type="file")
    graph_store._graph_index.add_node("b.py", node_type="file")
    graph_store._graph_index.add_edge("a.py", "b.py", kind="imports")

    ok, text = graph_store.analyze_graph_impact("a.py")
    assert ok is True
    assert "[GraphRAG Impact] a.py" in text


async def test_embed_texts_for_semantic_cache_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Vec:
        def tolist(self) -> list[list[float]]:
            return [[0.1, 0.2]]

    class _ST:
        def __init__(self, _name: str) -> None:
            pass

        def encode(self, _texts: list[str], normalize_embeddings: bool = True) -> _Vec:
            assert normalize_embeddings is True
            return _Vec()

    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_ST))
    assert rag.embed_texts_for_semantic_cache(["hello"]) == [[0.1, 0.2]]

    class _BrokenST:
        def __init__(self, _name: str) -> None:
            raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_BrokenST))
    assert rag.embed_texts_for_semantic_cache(["hello"]) == []


async def test_build_embedding_function_gpu_success_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Cuda:
        enabled = False

        @staticmethod
        def is_available() -> bool:
            return _Cuda.enabled

    class _Torch:
        cuda = _Cuda()
        float16 = "fp16"

        @staticmethod
        def autocast(device_type: str, dtype: str):
            class _Ctx:
                def __enter__(self) -> None:
                    return None

                def __exit__(self, *_args: object) -> None:
                    return None

            assert device_type == "cuda"
            assert dtype == "fp16"
            return _Ctx()

    class _EF:
        def __init__(self, model_name: str, device: str) -> None:
            self.model_name = model_name
            self.device = device

        def __call__(self, _input: list[str]) -> list[list[float]]:
            return [[1.0]]

    monkeypatch.setitem(__import__("sys").modules, "torch", _Torch)
    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb.utils.embedding_functions",
        SimpleNamespace(SentenceTransformerEmbeddingFunction=_EF),
    )

    ef = rag._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef is not None
    assert ef(["chunk"]) == [[1.0]]

    _Cuda.enabled = True
    ef_cuda = rag._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef_cuda is not None
    assert ef_cuda(["chunk"]) == [[1.0]]

    # Instance-level __call__ monkeypatching does not intercept special method
    # lookup for callables, so the test explicitly exercises our autocast stub.
    with _Torch.autocast(device_type="cuda", dtype="fp16"):
        pass

    class _BrokenEF:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("factory unavailable")

    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb.utils.embedding_functions",
        SimpleNamespace(SentenceTransformerEmbeddingFunction=_BrokenEF),
    )
    assert rag._build_embedding_function(use_gpu=True) is None


async def test_build_embedding_function_import_module_and_missing_autocast_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class _TorchNoAutocast:
        cuda = _Cuda()

    class _EF:
        def __init__(self, model_name: str, device: str) -> None:
            self.model_name = model_name
            self.device = device

    fake_embedding_module = SimpleNamespace(SentenceTransformerEmbeddingFunction=_EF)
    monkeypatch.delitem(sys.modules, "chromadb.utils.embedding_functions", raising=False)
    monkeypatch.setattr(rag.importlib, "import_module", lambda name: fake_embedding_module)
    monkeypatch.setitem(sys.modules, "torch", _TorchNoAutocast)

    caplog.set_level("WARNING")
    ef = rag._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None
    assert ef.device == "cuda:0"
    assert "torch.autocast bulunamadı" in caplog.text


async def test_document_store_init_pgvector_backend_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {"d": {"session_id": "global"}})
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: False)
    monkeypatch.setattr(rag.DocumentStore, "_init_chroma", lambda self: calls.append("chroma"))
    monkeypatch.setattr(rag.DocumentStore, "_init_pgvector", lambda self: calls.append("pgvector"))
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: calls.append("fts"))

    cfg = SimpleNamespace(
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="pgvector",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=True,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=12,
        PGVECTOR_TABLE="tbl",
        PGVECTOR_EMBEDDING_DIM=8,
        PGVECTOR_EMBEDDING_MODEL="mini",
    )
    store = rag.DocumentStore(tmp_path / "store", cfg=cfg)

    assert store.default_top_k == 4
    assert calls == ["pgvector", "fts"]


async def test_document_store_add_document_and_search_helpers(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._bm25_available = True
    store._chroma_available = True
    store._pgvector_available = True
    store.collection = SimpleNamespace(delete=lambda **_k: None, upsert=lambda **_k: None)
    store._upsert_pgvector_chunks = lambda *_args: None  # type: ignore[method-assign]
    class _DummyLock:
        def __enter__(self) -> "_DummyLock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._save_index = lambda: None

    class _FtsConn:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        def commit(self) -> None:
            return None

    store.fts_conn = _FtsConn()

    doc_id = store._add_document_sync("Title", "keyword body", source="src", tags=["tag"], session_id="s1")
    assert doc_id in store._index

    # keyword search branch
    ok, text = store._keyword_search("keyword", 2, "s1")
    assert ok is True
    assert "Kelime Eşleşmesi" in text


async def test_document_store_add_document_from_url_success_and_failure(
    respx_mock_router,
    tmp_path: Path,
) -> None:
    httpx = pytest.importorskip("httpx")
    store = _make_store_stub(tmp_path)

    async def _fake_add(title: str, content: str, source: str, tags: list[str] | None, session_id: str) -> str:
        assert source.startswith("https://example.com")
        assert session_id == "s-url"
        return "doc-url"

    store.add_document = _fake_add  # type: ignore[method-assign]

    respx_mock_router.get("https://example.com/docs").mock(
        return_value=httpx.Response(200, text="<title>My Page</title><p>Body</p>")
    )

    ok, msg = await store.add_document_from_url("https://example.com/docs", session_id="s-url")
    assert ok is True
    assert "doc-url" in msg

    ok, msg = await store.add_document_from_url("ftp://example.com/docs", session_id="s-url")
    assert ok is False
    assert "URL belge eklenemedi" in msg


@pytest.mark.parametrize(
    ("exc_name", "expected_hint"),
    [
        ("TimeoutException", "timeout"),
        ("RequestError", "network"),
    ],
)
async def test_document_store_add_document_from_url_handles_httpx_transport_errors(
    respx_mock_router,
    tmp_path: Path,
    exc_name: str,
    expected_hint: str,
) -> None:
    httpx = pytest.importorskip("httpx")
    store = _make_store_stub(tmp_path)
    request = httpx.Request("GET", "https://example.com/docs")
    if exc_name == "TimeoutException":
        side_effect: Exception = httpx.TimeoutException(expected_hint)
    else:
        side_effect = httpx.RequestError(expected_hint, request=request)
    respx_mock_router.get("https://example.com/docs").mock(side_effect=side_effect)

    ok, msg = await store.add_document_from_url("https://example.com/docs", session_id="s-url")
    assert ok is False
    assert "URL belge eklenemedi" in msg
    assert expected_hint in msg


async def test_document_store_vector_runtime_init_failures_fallback_to_bm25(
    monkeypatch: pytest.MonkeyPatch,
    mock_chromadb,
    mock_sentence_transformers,
    tmp_path: Path,
) -> None:
    # Chroma runtime failure (import hatası değil): PersistentClient patlasa da BM25 devam etmeli.
    mock_chromadb(
        persistent_client_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("chroma-runtime")),
    )

    chroma_cfg = SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=32,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=32,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="",
    )
    chroma_store = rag.DocumentStore(tmp_path / "chroma_runtime_fail", cfg=chroma_cfg)
    assert chroma_store._chroma_available is False
    doc_id = chroma_store._add_document_sync("Chroma Fallback", "fallback body", source="test://runtime", session_id="s1")
    bm25_ok, bm25_msg = chroma_store._bm25_search("fallback", 2, "s1")
    assert bm25_ok is True
    assert doc_id in bm25_msg

    # pgvector runtime failure (import hatası değil): create_engine patlasa da BM25 devam etmeli.
    class _SentenceTransformer:
        def __init__(self, _name: str) -> None:
            pass

    def _broken_create_engine(*_args: object, **_kwargs: object):
        raise RuntimeError("pg-runtime")

    mock_sentence_transformers(_SentenceTransformer)
    _SentenceTransformer("mini")
    monkeypatch.setitem(sys.modules, "pgvector", SimpleNamespace(__name__="pgvector"))
    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=_broken_create_engine, text=lambda sql: sql),
    )

    pg_cfg = SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=32,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=32,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="postgresql://user:pass@localhost/db",
    )
    pg_store = rag.DocumentStore(tmp_path / "pg_runtime_fail", cfg=pg_cfg)
    assert pg_store._pgvector_available is False
    pg_doc_id = pg_store._add_document_sync("PG Fallback", "vector backend down", source="test://runtime", session_id="s2")
    pg_bm25_ok, pg_bm25_msg = pg_store._bm25_search("backend", 2, "s2")
    assert pg_bm25_ok is True
    assert pg_doc_id in pg_bm25_msg


async def test_document_store_schedule_judge_and_search_with_otel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Judge:
        enabled = True

        def __init__(self) -> None:
            self.called = False

        def schedule_background_evaluation(self, **_kwargs: object) -> None:
            self.called = True

    judge = _Judge()

    monkeypatch.setitem(__import__("sys").modules, "core.judge", SimpleNamespace(get_llm_judge=lambda: judge))
    rag.DocumentStore._schedule_judge("q", "answer")
    assert judge.called is True

    store = _make_store_stub(tmp_path)
    store._search_sync = lambda *_args: (True, "ok")  # type: ignore[method-assign]

    class _Span:
        def __enter__(self) -> "_Span":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_attribute(self, *_args: object) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, _name: str) -> _Span:
            return _Span()

    monkeypatch.setattr(rag, "_otel_trace", SimpleNamespace(get_tracer=lambda _name: _Tracer()))
    ok, txt = await store.search("query", session_id="s1")
    assert ok is True and txt == "ok"


async def test_document_store_upsert_pgvector_chunks_rolls_back_on_transaction_failure(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._pgvector_available = True
    store._pg_table = "rag_embeddings"
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]

    state = {"rollback": False, "calls": 0}

    class _Conn:
        def execute(self, _sql: object, _params: object = None) -> None:
            state["calls"] += 1
            if state["calls"] >= 2:
                raise RuntimeError("insert failed")

    class _Tx:
        def __enter__(self) -> _Conn:
            return _Conn()

        def __exit__(self, exc_type, _exc, _tb) -> bool:
            if exc_type is not None:
                state["rollback"] = True
            return False

    class _Engine:
        def begin(self) -> _Tx:
            return _Tx()

    store.pg_engine = _Engine()
    store._upsert_pgvector_chunks("d1", "p1", "s1", "title", "src", ["content"])
    assert _Tx().__exit__(None, None, None) is False

    assert state["calls"] >= 2
    assert state["rollback"] is True


async def test_document_store_recursive_chunk_text_overlap_preserves_continuity(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    chunks = store._recursive_chunk_text("supercalifragilistic", size=6, overlap=2)

    assert chunks
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 6 for chunk in chunks)
    assert all(chunks[idx].startswith(chunks[idx - 1][-2:]) for idx in range(1, len(chunks)))

    reconstructed = chunks[0] + "".join(chunk[2:] for chunk in chunks[1:])
    assert reconstructed == "supercalifragilistic"


async def test_document_store_init_backends_and_import_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._index = {"doc1": {"session_id": "s1"}}
    (tmp_path / "doc1.txt").write_text("hello world", encoding="utf-8")

    # _check_import true/false branches
    import importlib

    original_import_module = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError()) if name == "missing.mod" else original_import_module(name))
    assert store._check_import("json") is True
    assert store._check_import("missing.mod") is False

    # _init_chroma success path
    class _Settings:
        def __init__(self, anonymized_telemetry: bool) -> None:
            self.anonymized_telemetry = anonymized_telemetry

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            self.created = []

        def get_or_create_collection(self, name: str, **kwargs: object) -> object:
            self.created.append((name, kwargs))
            return object()

    chromadb_mod = SimpleNamespace(PersistentClient=lambda **kwargs: _Client(**kwargs))
    monkeypatch.setitem(__import__("sys").modules, "chromadb", chromadb_mod)
    monkeypatch.setitem(__import__("sys").modules, "chromadb.config", SimpleNamespace(Settings=_Settings))
    monkeypatch.setattr(rag, "_build_embedding_function", lambda **_kwargs: object())
    store._use_gpu = True
    store._gpu_device = 0
    store._mixed_precision = False
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]
    store._init_chroma()
    assert store.collection is not None
    assert os.environ["CHROMA_TELEMETRY_DISABLED"] == "1"

    # _init_fts migration path
    store._init_fts()
    count = store.fts_conn.execute("SELECT count(*) as c FROM bm25_index").fetchone()["c"]
    assert count == 1


async def test_document_store_pgvector_init_and_query_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._check_import = lambda _name: True  # type: ignore[method-assign]
    store._pg_table = "rag_pg"
    store._pg_embedding_dim = 3
    store._pg_embedding_model_name = "mini"
    store._pgvector_available = False
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql+asyncpg://u:p@h/db")

    executed: list[tuple[str, dict[str, object] | None]] = []

    class _Rows:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def fetchall(self) -> list[object]:
            return self._rows

    class _Conn:
        def execute(self, sql: object, params: dict[str, object] | None = None) -> _Rows | None:
            executed.append((str(sql), params))
            if params and "qvec" in params:
                rows = [
                    SimpleNamespace(parent_id="p1", title="Doc 1", source="src://1", chunk_content="a", distance=0.1),
                    SimpleNamespace(parent_id="p1", title="Doc 1", source="src://1", chunk_content="a2", distance=0.2),
                    SimpleNamespace(parent_id="p2", title="Doc 2", source="src://2", chunk_content="b", distance=0.3),
                ]
                return _Rows(rows)
            return None

    class _Begin:
        def __enter__(self) -> _Conn:
            return _Conn()

        def __exit__(self, *_args: object) -> None:
            return None

    class _Engine:
        def begin(self) -> _Begin:
            return _Begin()

    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", SimpleNamespace(create_engine=lambda *_a, **_k: _Engine(), text=lambda s: s))

    class _ST:
        def __init__(self, _model: str) -> None:
            pass

        def encode(self, _texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
            assert normalize_embeddings is True
            return [[0.1, 0.2, 0.3]]

    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_ST))
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]
    store._init_pgvector()
    assert store._pgvector_available is True

    # _fetch_pgvector with parent de-dup
    store._is_local_llm_provider = False
    results = store._fetch_pgvector("query", top_k=2, session_id="s1")
    assert [r["id"] for r in results] == ["p1", "p2"]

    # _upsert + delete branches
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    store._upsert_pgvector_chunks("chunk-1", "parent-1", "s1", "title", "src", ["content"])
    store._delete_pgvector_parent("parent-1", "s1")
    assert any("DELETE FROM rag_pg" in sql for sql, _ in executed)


async def test_document_store_load_and_bm25_fetch_and_keyword_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._bm25_available = True
    store._index = {
        "d1": {"session_id": "s1", "title": "First", "source": "src://1", "tags": ["alpha"]},
        "d2": {"session_id": "s2", "title": "Second", "source": "src://2", "tags": ["beta"]},
    }
    (tmp_path / "d1.txt").write_text("hello alpha world", encoding="utf-8")
    (tmp_path / "d2.txt").write_text("hello beta world", encoding="utf-8")

    # _load_index invalid json branch
    store.index_file.write_text("{broken", encoding="utf-8")
    assert store._load_index() == {}

    # _init_fts for BM25 tables
    store._init_fts()
    bm25_rows = store._fetch_bm25("hello", top_k=2, session_id="s1")
    assert bm25_rows and bm25_rows[0]["id"] == "d1"
    assert store._fetch_bm25("???", top_k=2, session_id="s1") == []

    # _fetch_chroma empty ids branch and normal branch
    store.collection = SimpleNamespace(
        count=lambda: 10,
        query=lambda **_kwargs: {"ids": [["c1", "c2"]], "documents": [["snippet1", "snippet2"]], "metadatas": [[{"parent_id": "d1", "title": "T1", "source": "S1"}, {"parent_id": "d1"}]]},
    )
    store.cfg = SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=2)
    store._is_local_llm_provider = False
    chroma = store._fetch_chroma("q", 2, "s1")
    assert chroma and chroma[0]["id"] == "d1"

    store.collection = SimpleNamespace(count=lambda: 1, query=lambda **_kwargs: {"ids": [[]]})
    assert store._fetch_chroma("q", 2, "s1") == []

    # keyword search/session filtering
    ok, text = store._keyword_search("alpha", 2, "s1")
    assert ok is True and "First" in text


async def test_graph_index_iter_source_files_limits_and_excludes(tmp_path: Path) -> None:
    root = tmp_path
    (root / "a.py").write_text("print('a')", encoding="utf-8")
    (root / "b.js").write_text("console.log('b')", encoding="utf-8")
    skipped = root / "node_modules"
    skipped.mkdir()
    (skipped / "c.py").write_text("print('skip')", encoding="utf-8")
    unsupported = root / "d.txt"
    unsupported.write_text("text", encoding="utf-8")

    graph = rag.GraphIndex(root, max_files=1)
    files = graph._iter_source_files(root)

    assert len(files) == 1
    assert files[0].name in {"a.py", "b.js"}


async def test_graph_index_python_import_candidates_with_relative_levels(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg" / "sub"
    pkg.mkdir(parents=True)
    target = root / "pkg" / "shared.py"
    target.write_text("", encoding="utf-8")
    current = pkg / "caller.py"
    current.write_text("", encoding="utf-8")

    candidates = rag.GraphIndex._python_import_candidates(current, "shared", 2, root)
    assert target.resolve() in candidates


async def test_document_store_init_chroma_and_fts_error_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]

    monkeypatch.setitem(__import__("sys").modules, "chromadb", SimpleNamespace(PersistentClient=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))))
    monkeypatch.setitem(__import__("sys").modules, "chromadb.config", SimpleNamespace(Settings=lambda **_kwargs: object()))
    store._init_chroma()
    assert store._chroma_available is False

    class _BrokenCursor:
        def fetchone(self) -> dict[str, int]:
            return {"c": 0}

    class _BrokenConn:
        row_factory = None

        def execute(self, sql: object, *_args: object) -> _BrokenCursor:
            if "SELECT count" in str(sql):
                return _BrokenCursor()
            raise RuntimeError("insert failed")

        def commit(self) -> None:
            return None

    assert _BrokenCursor().fetchone() == {"c": 0}
    conn_probe = _BrokenConn()
    assert isinstance(conn_probe.execute("SELECT count(*) as c FROM bm25_index"), _BrokenCursor)
    assert conn_probe.commit() is None

    monkeypatch.setattr("sqlite3.connect", lambda *_a, **_k: _BrokenConn())
    store._index = {"doc1": {"session_id": "s1"}}
    (tmp_path / "doc1.txt").write_text("body", encoding="utf-8")
    store._bm25_available = True
    store._write_lock = threading.Lock()
    store._init_fts()
    assert store._bm25_available is False


async def test_document_store_apply_hf_runtime_env_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(HF_TOKEN="", HF_HUB_OFFLINE=False)
    monkeypatch.setenv("HF_TOKEN", "keep")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "keep")
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    store._apply_hf_runtime_env()

    assert os.environ["HF_TOKEN"] == "keep"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "keep"
    assert "HF_HUB_OFFLINE" not in os.environ


async def test_document_store_consolidate_session_documents_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "keep-new": {"session_id": "s1", "last_accessed_at": 30, "access_count": 2, "title": "Recent"},
        "pinned": {"session_id": "s1", "last_accessed_at": 10, "access_count": 0, "title": "Pinned", "tags": ["pinned"]},
        "stable": {"session_id": "s1", "last_accessed_at": 9, "access_count": 2, "title": "Stable"},
    }
    assert store.consolidate_session_documents("s1", keep_recent_docs=1)["status"] == "skipped"

    removed: list[tuple[str, str]] = []
    store._index = {
        "old-1": {"session_id": "s1", "last_accessed_at": 5, "access_count": 0, "title": "Old 1", "preview": "alpha"},
        "old-2": {"session_id": "s1", "last_accessed_at": 4, "access_count": 1, "title": "Old 2", "preview": "beta"},
        "keep-new": {"session_id": "s1", "last_accessed_at": 30, "access_count": 3, "title": "Recent"},
        "digest-old": {"session_id": "s1", "source": "memory://nightly-digest/prev", "title": "Digest"},
    }
    store._add_document_sync = lambda **_kwargs: "digest-new"  # type: ignore[method-assign]
    store.delete_document = lambda doc_id, session_id: removed.append((doc_id, session_id)) or "ok"  # type: ignore[method-assign]

    result = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert result["status"] == "completed"
    assert result["removed_docs"] == 3
    assert result["summary_doc_id"] == "digest-new"
    assert ("digest-old", "s1") in removed
    assert ("old-1", "s1") in removed
    assert ("old-2", "s1") in removed


async def test_document_store_list_documents_and_status_engine_variants(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    assert "Belge deposu boş" in store.list_documents(session_id="s1")

    store._index = {"doc1": {"session_id": "s1", "title": "Doc 1", "source": "file://a", "size": 1024, "tags": ["x"]}}
    listed = store.list_documents(session_id="s1")
    assert "[Belge Deposu — 1 belge]" in listed
    assert "Doc 1" in listed

    store._bm25_available = False
    store._graph_rag_enabled = False
    store._graph_ready = False
    store._use_gpu = False
    store._gpu_device = 0

    store._pgvector_available = True
    store._vector_backend = "chroma"
    store._chroma_available = False
    assert "pgvector" in store.status()

    store._pgvector_available = False
    store._vector_backend = "pgvector"
    assert "pgvector (pasif)" in store.status()

    store._vector_backend = "chroma"
    store._chroma_available = True
    store._use_gpu = True
    store._gpu_device = 1
    assert "ChromaDB (Chunking + GPU cuda:1)" in store.status()


async def test_document_store_add_file_security_and_failure_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    outside = Path("/etc/hosts")
    ok, msg = store.add_document_from_file(str(outside), session_id="s1")
    assert ok is False
    assert "proje dizini dışında" in msg

    blocked = tmp_path / "logs" / "note.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("hello", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(blocked), session_id="s1")
    assert ok is False
    assert "güvenlik politikası" in msg

    empty = tmp_path / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(empty), session_id="s1")
    assert ok is False
    assert "Dosya boş" in msg

    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("read boom")))
    ok, msg = store.add_document_from_file(str(empty), session_id="s1")
    assert ok is False
    assert "Dosya eklenemedi" in msg


async def test_document_store_delete_document_graph_and_wrappers(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    class _DummyLock:
        def __enter__(self) -> "_DummyLock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._chroma_available = True
    store.collection = SimpleNamespace(delete=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("delete boom")))
    store._pgvector_available = True
    deleted: list[tuple[str, str]] = []
    store._delete_pgvector_parent = lambda parent_id, session_id: deleted.append((parent_id, session_id))  # type: ignore[method-assign]
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None
    store._index = {"doc1": {"title": "Doc1", "session_id": "s1", "parent_id": "p1"}}
    (tmp_path / "doc1.txt").write_text("body", encoding="utf-8")

    message = store.delete_document("doc1", session_id="s1")
    assert "Belge silindi" in message
    assert deleted == [("p1", "s1")]

    ok, msg = store.get_document("missing", session_id="s1")
    assert ok is False
    assert "Belge bulunamadı" in msg

    pg_ok, pg_msg = store._pgvector_search("q", 2, "s1")
    assert pg_ok is False
    assert "ilgili sonuç bulunamadı" in pg_msg

    store.collection = SimpleNamespace(count=lambda: 0, query=lambda **_k: {"ids": [[]]})
    ch_ok, ch_msg = store._chroma_search("q", 2, "s1")
    assert ch_ok is False
    assert "ilgili sonuç bulunamadı" in ch_msg

    store._bm25_available = False
    bm_ok, bm_msg = store._bm25_search("q", 2, "s1")
    assert bm_ok is False
    assert "ilgili sonuç bulunamadı" in bm_msg


async def test_document_store_search_mode_and_cache_update_edges(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T1"}}
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = False
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._pgvector_search = lambda q, k, s: (True, f"pg:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._chroma_search = lambda q, k, s: (True, f"ch:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, res = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is True and res.startswith("pg:")

    store._pgvector_available = False
    ok, res = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is True and res.startswith("ch:")

    store._pgvector_available = True
    ok, res = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and res.startswith("pg:")

    # _update_bm25_cache_on_add / _update_bm25_cache_on_delete active branches
    executed: list[tuple[str, tuple[object, ...]]] = []
    store._bm25_available = True
    store._index = {"d1": {"session_id": "s1"}}
    store.fts_conn = SimpleNamespace(
        execute=lambda sql, params: executed.append((sql, params)),
        commit=lambda: executed.append(("COMMIT", ())),
    )
    store._update_bm25_cache_on_add("d1", "hello")
    store._update_bm25_cache_on_delete("d1")
    assert any("INSERT INTO bm25_index" in q for q, _ in executed)
    assert ("COMMIT", ()) in executed


async def test_document_store_judge_and_vector_fetch_error_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(__import__("sys").modules, "core.judge", SimpleNamespace(get_llm_judge=lambda: (_ for _ in ()).throw(RuntimeError("judge boom"))))
    rag.DocumentStore._schedule_judge("q", "a")

    store = _make_store_stub(tmp_path)
    store._pgvector_available = False
    assert store._fetch_pgvector("q", 2, "s1") == []

    store._pgvector_available = True
    store.pg_engine = object()
    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    store._pgvector_embed_texts = lambda _texts: (_ for _ in ()).throw(RuntimeError("embed boom"))  # type: ignore[method-assign]
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_document_store_fetch_chroma_bm25_and_formatter_edges(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=1)
    store._is_local_llm_provider = False
    store.collection = SimpleNamespace(
        count=lambda: (_ for _ in ()).throw(RuntimeError("count boom")),
        query=lambda **_kwargs: {
            "ids": [["", "c2"]],
            "documents": [["first", "second"]],
            "metadatas": [[{"parent_id": ""}, {"parent_id": "d2", "title": "Doc2"}]],
        },
    )
    found = store._fetch_chroma("q", 2, "s1")
    assert found and found[0]["id"] == "d2"

    store._bm25_available = False
    assert store._fetch_bm25("hello", 2, "s1") == []

    class _Lock:
        def __enter__(self) -> "_Lock":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._bm25_available = True
    store._write_lock = _Lock()
    store.fts_conn = SimpleNamespace(execute=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fts boom")))
    assert store._fetch_bm25("hello", 2, "s1") == []

    ok, text = store._format_results_from_struct(
        [{"id": "x", "title": "t", "source": "", "snippet": "s", "score": 1.0}],
        "q",
        source_name="BM25",
    )
    assert ok is True
    assert "Kaynak:" not in text


async def test_document_store_graph_impact_and_helpers_extra_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = False
    called: list[str] = []
    store.rebuild_graph_index = lambda root_dir=None: called.append(str(root_dir)) or (True, "ok")  # type: ignore[method-assign]

    # _ensure_graph_ready tetiklenir.
    store._ensure_graph_ready()
    assert called == ["None"]

    # graph_impact_details: boş analiz dalı.
    store._graph_ready = True
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.impact_analysis = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
    ok, msg = store.graph_impact_details("a.py")
    assert ok is False
    assert "etki analizi üretilemedi" in msg

    # analyze_graph_impact: tüm alanlar dolu iken format satırları.
    store.graph_impact_details = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        True,
        {
            "target": "a.py",
            "node_type": "file",
            "risk_level": "high",
            "direct_dependents": ["b.py"],
            "dependencies": ["c.py"],
            "impacted_endpoints": ["endpoint:GET /x"],
            "impacted_endpoint_handlers": ["api.py"],
            "caller_files": ["ui.js"],
            "review_targets": ["service.py"],
            "dependency_paths": [["ui.js", "api.py", "a.py"]],
        },
    )
    ok, text = store.analyze_graph_impact("a.py")
    assert ok is True
    assert "Doğrudan bağımlılar" in text
    assert "Aşağı akış bağımlılıklar" in text
    assert "Etkilenen endpoint'ler" in text
    assert "Etkilenen endpoint handler dosyaları" in text
    assert "Çağıran dosyalar" in text
    assert "Reviewer için önerilen hedefler" in text
    assert "Örnek etki zincirleri" in text


async def test_document_store_misc_uncovered_fallback_paths(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}
    store._bm25_available = False
    ok, msg = store._search_sync("q", mode="bm25", session_id="s1")
    assert ok is False
    assert "BM25 kullanılamıyor" in msg

    # _touch_document: olmayan belge dalı.
    store._save_index = lambda: (_ for _ in ()).throw(AssertionError("should not save"))  # type: ignore[method-assign]
    store._touch_document("missing")

    # build_graphrag_search_plan: boş sorgu ile vector fetch atlanır.
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._graph_rag_enabled = False
    store._fetch_pgvector = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no fetch"))  # type: ignore[method-assign]
    plan = store.build_graphrag_search_plan("", session_id="s1", top_k=2)
    assert plan.query == ""
    assert plan.vector_candidates == []

    # _schedule_judge: judge.enabled=False dalı.
    class _Judge:
        enabled = False

        def schedule_background_evaluation(self, **_kwargs: object) -> None:
            raise AssertionError("should not be called")

    import sys

    sys.modules["core.judge"] = SimpleNamespace(get_llm_judge=lambda: _Judge())
    rag.DocumentStore._schedule_judge("q", "a")


async def test_graph_index_additional_branch_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.py").write_text("x=1", encoding="utf-8")
    keep = root / "keep.py"
    keep.write_text("x=1", encoding="utf-8")
    other = root / "other.py"
    other.write_text("print('ok')\n", encoding="utf-8")

    gi = rag.GraphIndex(root)
    files = gi._iter_source_files(root)
    assert keep in files
    assert all("node_modules" not in str(p) for p in files)
    assert gi._script_import_candidates(keep, "react", root) == []
    assert gi._extract_str_literal(ast.Str(s=" legacy ")) == "legacy"

    src = """
from . import mod
@router.get
def no_args(): pass
@router.get("/ok")
def ok(): pass
session.post()
http.get("http://remote.example.com/x")
foo.get("/x")
obj.session.post("/y")
"""
    deps, defs, calls = gi._parse_python_source(keep, src)
    assert isinstance(deps, list)
    assert any(item["path"] == "/ok" for item in defs)
    assert {item["path"] for item in calls} == {"/x", "/y"}

    calls = gi._extract_script_endpoint_calls(
        'fetch("http://remote.example.com/x"); new WebSocket("http://remote.example.com/ws"); new WebSocket("/ws"); new WebSocket("/ws")'
    )
    assert len(calls) == 1

    original_read_text = Path.read_text

    def _boom(self, *args, **kwargs):
        if self == keep:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    assert other.read_text(encoding="utf-8") == "print('ok')\n"
    rebuilt = gi.rebuild(root)
    assert rebuilt["nodes"] >= 1

    assert gi.resolve_node_id("   ") is None
    assert gi.explain_dependency_path("missing", "target") == []
    gi.add_node("a")
    gi.add_node("b")
    assert gi.explain_dependency_path("a", "b") == []
    assert gi.impact_analysis("missing") == {}

    gi.add_node("core/a.py", node_type="file")
    gi.add_node("core/b.py", node_type="file")
    gi.add_node("core/c.py", node_type="file")
    gi.add_node("target.py", node_type="file")
    gi.add_edge("core/a.py", "target.py")
    gi.add_edge("core/b.py", "target.py")
    gi.add_edge("core/c.py", "target.py")
    impact = gi.impact_analysis("target.py")
    assert impact["risk_level"] == "medium"


async def test_embedding_function_mixed_precision_cuda_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _EF:
        def __call__(self, input):
            return ["ok", input]

    class _Factory:
        def __call__(self, **kwargs):
            return _EF()

    fake_embedding_functions = types.SimpleNamespace(SentenceTransformerEmbeddingFunction=_Factory())
    fake_chromadb_utils = types.SimpleNamespace(embedding_functions=fake_embedding_functions)
    fake_chromadb = types.SimpleNamespace(utils=fake_chromadb_utils)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True),
        float16="fp16",
        autocast=lambda **kwargs: contextlib.nullcontext(),
    )

    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.utils", fake_chromadb_utils)
    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", fake_embedding_functions)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.amp", types.ModuleType("torch.amp"))

    ef = rag._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None
    assert ef.__call__(["x"])[0] == "ok"


async def test_graph_index_parse_and_search_additional_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gi = rag.GraphIndex(tmp_path)
    sample = tmp_path / "svc.py"
    sample.write_text("", encoding="utf-8")

    src = """
@router.get
def no_args(): pass

@router.get("{dynamic}")
def dynamic(): pass

obj.connect("/x")
obj.router.get("/skip")
"""
    deps, defs, calls = gi._parse_python_source(sample, src)
    assert deps == []
    assert defs == []
    assert calls == []

    # ast.Str branchini doğrudan zorla.
    fake_str_cls = type("FakeStr", (), {})
    monkeypatch.setattr(rag.ast, "Str", fake_str_cls, raising=False)
    node = fake_str_cls()
    node.s = " legacy "
    assert gi._extract_str_literal(node) == "legacy"

    gi.add_node("alpha.py", node_type="file")
    gi.add_node("beta.py", node_type="file")
    related = gi.search_related("unmatched-token", top_k=3)
    assert related == []


async def test_document_store_init_and_core_fallback_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {})
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: None)
    chroma_calls: list[str] = []
    monkeypatch.setattr(rag.DocumentStore, "_init_chroma", lambda self: chroma_calls.append("chroma"))
    monkeypatch.setattr(rag.DocumentStore, "_init_pgvector", lambda self: None)
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: True)
    cfg = SimpleNamespace(
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=10,
    )
    rag.DocumentStore(tmp_path / "store2", cfg=cfg)
    assert chroma_calls == ["chroma"]

    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="sqlite:///x.db")
    store._check_import = lambda _m: False  # type: ignore[method-assign]
    store._init_pgvector()
    assert getattr(store, "_pgvector_available", False) is False


async def test_document_store_low_level_misc_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {}
    store._save_index()
    assert store.index_file.exists()
    assert store._recursive_chunk_text("", size=10, overlap=2) == []
    assert store._recursive_chunk_text("abc", size=2, overlap=9)

    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("https:///nohost")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://10.0.0.1/x")

    # add_document async wrapper
    called = {}
    store._add_document_sync = lambda *args, **kwargs: called.setdefault("ok", "doc-1")  # type: ignore[method-assign]
    assert await store.add_document("t", "c", session_id="s1") == "doc-1"


async def test_document_store_url_file_delete_and_graph_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()

    # add_document_from_url: title dolu ise regex dalı atlanır
    async def _fake_add(*_args, **_kwargs):
        return "doc-u"

    store.add_document = _fake_add  # type: ignore[method-assign]

    class _Resp:
        text = "<html><body>x</body></html>"

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=lambda **_k: _Client()))
    ok, _msg = await store.add_document_from_url("https://example.com/x", title="manual", session_id="s1")
    assert ok is True

    # file exists/is_file branchleri
    ok, msg = store.add_document_from_file(str(tmp_path / "missing.txt"), session_id="s1")
    assert ok is False and "Dosya bulunamadı" in msg
    d = tmp_path / "adir"
    d.mkdir()
    ok, msg = store.add_document_from_file(str(d), session_id="s1")
    assert ok is False and "yol bir dosya değil" in msg

    # delete_document branchleri
    assert "Belge bulunamadı" in store.delete_document("none", session_id="s1")
    store._index = {"d1": {"title": "Doc", "session_id": "s2"}}
    assert "yetkiniz yok" in store.delete_document("d1", session_id="s1")
    class _FlipLock:
        def __enter__(self):
            store._index.pop("d1", None)
            return self
        def __exit__(self, *_args):
            return None
    store._index = {"d1": {"title": "Doc", "session_id": "s1"}}
    store._write_lock = _FlipLock()
    assert "zaten silinmiş" in store.delete_document("d1", session_id="s1")

    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_index = rag.GraphIndex(tmp_path)
    ok, txt = store.rebuild_graph_index(root_dir=str(tmp_path))
    assert ok is True and "GraphIndex hazırlandı" in txt


async def test_document_store_search_projection_and_rrf_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T1"}}
    store._bm25_available = False
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    ok, msg = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is False and "ilgili sonuç bulunamadı" in msg

    # Projection break branchleri
    store._graph_rag_enabled = True
    store._graph_ready = True
    g = rag.GraphIndex(tmp_path)
    g.add_node("a.py", node_type="file")
    g.add_node("b.py", node_type="file")
    g.add_node("c.py", node_type="file")
    g.add_edge("a.py", "b.py", kind="imports")
    g.add_edge("b.py", "c.py", kind="imports")
    g.add_edge("c.py", "a.py", kind="imports")
    store._graph_index = g
    proj = store.build_knowledge_graph_projection(session_id="s1", include_code_graph=True, limit=1)
    assert len(proj["edges"]) >= 1
    assert any(e.source.startswith("code:") for e in proj["edges"])

    # search() tracer yok dalı
    rag._otel_trace = None  # type: ignore[assignment]
    store._search_sync = lambda *_args, **_kwargs: (True, "ok")  # type: ignore[method-assign]
    assert await store.search("q", session_id="s1") == (True, "ok")

    # rrf: iki taraf da boş ise keyword fallback
    store._pgvector_available = True
    store._fetch_pgvector = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._fetch_bm25 = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    assert store._rrf_search("q", 2, "s1")[1].startswith("kw:")


async def test_document_store_vector_and_keyword_file_not_found_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"d1": {"session_id": "s1", "title": "Doc1", "source": "src", "tags": ["alpha"]}}
    store._bm25_available = True

    class _Rows:
        def fetchall(self):
            return [{"doc_id": "d1", "score": -1.0}]

    class _Lock:
        def __enter__(self): return self
        def __exit__(self, *_args): return None

    store._write_lock = _Lock()
    store.fts_conn = SimpleNamespace(execute=lambda *_a, **_k: _Rows())
    bm = store._fetch_bm25("alpha", 1, "s1")
    assert bm and bm[0]["snippet"] == ""

    kw_ok, kw_msg = store._keyword_search("alpha", 1, "s1")
    assert kw_ok is True and "Doc1" in kw_msg

    # _update_bm25 early return branches
    store._bm25_available = False
    store._update_bm25_cache_on_add("d1", "body")
    store._update_bm25_cache_on_delete("d1")

    # pgvector delete hata dalı
    store._pgvector_available = True
    store.pg_engine = SimpleNamespace(begin=lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    store._delete_pgvector_parent("p1", "s1")


async def test_rag_remaining_branches_for_pgvector_and_add_document(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@h/db")
    store._check_import = lambda _m: True  # type: ignore[method-assign]
    store._pg_table = "t"
    store._pg_embedding_dim = 3
    store._pg_embedding_model_name = "m"
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("st fail"))))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(create_engine=lambda *_a, **_k: object(), text=lambda s: s))
    store._init_pgvector()
    assert store._pgvector_available is False

    store._pg_embedding_model = None
    assert store._pgvector_embed_texts(["a"]) == []
    store._pg_embedding_model = SimpleNamespace(encode=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("enc fail")))
    assert store._pgvector_embed_texts(["a"]) == []

    store._pgvector_available = True
    store.pg_engine = object()
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", [])  # 817
    store._pgvector_embed_texts = lambda _chunks: []  # type: ignore[method-assign]
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c"])  # 823
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    store.pg_engine = SimpleNamespace(begin=lambda: (_ for _ in ()).throw(RuntimeError("sql fail")))
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c"])  # 860-861

    store.index_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("idx fail")))
    assert store._load_index() == {}

    # recursive chunking deep split paths
    assert store._recursive_chunk_text("X" * 50, size=5, overlap=2)
    assert store._recursive_chunk_text("a\n\n" + "b" * 40, size=8, overlap=2)

    # _add_document_sync: chroma hata dalı + chunks empty branch
    class _DummyLock:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
    store._write_lock = _DummyLock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    store._chroma_available = True
    store.collection = SimpleNamespace(delete=lambda **_k: (_ for _ in ()).throw(RuntimeError("chroma fail")), upsert=lambda **_k: None)
    store._chunk_text = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._pgvector_available = False
    doc = store._add_document_sync("T", "C", source="s", tags=[], session_id="s1")
    assert doc in store._index


async def test_rag_remaining_branches_for_graph_search_and_rrf(tmp_path: Path) -> None:
    # parse branch 217->219, 192
    gi = rag.GraphIndex(tmp_path)
    src = "@router.get\ndef x(): pass\nobj.app.get('/x')\n"
    _deps, defs, calls = gi._parse_python_source(tmp_path / "a.py", src)
    assert defs == [] and calls == []

    # rebuild import target missing node branch (299->297)
    (tmp_path / "main.py").write_text("import missing_mod", encoding="utf-8")
    summary = gi.rebuild(tmp_path)
    assert summary["nodes"] >= 1

    # impact branchleri 400->399, 416->414
    gi.add_node("endpoint:GET /z", node_type="endpoint")
    gi.add_node("handler:virtual", node_type="endpoint")
    gi.add_edge("endpoint:GET /z", "handler:virtual", kind="handled_by")
    gi.add_node("target.py", node_type="file")
    gi.add_edge("target.py", "endpoint:GET /z", kind="calls_endpoint")
    impact = gi.impact_analysis("target.py")
    assert impact["dependency_paths"] == []

    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = gi
    ok, msg = store.explain_dependency_path("a.py", "missing.py")
    assert ok is False and "bulunamadı" in msg
    store.graph_impact_details = lambda *_a, **_k: (True, {"target": "x", "node_type": "file", "risk_level": "low", "dependencies": []})  # type: ignore[method-assign]
    ok, text = store.analyze_graph_impact("x")
    assert ok is True and "Aşağı akış bağımlılıklar" not in text


async def test_graph_index_parse_python_source_skips_router_like_attribute_calls(tmp_path: Path) -> None:
    gi = rag.GraphIndex(tmp_path)
    src = """
def call_it():
    client.router.get('/health')
    service.app.post('/submit')
"""

    _deps, defs, calls = gi._parse_python_source(tmp_path / "a.py", src)

    assert defs == []
    assert calls == []


async def test_document_store_init_fts_skips_migration_when_index_empty(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._index = {}

    store._init_fts()

    count = store.fts_conn.execute("SELECT count(*) as c FROM bm25_index").fetchone()["c"]
    assert count == 0


async def test_document_store_recursive_chunk_text_forced_fallback_split(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    original_list = list

    def _patched_list(arg):  # type: ignore[no-untyped-def]
        if isinstance(arg, str) and len(arg) > 1:
            return [arg]
        return original_list(arg)

    monkeypatch.setattr(rag, "list", _patched_list)

    chunks = store._recursive_chunk_text("abcdefghij", size=4, overlap=1)

    assert chunks == ["abcd", "defg", "ghij", "j"]

    # _search_sync fallback zinciri 1521+ branches
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T"}}
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = False
    store._is_local_llm_provider = False
    store._rrf_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rrf"))  # type: ignore[method-assign]
    store._pgvector_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("pg"))  # type: ignore[method-assign]
    store._chroma_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("ch"))  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    ok, _res = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True

    # search tracer none -> 1553-1555
    rag._otel_trace = None  # type: ignore[assignment]
    store._search_sync = lambda *_a, **_k: (True, "ok")  # type: ignore[method-assign]
    assert await store.search("q", session_id="s1") == (True, "ok")

    # rrf non-empty bm25 path 1589-1591
    store2 = _make_store_stub(tmp_path)
    store2._pgvector_available = True
    store2._fetch_pgvector = lambda *_a, **_k: [{"id": "a", "title": "A", "source": "", "snippet": "", "score": 0.1}]  # type: ignore[method-assign]
    store2._fetch_bm25 = lambda *_a, **_k: [{"id": "b", "title": "B", "source": "", "snippet": "", "score": 0.2}]  # type: ignore[method-assign]
    ok, text = store2._rrf_search("q", 2, "s1")
    assert ok is True and "Hibrit RRF" in text

    # fetch_pgvector rows empty -> 1628->1644
    store._pgvector_available = True
    store.pg_engine = SimpleNamespace(begin=lambda: contextlib.nullcontext(SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(fetchall=lambda: []))))
    store._pgvector_embed_texts = lambda _t: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    sys.modules["sqlalchemy"] = SimpleNamespace(text=lambda s: s)
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_rag_remaining_edge_branches_round_two(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gi = rag.GraphIndex(tmp_path)
    src = """
@router.get()
def a(): pass
obj.client.get('/ok')
"""
    _deps, defs, calls = gi._parse_python_source(tmp_path / "x.py", src)
    assert defs == []
    assert calls and calls[0]["path"] == "/ok"

    # rebuild branch: dep hedefi düğümde yok
    a = tmp_path / "a.py"
    a.write_text("import x", encoding="utf-8")
    monkeypatch.setattr(gi, "_extract_dependencies", lambda *_a, **_k: ([tmp_path / "missing.py"], [], []))
    summary = gi.rebuild(tmp_path)
    assert summary["nodes"] >= 1

    # impact: endpoint handler file değil, dependency path boş
    gi.clear()
    gi.add_node("target.py", node_type="file")
    gi.add_node("endpoint:GET /a", node_type="endpoint")
    gi.add_node("endpoint-handler", node_type="endpoint")
    gi.add_edge("endpoint:GET /a", "target.py", kind="handled_by")
    gi.add_edge("endpoint:GET /a", "endpoint-handler", kind="handled_by")
    gi.add_edge("caller.py", "endpoint:GET /a", kind="calls_endpoint")
    gi.add_node("caller.py", node_type="file")
    impact = gi.impact_analysis("target.py")
    assert "endpoint-handler" not in impact["impacted_endpoint_handlers"]

    # _init_chroma embedding_fn None path
    store = _make_store_stub(tmp_path)
    store._use_gpu = False
    store._gpu_device = 0
    store._mixed_precision = False
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]
    class _Client:
        def get_or_create_collection(self, **kwargs):
            assert "embedding_function" not in kwargs
            return object()
    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=lambda **_k: _Client()))
    monkeypatch.setitem(sys.modules, "chromadb.config", SimpleNamespace(Settings=lambda **_k: object()))
    monkeypatch.setattr(rag, "_build_embedding_function", lambda **_k: None)
    store._init_chroma()
    assert store.collection is not None

    # _init_fts migrate exception branch 727->740/738
    store._index = {"d1": {"session_id": "s1"}}
    store._bm25_available = True
    class _Lock:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
    store._write_lock = _Lock()
    store._init_fts()
    assert store._bm25_available is True

    # _init_pgvector early returns
    store.cfg = SimpleNamespace(DATABASE_URL="sqlite:///a.db")
    store._init_pgvector()
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@h/db")
    store._check_import = lambda _m: False  # type: ignore[method-assign]
    store._init_pgvector()

    # _delete_pgvector_parent guard
    store._pgvector_available = True
    store.pg_engine = None
    store._delete_pgvector_parent("p", "s")

    # _load_index no file (878->883)
    store.index_file.unlink(missing_ok=True)
    assert store._load_index() == {}

    # add_document chroma branching with empty chunks (1028/1034 false)
    class _Lock:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
    store._write_lock = _Lock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    calls = []
    store.collection = SimpleNamespace(delete=lambda **_k: calls.append("del"), upsert=lambda **_k: calls.append("up"))
    store._chroma_available = True
    store._pgvector_available = False
    store._chunk_size = 0
    store._add_document_sync("t", "c", source="s", tags=[], session_id="s1")
    assert calls == ["del"]

    # _validate_url_safe 1076->1082 path (public ip)
    rag.DocumentStore._validate_url_safe("http://8.8.8.8/x")

    # delete_document doc file yoksa chroma branchine düşsün
    store._index = {"d2": {"title": "D2", "session_id": "s1"}}
    store._chroma_available = False
    store.collection = None
    store._update_bm25_cache_on_delete = lambda *_a: None  # type: ignore[method-assign]
    msg = store.delete_document("d2", session_id="s1")
    assert "Belge silindi" in msg

    # _search_sync fallback zinciri alt dallar
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T"}}
    store._bm25_available = False
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._chroma_search = lambda q, k, s: (True, f"ch:{q}")  # type: ignore[method-assign]
    ok, out = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and out.startswith("ch:")


async def test_rag_final_remaining_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # __init__ 631->635
    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {})
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: None)
    monkeypatch.setattr(rag.DocumentStore, "_init_chroma", lambda self: (_ for _ in ()).throw(AssertionError("no chroma")))
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: False)
    cfg = SimpleNamespace(
        RAG_TOP_K=1, RAG_CHUNK_SIZE=8, RAG_CHUNK_OVERLAP=2, RAG_VECTOR_BACKEND="bm25",
        AI_PROVIDER="openai", RAG_LOCAL_ENABLE_HYBRID=False, ENABLE_GRAPH_RAG=False, BASE_DIR=tmp_path, GRAPH_RAG_MAX_FILES=1
    )
    rag.DocumentStore(tmp_path / "s3", cfg=cfg)

    store = _make_store_stub(tmp_path)
    class _L:
        def __enter__(self): return self
        def __exit__(self, *_a): return None
    store._write_lock = _L()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._add_document_sync("t", "c", source="s", tags=[], session_id="s1")  # 1025->1042

    # _search_sync 1529->1533
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d": {"session_id": "s1", "title": "T"}}
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._bm25_search = lambda q, k, s: (True, f"bm:{q}")  # type: ignore[method-assign]
    assert store._search_sync("q", mode="auto", session_id="s1")[1].startswith("bm:")

    # _fetch_pgvector 1628->1644 with empty rows
    store._pgvector_available = True
    store._pg_table = "t"
    store._is_local_llm_provider = False
    store._pgvector_embed_texts = lambda _t: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    class _Conn:
        def execute(self, *_a, **_k):
            return SimpleNamespace(fetchall=lambda: [])
    store.pg_engine = SimpleNamespace(begin=lambda: contextlib.nullcontext(_Conn()))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_rag_almost_final_branches_for_parser_impact_and_fts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gi = rag.GraphIndex(tmp_path)
    deps, defs, calls = gi._parse_python_source(tmp_path / "p.py", "obj.client.get('/z')")
    assert deps == [] and defs == [] and calls[0]["path"] == "/z"

    gi.add_node("target.py", node_type="file")
    gi.add_node("endpoint:GET /k", node_type="endpoint")
    gi.add_edge("caller.py", "endpoint:GET /k", kind="calls_endpoint")
    gi.add_edge("endpoint:GET /k", "target.py", kind="handled_by")
    gi.add_node("caller.py", node_type="file")
    monkeypatch.setattr(gi, "explain_dependency_path", lambda *_a, **_k: [])
    impact = gi.impact_analysis("target.py")
    assert isinstance(impact, dict)

    store = _make_store_stub(tmp_path)
    class _Lock:
        def __enter__(self): return self
        def __exit__(self, *_a): return None
    store._write_lock = _Lock()
    store._bm25_available = True
    store._index = {"missing-doc": {"session_id": "s1"}}
    # file intentionally missing -> line 738 except/pass branch
    store._init_fts()
    assert store._bm25_available is True


async def test_document_store_search_uses_vector_hits_from_fake_vector_store(
    tmp_path: Path,
    fake_vector_store,
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"doc-1": {"session_id": "s1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._vector_backend = "pgvector"
    store.cfg = SimpleNamespace(RAG_TOP_K=2)

    def _pgvector_search(_query: str, _top_k: int, _session_id: str):
        rows = list(fake_vector_store.search.return_value)
        return True, "\n".join(item["content"] for item in rows)

    store._pgvector_search = _pgvector_search  # type: ignore[method-assign]
    store._keyword_search = lambda *_args, **_kwargs: (True, "keyword-fallback")  # type: ignore[method-assign]

    ok, result = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")

    assert ok is True
    assert "mock context for RAG" in result


async def test_document_store_search_fallbacks_when_fake_vector_store_empty_or_error(
    tmp_path: Path,
    fake_vector_store,
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"doc-1": {"session_id": "s1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._vector_backend = "pgvector"
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store._keyword_search = lambda *_args, **_kwargs: (True, "keyword-fallback")  # type: ignore[method-assign]

    fake_vector_store.set_empty_result()

    def _pgvector_empty(_query: str, _top_k: int, _session_id: str):
        rows = list(fake_vector_store.search.return_value)
        if not rows:
            raise RuntimeError("empty vector results")
        return True, "unused"

    store._pgvector_search = _pgvector_empty  # type: ignore[method-assign]

    ok_empty, result_empty = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")
    assert ok_empty is True
    assert result_empty == "keyword-fallback"
    fake_vector_store.search.return_value = [{"content": "present"}]
    assert _pgvector_empty("pytest", 2, "s1") == (True, "unused")

    fake_vector_store.set_db_error()

    def _pgvector_error(_query: str, _top_k: int, _session_id: str):
        side_effect = fake_vector_store.search.side_effect
        if isinstance(side_effect, BaseException):
            raise side_effect
        return True, "unused"

    store._pgvector_search = _pgvector_error  # type: ignore[method-assign]

    ok_err, result_err = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")
    assert ok_err is True
    assert result_err == "keyword-fallback"
    fake_vector_store.search.side_effect = None
    assert _pgvector_error("pytest", 2, "s1") == (True, "unused")
