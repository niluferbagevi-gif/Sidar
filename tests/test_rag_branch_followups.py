import types

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store


def test_chunk_text_returns_single_chunk_for_short_text(tmp_path):
    rag_mod = _load_rag_module("rag_branch_short_chunk")
    store = _new_store(rag_mod, tmp_path)

    chunks = store._chunk_text("kısa not", chunk_size=64, chunk_overlap=8)

    assert chunks == ["kısa not"]



def test_fetch_chroma_skips_blank_parent_ids_and_duplicate_overflow_entries(tmp_path):
    rag_mod = _load_rag_module("rag_branch_chroma_meta_guards")
    store = _new_store(rag_mod, tmp_path)

    class _Collection:
        def count(self):
            return 8

        def query(self, **kwargs):
            assert kwargs["where"] == {"session_id": "sess-1"}
            return {
                "ids": [["", "c1", "c2", "c3"]],
                "documents": [["skip-me", "chunk-1", "chunk-2", "chunk-3"]],
                "metadatas": [[
                    None,
                    {"parent_id": "p1", "title": "Doc 1", "source": "src-1"},
                    {"parent_id": "p2", "title": "Doc 2", "source": "src-2"},
                    {"parent_id": "p2", "title": "Doc 2 dupe", "source": "src-2"},
                ]],
            }

    store.collection = _Collection()
    store._chroma_available = True

    found = store._fetch_chroma("needle", top_k=2, session_id="sess-1")

    assert [row["id"] for row in found] == ["p1", "p2"]
    assert [row["snippet"] for row in found] == ["chunk-1", "chunk-2"]



def test_rrf_search_merges_duplicate_documents_without_division_errors(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_branch_rrf_duplicates")
    store = _new_store(rag_mod, tmp_path)

    store._pgvector_available = False
    store._fetch_chroma = lambda *_a, **_k: [
        {"id": "doc-1", "title": "Vector Doc", "source": "vec", "snippet": "vec-hit", "score": 0.91},
        {"id": "doc-2", "title": "Vector Doc 2", "source": "vec", "snippet": "vec-hit-2", "score": 0.75},
    ]
    store._fetch_bm25 = lambda *_a, **_k: [
        {"id": "doc-1", "title": "Keyword Doc", "source": "bm25", "snippet": "kw-hit", "score": 1.7},
    ]

    captured = {}

    def _format(results, query, source_name):
        captured["results"] = results
        captured["query"] = query
        captured["source_name"] = source_name
        return True, "formatted"

    monkeypatch.setattr(store, "_format_results_from_struct", _format)

    ok, text = store._rrf_search("needle", top_k=2, session_id="sess-1")

    assert ok is True
    assert text == "formatted"
    assert captured["query"] == "needle"
    assert captured["source_name"] == "Hibrit RRF (ChromaDB + BM25)"
    assert [row["id"] for row in captured["results"]] == ["doc-1", "doc-2"]
    assert captured["results"][0]["score"] > captured["results"][1]["score"] > 0.0



def test_fetch_bm25_returns_empty_for_symbol_only_query_without_touching_sqlite(tmp_path):
    rag_mod = _load_rag_module("rag_branch_bm25_symbol_only")
    store = _new_store(rag_mod, tmp_path)
    store._bm25_available = True

    class _Conn:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("sqlite should not run for symbol-only queries")

    store.fts_conn = _Conn()
    store._write_lock = types.SimpleNamespace(__enter__=lambda self: self, __exit__=lambda self, *args: False)

    assert store._fetch_bm25('"" !!! ???', top_k=3, session_id="sess-1") == []
