from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def test_build_graphrag_plan_non_empty_query_skips_chroma_when_collection_missing(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    store._pgvector_available = False
    store._chroma_available = True
    store.collection = None
    monkeypatch.setattr(store, "_fetch_chroma", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("chroma fetch should not run")))

    plan = store.build_graphrag_search_plan("aktif sorgu", session_id="sess-1", top_k=2)

    assert plan.vector_backend == "bm25"
    assert plan.vector_candidates == []


def test_search_sync_local_auto_path_falls_back_to_bm25_when_collection_becomes_unavailable(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)
    store._index["doc-1"] = {"session_id": "sess-1"}

    class _FlakyCollection:
        def __init__(self):
            self._checks = 0

        def __bool__(self):
            self._checks += 1
            return self._checks == 1

    store._pgvector_available = False
    store._chroma_available = True
    store.collection = _FlakyCollection()
    store._bm25_available = True
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False

    monkeypatch.setattr(store, "_chroma_search", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("chroma fallback should not run")))
    monkeypatch.setattr(store, "_bm25_search", lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}"))

    assert store._search_sync("q", top_k=2, mode="auto", session_id="sess-1") == (True, "bm25:q:2:sess-1")


def test_fetch_chroma_returns_empty_when_ids_exist_but_document_chunks_are_empty(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    class _Collection:
        def count(self):
            return 1

        def query(self, **_kwargs):
            return {
                "ids": [["chunk-1"]],
                "documents": [[]],
                "metadatas": [[{"parent_id": "doc-1", "title": "Doc 1"}]],
            }

    store.collection = _Collection()
    assert store._fetch_chroma("needle", top_k=2, session_id="s1") == []


def test_fetch_chroma_skips_duplicate_parent_when_top_k_already_reached(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    class _Collection:
        def count(self):
            return 2

        def query(self, **_kwargs):
            return {
                "ids": [["chunk-1", "chunk-2"]],
                "documents": [["first", "second"]],
                "metadatas": [[
                    {"parent_id": "doc-1", "title": "Doc 1"},
                    {"parent_id": "doc-1", "title": "Doc 1 duplicate"},
                ]],
            }

    store.collection = _Collection()
    out = store._fetch_chroma("needle", top_k=1, session_id="s1")

    assert len(out) == 1
    assert out[0]["id"] == "doc-1"
    assert out[0]["snippet"] == "first"


def test_status_omits_graphrag_engine_when_feature_disabled(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    store._graph_rag_enabled = False
    store._bm25_available = False
    store._pgvector_available = False
    store._vector_backend = "bm25"
    store._chroma_available = False

    status = store.status()

    assert "GraphRAG" not in status
    assert "Anahtar Kelime" in status
