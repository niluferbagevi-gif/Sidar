import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from tests.test_llm_client_critical_gap_closers import _collect, _load_llm_module


def test_semantic_cache_embed_prompt_returns_empty_for_missing_vectors(monkeypatch):
    llm = _load_llm_module()
    cache = llm._SemanticCacheManager(
        SimpleNamespace(
            ENABLE_SEMANTIC_CACHE=True,
            REDIS_URL="redis://test",
            SEMANTIC_CACHE_THRESHOLD=0.5,
            SEMANTIC_CACHE_TTL=30,
            SEMANTIC_CACHE_MAX_ITEMS=10,
        )
    )

    rag_mod = types.ModuleType("core.rag")
    rag_mod.embed_texts_for_semantic_cache = lambda _texts, cfg=None: []
    monkeypatch.setitem(sys.modules, "core.rag", rag_mod)

    assert cache._embed_prompt("hello") == []


def test_openai_chat_allows_none_content_for_non_json_mode(monkeypatch):
    llm = _load_llm_module()
    client = llm.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", OPENAI_TIMEOUT=10))

    async def _return_none(*_args, **_kwargs):
        return {"choices": [{"message": {"content": None}}], "usage": {"prompt_tokens": 1, "completion_tokens": 0}}

    monkeypatch.setattr(llm, "_retry_with_backoff", _return_none)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False))

    assert result is None


def test_openai_stream_interruption_yields_safe_error_and_closes_resources(monkeypatch):
    llm = _load_llm_module()
    client = llm.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", OPENAI_TIMEOUT=10, LLM_MAX_RETRIES=0))
    state = {"client_closed": False, "stream_closed": False}

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "ilk"}}]}'
            raise RuntimeError("openai stream interrupted")

    class _StreamCM:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *_args):
            state["stream_closed"] = True
            return False

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def stream(self, method, url, json=None, headers=None):
            return _StreamCM()

        async def aclose(self):
            state["client_closed"] = True

    async def _call_operation(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm, "_retry_with_backoff", _call_operation)

    out = asyncio.run(
        _collect(
            client._stream_openai(
                {"model": "gpt", "messages": []},
                {"Authorization": "Bearer k"},
                llm.httpx.Timeout(10),
                json_mode=True,
            )
        )
    )

    assert out[0] == "ilk"
    payload = json.loads(out[1])
    assert "OpenAI akış hatası" in payload["argument"]
    assert "openai stream interrupted" in payload["argument"]
    assert state == {"client_closed": True, "stream_closed": True}


def test_litellm_chat_retries_with_fallback_model_after_rate_limit(monkeypatch):
    llm = _load_llm_module()
    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://gateway",
        LITELLM_API_KEY="",
        LITELLM_MODEL="primary-model",
        LITELLM_FALLBACK_MODELS=["backup-model"],
        LITELLM_TIMEOUT=10,
        LLM_MAX_RETRIES=0,
    )
    client = llm.LiteLLMClient(cfg)
    warnings = []

    class _Resp:
        def __init__(self, model_name):
            self.model_name = model_name

        def raise_for_status(self):
            if self.model_name == "primary-model":
                raise llm.httpx.HTTPStatusError(429)
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "backup ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }

    class _HttpxClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, json=None, headers=None):
            return _Resp(json["model"])

    monkeypatch.setattr(llm.httpx, "AsyncClient", _HttpxClient)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)
    monkeypatch.setattr(llm.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    result = asyncio.run(client.chat([{"role": "user", "content": "retry please"}], stream=False, json_mode=False))

    assert result == "backup ok"
    assert warnings and "primary-model" in warnings[0]


def test_litellm_stream_interruption_yields_safe_error_and_closes_resources(monkeypatch):
    llm = _load_llm_module()
    client = llm.LiteLLMClient(SimpleNamespace(LITELLM_GATEWAY_URL="http://gateway", LITELLM_TIMEOUT=10, LLM_MAX_RETRIES=0))
    state = {"client_closed": False, "stream_closed": False}

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "parca"}}]}'
            raise RuntimeError("litellm stream interrupted")

    class _StreamCM:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *_args):
            state["stream_closed"] = True
            return False

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def stream(self, method, endpoint, json=None, headers=None):
            return _StreamCM()

        async def aclose(self):
            state["client_closed"] = True

    async def _call_operation(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm, "_retry_with_backoff", _call_operation)

    out = asyncio.run(
        _collect(
            client._stream_openai_compatible(
                "http://gateway/chat/completions",
                {"model": "primary", "messages": [], "stream": True},
                {},
                llm.httpx.Timeout(10),
                json_mode=True,
            )
        )
    )

    assert out[0] == "parca"
    payload = json.loads(out[1])
    assert "LiteLLM akış hatası" in payload["argument"]
    assert "litellm stream interrupted" in payload["argument"]
    assert state == {"client_closed": True, "stream_closed": True}

def test_openai_chat_retries_through_transient_500_until_success(monkeypatch):
    llm = _load_llm_module()
    client = llm.OpenAIClient(
        SimpleNamespace(
            OPENAI_API_KEY="k",
            OPENAI_MODEL="gpt",
            OPENAI_TIMEOUT=10,
            LLM_MAX_RETRIES=2,
            LLM_RETRY_BASE_DELAY=0.05,
            LLM_RETRY_MAX_DELAY=0.05,
        )
    )
    attempts = {"count": 0}
    sleeps = []

    class _Resp:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 500:
                raise llm.httpx.HTTPStatusError(self.status_code)

        def json(self):
            return {
                "choices": [{"message": {"content": "retry ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                return _Resp(500)
            return _Resp(200)

    async def _fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    result = asyncio.run(client.chat([{"role": "user", "content": "retry please"}], stream=False, json_mode=False))

    assert result == "retry ok"
    assert attempts["count"] == 3
    assert sleeps == [0.05, 0.05]


def test_anthropic_chat_retries_until_timeout_budget_is_exhausted(monkeypatch):
    llm = _load_llm_module()
    attempts = {"count": 0}
    sleeps = []

    class _AsyncAnthropic:
        def __init__(self, api_key, timeout):
            self.api_key = api_key
            self.timeout = timeout
            self.messages = types.SimpleNamespace(create=self._create)

        async def _create(self, **_kwargs):
            attempts["count"] += 1
            raise llm.httpx.TimeoutException("anthropic timeout")

    async def _fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    monkeypatch.setattr(llm.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    client = llm.AnthropicClient(
        SimpleNamespace(
            ANTHROPIC_API_KEY="k",
            ANTHROPIC_MODEL="claude",
            ANTHROPIC_TIMEOUT=10,
            LLM_MAX_RETRIES=2,
            LLM_RETRY_BASE_DELAY=0.05,
            LLM_RETRY_MAX_DELAY=0.05,
        )
    )

    with pytest.raises(llm.LLMAPIError) as exc:
        asyncio.run(client.chat([{"role": "user", "content": "still timing out"}], stream=False, json_mode=False))

    assert exc.value.provider == "anthropic"
    assert exc.value.retryable is True
    assert "anthropic timeout" in str(exc.value)
    assert attempts["count"] == 3
    assert sleeps == [0.05, 0.05]
