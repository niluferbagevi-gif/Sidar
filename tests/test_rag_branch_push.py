import asyncio
import sys
import types

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store


def test_validate_url_safe_allows_public_ip_addresses(tmp_path):
    rag_mod = _load_rag_module("rag_branch_public_ip")
    store = _new_store(rag_mod, tmp_path)

    store._validate_url_safe("https://8.8.8.8/search?q=sidar")


def test_add_document_from_url_uses_explicit_title_without_parsing_html_title(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_branch_add_url_explicit_title")
    store = _new_store(rag_mod, tmp_path)

    class _Resp:
        text = "<html><head><title>Ignored</title></head><body>hello</body></html>"

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            assert url == "https://example.com/docs/spec"
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=lambda **_kwargs: _Client()))
    monkeypatch.setattr(store, "_clean_html", lambda html: f"clean:{'Ignored' in html}")
    monkeypatch.setattr(store, "add_document", lambda title, content, source, tags, session_id: asyncio.sleep(0, result="doc-1"))

    ok, msg = asyncio.run(
        store.add_document_from_url(
            "https://example.com/docs/spec",
            title="Provided Title",
            tags=["guide"],
            session_id="sess-1",
        )
    )

    assert ok is True
    assert "Provided Title" in msg
    assert "doc-1" in msg


def test_delete_document_succeeds_when_file_missing_and_chroma_disabled(tmp_path):
    rag_mod = _load_rag_module("rag_branch_delete_missing_file")
    store = _new_store(rag_mod, tmp_path)
    store._index = {
        "doc-1": {"title": "Spec", "session_id": "sess-1", "parent_id": "parent-1"}
    }
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False

    saved = []
    deleted = []
    store._save_index = lambda: saved.append(True)
    store._update_bm25_cache_on_delete = lambda doc_id: deleted.append(doc_id)

    message = store.delete_document("doc-1", session_id="sess-1")

    assert "Belge silindi" in message
    assert saved == [True]
    assert deleted == ["doc-1"]
    assert store._index == {}


def test_analyze_graph_impact_omits_optional_sections_when_analysis_lists_are_empty(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_branch_impact_minimal")
    store = _new_store(rag_mod, tmp_path)

    monkeypatch.setattr(
        store,
        "graph_impact_details",
        lambda target, top_k=10: (
            True,
            {
                "target": target,
                "node_type": "file",
                "risk_level": "low",
                "direct_dependents": [],
                "dependencies": [],
                "impacted_endpoints": [],
                "impacted_endpoint_handlers": [],
                "caller_files": [],
                "review_targets": [],
                "dependency_paths": [],
            },
        ),
    )

    ok, report = store.analyze_graph_impact("core/rag.py", top_k=3)

    assert ok is True
    assert "Düğüm tipi: file" in report
    assert "Risk seviyesi: low" in report
    assert "Doğrudan bağımlılar" not in report
    assert "Aşağı akış bağımlılıklar" not in report
    assert "Etkilenen endpoint'ler" not in report
    assert "Çağıran dosyalar" not in report
    assert "Reviewer için önerilen hedefler" not in report
    assert "Örnek etki zincirleri" not in report


def test_build_knowledge_graph_projection_skips_source_nodes_for_docs_without_source(tmp_path):
    rag_mod = _load_rag_module("rag_branch_projection_no_source")
    store = _new_store(rag_mod, tmp_path)
    store._index = {
        "doc-1": {"title": "Spec", "source": "", "session_id": "sess-1"}
    }
    store._graph_rag_enabled = False

    projection = store.build_knowledge_graph_projection(session_id="sess-1", include_code_graph=False, limit=5)

    assert any(node.id == "doc:doc-1" for node in projection["nodes"])
    assert any(node.id == "session:sess-1" for node in projection["nodes"])
    assert not any(node.id.startswith("source:") for node in projection["nodes"])


def test_build_graphrag_search_plan_skips_vector_lookup_for_blank_queries(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_branch_plan_blank_query")
    store = _new_store(rag_mod, tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._index = {"doc-1": {"title": "Spec", "source": "docs/spec.md", "session_id": "sess-1"}}
    store._pgvector_available = True

    fetch_calls = []
    monkeypatch.setattr(store, "_fetch_pgvector", lambda *_args, **_kwargs: fetch_calls.append(True) or [{"doc_id": "doc-1"}])

    plan = store.build_graphrag_search_plan("   ", session_id="sess-1", top_k=2)

    assert plan.vector_candidates == []
    assert fetch_calls == []
    assert plan.vector_backend == "pgvector"


def test_search_sync_local_provider_falls_back_to_bm25_when_only_bm25_is_available(tmp_path):
    rag_mod = _load_rag_module("rag_branch_local_bm25_fallback")
    store = _new_store(rag_mod, tmp_path)
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._index = {"doc-1": {"session_id": "sess-1"}}
    store._bm25_search = lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}")

    assert store._search_sync("needle", top_k=2, mode="auto", session_id="sess-1") == (
        True,
        "bm25:needle:2:sess-1",
    )


def test_fetch_chroma_skips_duplicate_parent_after_top_k_is_reached(tmp_path):
    rag_mod = _load_rag_module("rag_branch_chroma_duplicate_cap")
    store = _new_store(rag_mod, tmp_path)

    class _Collection:
        def count(self):
            return 10

        def query(self, **kwargs):
            assert kwargs["where"] == {"session_id": "sess-1"}
            return {
                "ids": [["c1", "c2", "c3", "c4"]],
                "documents": [["chunk-1", "chunk-2", "dup-chunk", "chunk-3"]],
                "metadatas": [[
                    {"parent_id": "p1", "title": "Doc 1", "source": "s1"},
                    {"parent_id": "p2", "title": "Doc 2", "source": "s2"},
                    {"parent_id": "p2", "title": "Doc 2 duplicate", "source": "s2"},
                    {"parent_id": "p3", "title": "Doc 3", "source": "s3"},
                ]],
            }

    store.collection = _Collection()
    store._chroma_available = True

    found = store._fetch_chroma("needle", top_k=2, session_id="sess-1")

    assert [item["id"] for item in found] == ["p1", "p2"]
    assert all(item["snippet"] != "dup-chunk" for item in found)


def test_search_sync_local_auto_falls_back_to_bm25_when_collection_truthiness_flips(tmp_path):
    rag_mod = _load_rag_module("rag_branch_local_auto_flaky_collection")
    store = _new_store(rag_mod, tmp_path)
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._pgvector_available = False
    store._chroma_available = True
    store._bm25_available = True
    store._index = {"doc-1": {"session_id": "sess-1"}}
    store._bm25_search = lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}")

    class _FlakyCollection:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

    store.collection = _FlakyCollection()

    assert store._search_sync("needle", top_k=2, mode="auto", session_id="sess-1") == (
        True,
        "bm25:needle:2:sess-1",
    )


def test_fetch_chroma_hits_duplicate_parent_continue_branch_with_stateful_top_k(tmp_path):
    rag_mod = _load_rag_module("rag_branch_chroma_duplicate_continue")
    store = _new_store(rag_mod, tmp_path)

    class _Collection:
        def count(self):
            return 3

        def query(self, **kwargs):
            assert kwargs["where"] == {"session_id": "sess-1"}
            return {
                "ids": [["c1", "c2", "c3"]],
                "documents": [["chunk-1", "dup-chunk", "chunk-2"]],
                "metadatas": [[
                    {"parent_id": "p1", "title": "Doc 1", "source": "s1"},
                    {"parent_id": "p1", "title": "Doc 1 duplicate", "source": "s1"},
                    {"parent_id": "p2", "title": "Doc 2", "source": "s2"},
                ]],
            }

    class _StatefulTopK:
        def __init__(self):
            self.compare_calls = 0

        def __mul__(self, other):
            return 2

        __rmul__ = __mul__

        def __le__(self, other):
            self.compare_calls += 1
            return self.compare_calls >= 2

    store.collection = _Collection()
    store._chroma_available = True

    found = store._fetch_chroma("needle", top_k=_StatefulTopK(), session_id="sess-1")

    assert [item["id"] for item in found] == ["p1", "p2"]
    assert [item["snippet"] for item in found] == ["chunk-1", "chunk-2"]


def test_keyword_search_skips_documents_from_other_sessions(tmp_path):
    rag_mod = _load_rag_module("rag_branch_keyword_session_skip")
    store = _new_store(rag_mod, tmp_path)
    store._index = {
        "doc-a": {"title": "A", "source": "", "session_id": "sess-a"},
        "doc-b": {"title": "B", "source": "", "session_id": "sess-b"},
    }
    (store.store_dir / "doc-a.txt").write_text("needle in session a", encoding="utf-8")
    (store.store_dir / "doc-b.txt").write_text("needle in session b", encoding="utf-8")

    ok, report = store._keyword_search("needle", top_k=5, session_id="sess-a")

    assert ok is True
    assert "[doc-a]" in report
    assert "[doc-b]" not in report


def test_status_includes_graph_engine_when_enabled(tmp_path):
    rag_mod = _load_rag_module("rag_branch_status_graphrag")
    store = _new_store(rag_mod, tmp_path)
    store._index = {"doc-1": {}}
    store._graph_rag_enabled = True
    store._graph_ready = False
    store._pgvector_available = False
    store._vector_backend = "chroma"
    store._chroma_available = False
    store._bm25_available = False

    status = store.status()

    assert "GraphRAG (pasif)" in status
    assert "Anahtar Kelime" in status
