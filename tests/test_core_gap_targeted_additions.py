import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from core.dlp import DLPEngine, _is_valid_tckn
from tests.test_db_postgresql_branches import _pg_db
from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def test_postgresql_audit_log_insert_and_list_paths_cover_filtering():
    db, conn, _pool = _pg_db()
    fetch_calls = []
    original_fetch = conn.fetch

    async def _fetch(query, *args):
        fetch_calls.append((query, args))
        return await original_fetch(query, *args)

    conn.fetch = _fetch

    async def _run():
        await db.record_audit_log(
            user_id=" u-1 ",
            tenant_id=" ",
            action=" READ ",
            resource="rag:*",
            ip_address=" ",
            allowed=True,
            timestamp="2026-03-19T00:00:00Z",
        )
        insert_query, insert_args = conn.execute_calls[-1]
        assert "INSERT INTO audit_logs" in insert_query
        assert insert_args == (
            "u-1",
            "default",
            "read",
            "rag:*",
            "unknown",
            True,
            "2026-03-19T00:00:00Z",
        )

        conn.fetch_queue.append(
            [
                {
                    "id": 1,
                    "user_id": "u-1",
                    "tenant_id": "default",
                    "action": "read",
                    "resource": "rag:*",
                    "ip_address": "unknown",
                    "allowed": True,
                    "timestamp": "2026-03-19T00:00:00Z",
                }
            ]
        )
        logs = await db.list_audit_logs(limit=3)
        assert logs[0].resource == "rag:*"
        assert "LIMIT $1" in fetch_calls[0][0]
        assert fetch_calls[0][1] == (3,)

        conn.fetch_queue.append(
            [
                {
                    "id": 2,
                    "user_id": "u-1",
                    "tenant_id": "default",
                    "action": "write",
                    "resource": "github:*",
                    "ip_address": "127.0.0.1",
                    "allowed": False,
                    "timestamp": "2026-03-20T00:00:00Z",
                }
            ]
        )
        filtered = await db.list_audit_logs(user_id=" u-1 ", limit=2)
        assert filtered[0].action == "write"
        assert "WHERE user_id=$1" in fetch_calls[1][0]
        assert fetch_calls[1][1] == ("u-1", 2)

    asyncio.run(_run())


def test_dlp_engine_leaves_invalid_tckn_unmasked_and_masks_valid_one():
    assert _is_valid_tckn("10000000A46") is False

    engine = DLPEngine(replacement="[MASK]")
    invalid_text = "Kimlik: 12345678901"
    masked_invalid, invalid_detections = engine.mask(invalid_text)
    assert masked_invalid == invalid_text
    assert invalid_detections == []

    valid_text = "Kimlik: 10000000146"
    masked_valid, valid_detections = engine.mask(valid_text)
    assert masked_valid == "Kimlik: [MASK]"
    assert [d.pattern_name for d in valid_detections] == ["tckn"]


def test_openai_missing_key_stream_and_anthropic_503_error_paths():
    llm_mod = _load_llm_client_module()

    openai_client = llm_mod.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="", OPENAI_TIMEOUT=30))
    async def _collect_openai_stream():
        stream_iter = await openai_client.chat(
            messages=[{"role": "user", "content": "merhaba"}],
            stream=True,
            json_mode=True,
        )
        return await _collect(stream_iter)

    stream = asyncio.run(_collect_openai_stream())
    payload = json.loads("".join(stream))
    assert payload["tool"] == "final_answer"
    assert "OPENAI_API_KEY" in payload["argument"]

    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.AsyncAnthropic = lambda **_kwargs: SimpleNamespace(messages=SimpleNamespace(create=lambda **_k: None))
    sys.modules["anthropic"] = anthropic_mod

    async def _raise_503(*_args, **_kwargs):
        raise llm_mod.LLMAPIError("anthropic", "503 Service Unavailable", status_code=503, retryable=True)

    client = llm_mod.AnthropicClient(
        SimpleNamespace(ANTHROPIC_API_KEY="key", ANTHROPIC_TIMEOUT=30, ANTHROPIC_MODEL="claude")
    )
    original_retry = llm_mod._retry_with_backoff
    llm_mod._retry_with_backoff = _raise_503
    try:
        with pytest.raises(llm_mod.LLMAPIError) as excinfo:
            asyncio.run(client.chat(messages=[{"role": "user", "content": "selam"}], stream=False, json_mode=False))
    finally:
        llm_mod._retry_with_backoff = original_retry
        sys.modules.pop("anthropic", None)

    assert excinfo.value.status_code == 503
    assert excinfo.value.retryable is True


def test_rag_fetch_chroma_returns_empty_for_blank_vector_results(tmp_path):
    rag_mod = _load_rag_module(tmp_path)
    store = _new_store(rag_mod, tmp_path)

    seen = {}

    class _Collection:
        def count(self):
            raise RuntimeError("count unavailable")

        def query(self, **kwargs):
            seen.update(kwargs)
            return {"ids": [[]], "documents": [[]], "metadatas": [[]]}

    store.collection = _Collection()
    store._chroma_available = True

    found = store._fetch_chroma("needle", top_k=2, session_id="sess-1")

    assert found == []
    assert seen["query_texts"] == ["needle"]
    assert seen["where"] == {"session_id": "sess-1"}
    assert seen["n_results"] == 4