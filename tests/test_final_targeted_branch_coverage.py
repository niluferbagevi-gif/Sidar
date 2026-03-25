import asyncio
import ctypes
import sys

import core.ci_remediation as ci_mod
from core.llm_metrics import LLMMetricsCollector
from core.multimodal import build_multimodal_context
from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store
from tests.test_sidar_agent_runtime import ExternalTrigger, SA_MOD, _make_agent_for_runtime


_PYFRAME_LOCALS_TO_FAST = ctypes.pythonapi.PyFrame_LocalsToFast
_PYFRAME_LOCALS_TO_FAST.argtypes = [ctypes.py_object, ctypes.c_int]
_PYFRAME_LOCALS_TO_FAST.restype = None


def _set_frame_local(frame, name, value):
    frame.f_locals[name] = value
    _PYFRAME_LOCALS_TO_FAST(frame, 1)


def test_handle_external_trigger_skips_self_heal_when_status_mutates_before_guard(monkeypatch):
    agent = _make_agent_for_runtime()
    agent.initialize = lambda: asyncio.sleep(0)
    calls = {"heal": 0}

    async def _multi(_prompt):
        return "ci teşhisi"

    async def _heal(**_kwargs):
        calls["heal"] += 1

    monkeypatch.setattr(
        SA_MOD,
        "build_ci_remediation_payload",
        lambda ctx, summary: {"summary": summary, "remediation_loop": {"status": "planned", "steps": []}},
    )
    agent._try_multi_agent = _multi
    agent._attempt_autonomous_self_heal = _heal

    previous = sys.gettrace()

    def _tracer(frame, event, arg):
        if frame.f_code.co_name == "handle_external_trigger" and event == "line" and frame.f_lineno == 641:
            _set_frame_local(frame, "status", "partial")
        return _tracer

    sys.settrace(_tracer)
    try:
        record = asyncio.run(
            agent.handle_external_trigger(
                ExternalTrigger(
                    trigger_id="tr-ci-skip-heal",
                    source="webhook:github",
                    event_name="workflow_run",
                    payload={"kind": "workflow_run", "workflow_name": "CI", "task_id": "ci-77"},
                )
            )
        )
    finally:
        sys.settrace(previous)

    assert record["status"] == "partial"
    assert record["summary"] == "ci teşhisi"
    assert record["remediation"]["summary"] == "ci teşhisi"
    assert calls["heal"] == 0



def test_build_root_cause_summary_skips_empty_first_sentence_branch_via_trace(monkeypatch):
    monkeypatch.setattr(ci_mod, "_extract_root_cause_line", lambda *_args: "Inferred root cause")

    previous = sys.gettrace()

    def _tracer(frame, event, arg):
        if frame.f_code.co_name == "build_root_cause_summary" and event == "line" and frame.f_lineno == 421:
            _set_frame_local(frame, "first_sentence", "")
        return _tracer

    sys.settrace(_tracer)
    try:
        summary = ci_mod.build_root_cause_summary({}, "Root cause: websocket teardown")
    finally:
        sys.settrace(previous)

    assert summary == "Inferred root cause"



def test_llm_metrics_snapshot_skips_latency_average_when_row_calls_is_zero_via_trace():
    collector = LLMMetricsCollector(max_events=5)
    collector.record(provider="openai", model="gpt-4o-mini", latency_ms=5, prompt_tokens=1, completion_tokens=1)

    previous = sys.gettrace()

    def _tracer(frame, event, arg):
        if frame.f_code.co_name == "snapshot" and event == "line" and frame.f_lineno == 209:
            row = frame.f_locals.get("row")
            if isinstance(row, dict):
                row["calls"] = 0
        return _tracer

    sys.settrace(_tracer)
    try:
        snap = collector.snapshot()
    finally:
        sys.settrace(previous)

    assert snap["by_provider"]["openai"]["latency_ms_avg"] == 5.0
    assert snap["by_provider"]["openai"]["latency_ms_max"] == 5.0



def test_build_multimodal_context_skips_reason_and_language_when_transcript_fields_blank():
    context = build_multimodal_context(
        media_kind="video",
        transcript={"text": "   ", "reason": "", "language": "   "},
        frame_analyses=None,
        extra_notes="",
    )

    assert context == "Medya Türü: video"



def test_build_graphrag_search_plan_skips_chroma_branch_when_collection_missing(tmp_path):
    rag_mod = _load_rag_module("rag_targeted_graphrag_missing_collection")
    store = _new_store(rag_mod, tmp_path)
    store._chroma_available = True
    store.collection = None
    store._pgvector_available = False
    store.build_knowledge_graph_projection = lambda **_kwargs: {"nodes": [], "edges": [], "cypher_hint": ""}
    store._fetch_chroma = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("chroma fetch should not run"))

    plan = store.build_graphrag_search_plan("spec query", session_id="sess-1", top_k=2)

    assert plan.vector_backend == "bm25"
    assert plan.vector_candidates == []



def test_search_sync_local_auto_falls_back_to_bm25_when_chroma_collection_drops_via_trace(tmp_path):
    rag_mod = _load_rag_module("rag_targeted_local_auto_bm25_fallback")
    store = _new_store(rag_mod, tmp_path)
    store._index = {"doc-1": {"session_id": "s1", "title": "Doc", "source": "src", "tags": []}}
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = True
    store._bm25_search = lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}")

    previous = sys.gettrace()

    def _tracer(frame, event, arg):
        if frame.f_code.co_name == "_search_sync" and event == "line" and frame.f_lineno == 1494:
            store.collection = None
        return _tracer

    sys.settrace(_tracer)
    try:
        result = store._search_sync("needle", top_k=2, mode="auto", session_id="s1")
    finally:
        sys.settrace(previous)

    assert result == (True, "bm25:needle:2:s1")



def test_fetch_chroma_skips_duplicate_parent_after_top_k_is_reached(tmp_path):
    rag_mod = _load_rag_module("rag_targeted_chroma_duplicate_continue")
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



def test_fetch_chroma_returns_empty_when_query_has_no_document_chunks(tmp_path):
    rag_mod = _load_rag_module("rag_targeted_chroma_empty_chunks")
    store = _new_store(rag_mod, tmp_path)

    class _Collection:
        def count(self):
            return 1

        def query(self, **kwargs):
            assert kwargs["where"] == {"session_id": "sess-1"}
            return {"ids": [["c1"]], "documents": [[]], "metadatas": [[]]}

    store.collection = _Collection()
    store._chroma_available = True

    assert store._fetch_chroma("needle", top_k=2, session_id="sess-1") == []



def test_rag_status_omits_graphrag_engine_when_disabled(tmp_path):
    rag_mod = _load_rag_module("rag_targeted_status_no_graph")
    store = _new_store(rag_mod, tmp_path)
    store._index = {"doc-1": {}}
    store._pgvector_available = False
    store._vector_backend = "pgvector"
    store._chroma_available = False
    store._bm25_available = True
    store._graph_rag_enabled = False
    store._graph_ready = True

    status = store.status()

    assert status == "RAG: 1 belge | Motorlar: pgvector (pasif), BM25 (SQLite FTS5), Anahtar Kelime"