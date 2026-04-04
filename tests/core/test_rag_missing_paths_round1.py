from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core import rag as rag_module
from core.rag import DocumentStore, GraphIndex, GraphRAGSearchPlan, embed_texts_for_semantic_cache


class _DummyGraph:
    def __init__(self) -> None:
        self.nodes = {"api.py": {"node_type": "file"}, "endpoint:GET /health": {"node_type": "endpoint"}}
        self.edges = {"api.py": {"endpoint:GET /health"}}
        self.edge_kinds = {("api.py", "endpoint:GET /health"): {"calls_endpoint"}}

    def impact_analysis(self, target: str, top_k: int = 10):
        _ = top_k
        if target == "api.py":
            return {
                "target": "api.py",
                "node_type": "file",
                "risk_level": "medium",
                "direct_dependents": ["caller.py"],
                "dependencies": ["dep.py"],
                "impacted_endpoints": ["endpoint:GET /health"],
                "impacted_endpoint_handlers": ["handlers.py"],
                "caller_files": ["caller.py"],
                "review_targets": ["caller.py", "handlers.py"],
                "dependency_paths": [["caller.py", "api.py"]],
            }
        return {}

    def search_related(self, query: str, top_k: int = 5):
        _ = top_k
        if query == "exists":
            return [{"id": "api.py", "score": 4, "neighbors": ["dep.py"], "reverse_neighbors": ["caller.py"]}]
        return []

    def explain_dependency_path(self, source: str, target: str):
        if source == "a" and target == "b":
            return ["a", "b"]
        return []



def test_graphindex_rebuild_handles_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "svc.py"
    src.write_text("print('ok')", encoding="utf-8")

    graph = GraphIndex(tmp_path)

    original = Path.read_text

    def _boom(self: Path, *args, **kwargs):
        if self.name == "svc.py":
            raise OSError("denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    summary = graph.rebuild(tmp_path)

    assert summary["nodes"] == 1
    assert summary["edges"] == 0



def test_graphindex_resolve_impact_and_search_related() -> None:
    graph = GraphIndex(Path("."))
    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_node("endpoint:GET /ping", node_type="endpoint")
    graph.add_edge("a.py", "b.py", kind="imports")
    graph.add_edge("endpoint:GET /ping", "a.py", kind="handled_by")

    assert graph.resolve_node_id(" ") is None
    assert graph.resolve_node_id("A.PY") == "a.py"
    assert graph.explain_dependency_path("b.py", "a.py") == []

    impact = graph.impact_analysis("a.py", top_k=5)
    assert impact["risk_level"] == "high"
    assert "endpoint:GET /ping" in impact["impacted_endpoints"]

    related = graph.search_related("ping", top_k=3)
    assert related and related[0]["id"] == "endpoint:GET /ping"



def test_embed_texts_semantic_cache_empty_and_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    assert embed_texts_for_semantic_cache([]) == []

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("missing")

    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_Boom))
    assert embed_texts_for_semantic_cache(["hello"], cfg=SimpleNamespace(PGVECTOR_EMBEDDING_MODEL="x")) == []



def _make_store() -> DocumentStore:
    store = DocumentStore.__new__(DocumentStore)
    store._index = {
        "d1": {"title": "Doc 1", "source": "file://a", "session_id": "s1", "tags": ["x"], "size": 1024},
        "d2": {"title": "Doc 2", "source": "file://b", "session_id": "s2", "tags": [], "size": 512},
    }
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = _DummyGraph()
    store._ensure_graph_ready = lambda: None
    store._chroma_available = False
    store.collection = None
    store._bm25_available = False
    store._pgvector_available = False
    store._vector_backend = "bm25"
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = False
    return store



def test_graph_methods_cover_disabled_empty_and_success_paths() -> None:
    store = _make_store()

    ok, msg = store.search_graph("exists", top_k=2)
    assert ok is True and "[GraphRAG: exists]" in msg

    ok, msg = store.search_graph("impact:api.py")
    assert ok is True and "Risk seviyesi" in msg

    ok, msg = store.search_graph("a -> b")
    assert ok is True and "[GraphRAG Path]" in msg

    ok, msg = store.graph_impact_details("   ")
    assert ok is False and "hedef belirtilmedi" in msg

    store._graph_rag_enabled = False
    ok, msg = store.rebuild_graph_index()
    assert ok is False and "devre dışı" in msg



def test_projection_and_search_plan_use_pgvector_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _make_store()
    store._pgvector_available = True
    store._vector_backend = "pgvector"
    store._fetch_pgvector = lambda q, top_k, session_id: [
        {"doc_id": "d1", "id": "d1"},
        {"doc_id": "d2", "id": "d2"},
    ]

    projection = store.build_knowledge_graph_projection(session_id="s1", include_code_graph=True, limit=1)
    assert projection["vector_backend"] == "pgvector"
    assert any(node.id == "doc:d1" for node in projection["nodes"])
    assert all(node.id != "doc:d2" for node in projection["nodes"])

    plan = store.build_graphrag_search_plan("  query  ", session_id="s1", top_k=1)
    assert isinstance(plan, GraphRAGSearchPlan)
    assert plan.query == "query"
    assert plan.vector_candidates == ["d1"]
    assert any(topic.endswith("researcher.rag_search") for topic in plan.broker_topics)



def test_search_sync_modes_and_list_documents() -> None:
    store = _make_store()
    store._index = {}

    ok, msg = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is False and "boş" in msg

    store._index = {"d1": {"session_id": "s1", "title": "T", "source": "src", "tags": ["a"], "size": 2048}}
    store._pgvector_available = False
    store._chroma_available = False
    ok, msg = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is False and "Vektör arama" in msg

    store._bm25_available = False
    ok, msg = store._search_sync("q", mode="bm25", session_id="s1")
    assert ok is False and "BM25" in msg

    store._keyword_search = lambda q, top_k, sid: (True, f"kw:{q}:{top_k}:{sid}")
    ok, msg = store._search_sync("q", mode="keyword", session_id="s1")
    assert ok is True and msg.startswith("kw:")

    listed = store.list_documents(session_id="s1")
    assert "[Belge Deposu" in listed
    assert "Kaynak:" in listed



def test_clean_html_fallback_when_bleach_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag_module, "_BLEACH_AVAILABLE", False)
    cleaned = DocumentStore._clean_html("<script>x()</script><b>Merhaba</b>&amp; dunya")
    assert cleaned == "Merhaba & dunya"
