from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from types import SimpleNamespace


def _install_httpx_stub() -> None:
    if "httpx" in sys.modules:
        return

    httpx_stub = types.ModuleType("httpx")

    class TimeoutException(Exception):
        pass

    class ConnectError(Exception):
        pass

    class Request:
        def __init__(self, method: str, url: str) -> None:
            self.method = method
            self.url = url

    class Response:
        def __init__(self, status_code: int, request: Request | None = None) -> None:
            self.status_code = status_code
            self.request = request

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request: Request, response: Response) -> None:
            super().__init__(message)
            self.request = request
            self.response = response
            self.status_code = response.status_code

    httpx_stub.TimeoutException = TimeoutException
    httpx_stub.ConnectError = ConnectError
    httpx_stub.Request = Request
    httpx_stub.Response = Response
    httpx_stub.HTTPStatusError = HTTPStatusError
    sys.modules["httpx"] = httpx_stub


_install_httpx_stub()
mod = importlib.import_module("core.llm_client")
httpx = importlib.import_module("httpx")


def test_build_provider_json_mode_config_known_providers() -> None:
    assert mod.build_provider_json_mode_config("ollama") == {"format": mod.SIDAR_TOOL_JSON_SCHEMA}
    assert mod.build_provider_json_mode_config("openai") == {"response_format": {"type": "json_object"}}
    assert mod.build_provider_json_mode_config("litellm") == {"response_format": {"type": "json_object"}}
    assert mod.build_provider_json_mode_config("gemini") == {"generation_config": {"response_mime_type": "application/json"}}
    assert mod.build_provider_json_mode_config("anthropic") == {}
    assert mod.build_provider_json_mode_config("unknown-provider") == {}


def test_ensure_json_text_keeps_json_and_wraps_plain_text() -> None:
    raw = '{"tool":"final_answer","argument":"ok","thought":"x"}'
    assert mod._ensure_json_text(raw, "openai") == raw

    wrapped = mod._ensure_json_text("plain answer", "openai")
    payload = json.loads(wrapped)
    assert payload["tool"] == "final_answer"
    assert payload["argument"] == "plain answer"


def test_extract_usage_tokens_with_fallback_output_tokens() -> None:
    assert mod._extract_usage_tokens({"usage": {"prompt_tokens": 3, "completion_tokens": 7}}) == (3, 7)
    assert mod._extract_usage_tokens({"usage": {"prompt_tokens": 2, "output_tokens": 9}}) == (2, 9)
    assert mod._extract_usage_tokens({}) == (0, 0)


def test_is_retryable_exception_for_http_status_error() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(status_code=429, request=req)
    exc = httpx.HTTPStatusError("too many requests", request=req, response=resp)

    retryable, code = mod._is_retryable_exception(exc)
    assert retryable is True
    assert code == 429


def test_retry_with_backoff_retries_then_succeeds(monkeypatch) -> None:
    calls = {"count": 0}

    async def _operation() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("temporary connection issue")
        return "ok"

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    cfg = SimpleNamespace(LLM_MAX_RETRIES=2, LLM_RETRY_BASE_DELAY=0.05, LLM_RETRY_MAX_DELAY=0.2)
    result = asyncio.run(mod._retry_with_backoff("openai", _operation, config=cfg, retry_hint="retry test"))

    assert result == "ok"
    assert calls["count"] == 2
    assert len(sleep_calls) == 1


def test_retry_with_backoff_raises_wrapped_api_error() -> None:
    async def _operation() -> None:
        raise ValueError("fatal")

    cfg = SimpleNamespace(LLM_MAX_RETRIES=2, LLM_RETRY_BASE_DELAY=0.05, LLM_RETRY_MAX_DELAY=0.2)
    with __import__("pytest").raises(mod.LLMAPIError) as err:
        asyncio.run(mod._retry_with_backoff("openai", _operation, config=cfg, retry_hint="retry test"))

    assert err.value.provider == "openai"
    assert err.value.retryable is False


def test_semantic_cache_cosine_similarity_edges() -> None:
    cache = mod._SemanticCacheManager(SimpleNamespace())

    assert cache._cosine_similarity([], [1.0]) == 0.0
    assert cache._cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert cache._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_semantic_cache_embed_prompt_handles_embedding_error(monkeypatch) -> None:
    cache = mod._SemanticCacheManager(SimpleNamespace())

    def _raise(*_args, **_kwargs):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr("core.rag.embed_texts_for_semantic_cache", _raise, raising=False)
    assert cache._embed_prompt("hello") == []
