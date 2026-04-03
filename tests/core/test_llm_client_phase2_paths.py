from __future__ import annotations

import asyncio
from types import SimpleNamespace
import sys
import types

if "httpx" not in sys.modules:
    _req = type("Request", (), {"__init__": lambda self,*a,**k: None})
    _resp = type("Response", (), {"__init__": lambda self,*a,**k: setattr(self, "status_code", a[0] if a else k.get("status_code", 0))})
    _hse = type("HTTPStatusError", (Exception,), {})
    sys.modules["httpx"] = types.SimpleNamespace(
        HTTPStatusError=_hse,
        TimeoutException=Exception,
        ConnectError=Exception,
        Timeout=object,
        AsyncClient=object,
        Request=_req,
        Response=_resp,
    )

import core.llm_client as llm


def test_get_tracer_respects_toggle(monkeypatch) -> None:
    fake_trace = SimpleNamespace(get_tracer=lambda _name: "tracer")
    monkeypatch.setattr(llm, "trace", fake_trace)

    assert llm._get_tracer(SimpleNamespace(ENABLE_TRACING=True)) == "tracer"
    assert llm._get_tracer(SimpleNamespace(ENABLE_TRACING=False)) is None


def test_trace_stream_metrics_sets_ttft_and_ends_span() -> None:
    class _Span:
        def __init__(self):
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def end(self):
            self.ended = True

    async def _stream():
        yield "a"
        yield "b"

    span = _Span()

    async def _collect():
        return [chunk async for chunk in llm._trace_stream_metrics(_stream(), span, started_at=0.0)]

    chunks = asyncio.run(_collect())
    assert chunks == ["a", "b"]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" in span.attrs
    assert span.ended is True


def test_semantic_cache_embed_prompt_handles_embedding_error(monkeypatch) -> None:
    cache = llm._SemanticCacheManager(SimpleNamespace(ENABLE_SEMANTIC_CACHE=True))

    def _boom(_texts, cfg=None):
        raise RuntimeError("embed failed")

    monkeypatch.setattr("core.rag.embed_texts_for_semantic_cache", _boom)

    assert cache._embed_prompt("hello") == []


def test_semantic_cache_cosine_edge_cases() -> None:
    assert llm._SemanticCacheManager._cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert llm._SemanticCacheManager._cosine_similarity([1.0], [1.0, 2.0]) == 0.0
