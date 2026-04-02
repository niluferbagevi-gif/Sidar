from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import importlib.util
import sys
import types

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")

    class Request:
        def __init__(self, method: str, url: str) -> None:
            self.method = method
            self.url = url

    class Response:
        def __init__(self, status_code: int, request=None) -> None:
            self.status_code = status_code
            self.request = request

    class TimeoutException(Exception):
        pass

    class ConnectError(Exception):
        pass

    class ReadTimeout(TimeoutException):
        pass

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None) -> None:
            super().__init__(message)
            self.request = request
            self.response = response

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.Request = Request
    fake_httpx.Response = Response
    fake_httpx.TimeoutException = TimeoutException
    fake_httpx.ConnectError = ConnectError
    fake_httpx.ReadTimeout = ReadTimeout
    fake_httpx.HTTPStatusError = HTTPStatusError
    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx


import pytest

import core.llm_client as llm_client


def test_build_provider_json_mode_config_supports_known_providers() -> None:
    assert llm_client.build_provider_json_mode_config("ollama") == {"format": llm_client.SIDAR_TOOL_JSON_SCHEMA}
    assert llm_client.build_provider_json_mode_config("openai") == {"response_format": {"type": "json_object"}}
    assert llm_client.build_provider_json_mode_config("litellm") == {"response_format": {"type": "json_object"}}
    assert llm_client.build_provider_json_mode_config("gemini") == {
        "generation_config": {"response_mime_type": "application/json"}
    }
    assert llm_client.build_provider_json_mode_config("anthropic") == {}
    assert llm_client.build_provider_json_mode_config("unknown") == {}


def test_ensure_json_text_wraps_non_json_output() -> None:
    raw = "tool output"
    wrapped = llm_client._ensure_json_text(raw, "openai")

    parsed = json.loads(wrapped)
    assert parsed["tool"] == "final_answer"
    assert parsed["argument"] == raw


def test_extract_usage_tokens_defaults_missing_values() -> None:
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 12, "completion_tokens": 7}}) == (12, 7)
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 3, "output_tokens": 9}}) == (3, 9)
    assert llm_client._extract_usage_tokens({}) == (0, 0)


def test_is_retryable_exception_covers_status_and_timeout_cases() -> None:
    req = llm_client.httpx.Request("GET", "https://example.com")
    resp_503 = llm_client.httpx.Response(503, request=req)
    exc_503 = llm_client.httpx.HTTPStatusError("server", request=req, response=resp_503)
    assert llm_client._is_retryable_exception(exc_503) == (True, 503)

    resp_400 = llm_client.httpx.Response(400, request=req)
    exc_400 = llm_client.httpx.HTTPStatusError("bad", request=req, response=resp_400)
    assert llm_client._is_retryable_exception(exc_400) == (False, 400)

    timeout = llm_client.httpx.TimeoutException("timeout")
    assert llm_client._is_retryable_exception(timeout) == (True, None)


def test_retry_with_backoff_retries_and_returns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(LLM_MAX_RETRIES=2, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.05)
    state = {"calls": 0}

    async def op():
        state["calls"] += 1
        if state["calls"] < 2:
            raise llm_client.httpx.ConnectError("temporary")
        return "ok"

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.0)

    result = asyncio.run(llm_client._retry_with_backoff("openai", op, config=cfg, retry_hint="test"))

    assert result == "ok"
    assert state["calls"] == 2
    assert len(sleeps) == 1


def test_retry_with_backoff_raises_api_error_after_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(LLM_MAX_RETRIES=1, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.05)

    async def failing_op():
        raise llm_client.httpx.ReadTimeout("still failing")

    async def _fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(llm_client.LLMAPIError) as err:
        asyncio.run(llm_client._retry_with_backoff("openai", failing_op, config=cfg, retry_hint="failcase"))

    assert err.value.provider == "openai"
    assert err.value.retryable is True


def test_track_stream_completion_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake_record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(llm_client, "_record_llm_metric", _fake_record)

    async def _stream():
        yield "a"
        yield "b"

    async def _collect():
        chunks = []
        async for chunk in llm_client._track_stream_completion(_stream(), provider="openai", model="gpt", started_at=0.0):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())
    assert chunks == ["a", "b"]
    assert calls[-1]["success"] is True


def test_trace_stream_metrics_sets_ttft_and_ends_span() -> None:
    class DummySpan:
        def __init__(self) -> None:
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value) -> None:
            self.attrs[key] = value

        def end(self) -> None:
            self.ended = True

    async def _stream():
        yield "token"

    span = DummySpan()

    async def _collect():
        chunks = []
        async for chunk in llm_client._trace_stream_metrics(_stream(), span, started_at=0.0):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())
    assert chunks == ["token"]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" in span.attrs
    assert span.ended is True


def test_semantic_cache_cosine_similarity_edges() -> None:
    assert llm_client._SemanticCacheManager._cosine_similarity([], [1.0]) == 0.0
    assert llm_client._SemanticCacheManager._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert llm_client._SemanticCacheManager._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_ensure_json_text_preserves_valid_json() -> None:
    raw = '{"tool":"final_answer","argument":"ok"}'
    assert llm_client._ensure_json_text(raw, "openai") == raw


def test_track_stream_completion_records_error_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _fake_record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(llm_client, "_record_llm_metric", _fake_record)

    async def _failing_stream():
        yield "start"
        raise RuntimeError("boom")

    async def _consume() -> None:
        async for _chunk in llm_client._track_stream_completion(
            _failing_stream(), provider="openai", model="gpt", started_at=0.0
        ):
            pass

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(_consume())

    assert calls[-1]["success"] is False
    assert "boom" in calls[-1]["error"]


def test_ensure_json_text_wraps_empty_plaintext() -> None:
    wrapped = llm_client._ensure_json_text("", "openai")
    payload = __import__("json").loads(wrapped)
    assert payload["tool"] == "final_answer"
    assert "boş içerik" in payload["argument"]


def test_is_retryable_exception_handles_asyncio_timeout() -> None:
    retryable, status = llm_client._is_retryable_exception(asyncio.TimeoutError())
    assert retryable is True
    assert status is None
