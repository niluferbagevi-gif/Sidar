"""
core/llm_client.py için birim testleri.
Saf yardımcı fonksiyonlar (build_provider_json_mode_config, LLMAPIError,
_is_retryable_exception, _ensure_json_text, _extract_usage_tokens,
_cosine_similarity) ve retry mekanizmasını kapsar.
HTTP/LLM çağrıları gerektiren provider sınıfları stub'lanır.
"""
from __future__ import annotations

import asyncio
import time
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest


def _get_llm_client():
    # redis stub — redis.asyncio optional
    if "redis" not in sys.modules:
        redis_stub = types.ModuleType("redis")
        redis_asyncio = types.ModuleType("redis.asyncio")
        redis_stub.asyncio = redis_asyncio
        sys.modules["redis"] = redis_stub
        sys.modules["redis.asyncio"] = redis_asyncio

    if "core.llm_client" in sys.modules:
        del sys.modules["core.llm_client"]
    import core.llm_client as lc
    return lc


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════
# build_provider_json_mode_config
# ══════════════════════════════════════════════════════════════

class TestBuildProviderJsonModeConfig:
    def test_ollama_returns_format_key(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("ollama")
        assert "format" in cfg

    def test_openai_returns_response_format(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("openai")
        assert cfg.get("response_format", {}).get("type") == "json_object"

    def test_litellm_same_as_openai(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("litellm")
        assert cfg.get("response_format", {}).get("type") == "json_object"

    def test_gemini_returns_generation_config(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("gemini")
        assert "generation_config" in cfg

    def test_anthropic_returns_empty_dict(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("anthropic")
        assert cfg == {}

    def test_unknown_provider_returns_empty_dict(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("unknown_provider")
        assert cfg == {}

    def test_case_insensitive(self):
        lc = _get_llm_client()
        cfg_upper = lc.build_provider_json_mode_config("OPENAI")
        cfg_lower = lc.build_provider_json_mode_config("openai")
        assert cfg_upper == cfg_lower

    def test_empty_string_returns_empty_dict(self):
        lc = _get_llm_client()
        cfg = lc.build_provider_json_mode_config("")
        assert cfg == {}


# ══════════════════════════════════════════════════════════════
# LLMAPIError
# ══════════════════════════════════════════════════════════════

class TestLLMAPIError:
    def test_attributes_set(self):
        lc = _get_llm_client()
        err = lc.LLMAPIError("openai", "rate limit", status_code=429, retryable=True)
        assert err.provider == "openai"
        assert err.status_code == 429
        assert err.retryable is True

    def test_is_runtime_error(self):
        lc = _get_llm_client()
        err = lc.LLMAPIError("anthropic", "timeout")
        assert isinstance(err, RuntimeError)

    def test_default_status_none(self):
        lc = _get_llm_client()
        err = lc.LLMAPIError("gemini", "error")
        assert err.status_code is None

    def test_default_retryable_false(self):
        lc = _get_llm_client()
        err = lc.LLMAPIError("gemini", "error")
        assert err.retryable is False


# ══════════════════════════════════════════════════════════════
# _is_retryable_exception
# ══════════════════════════════════════════════════════════════

class TestIsRetryableException:
    def test_timeout_exception_retryable(self):
        lc = _get_llm_client()
        import httpx
        exc = httpx.TimeoutException("timeout")
        retryable, code = lc._is_retryable_exception(exc)
        assert retryable is True

    def test_connect_error_retryable(self):
        lc = _get_llm_client()
        import httpx
        exc = httpx.ConnectError("connection refused")
        retryable, code = lc._is_retryable_exception(exc)
        assert retryable is True

    def test_429_status_retryable(self):
        lc = _get_llm_client()
        exc = Exception("rate limit")
        exc.status_code = 429
        retryable, code = lc._is_retryable_exception(exc)
        assert retryable is True
        assert code == 429

    def test_500_status_retryable(self):
        lc = _get_llm_client()
        exc = Exception("server error")
        exc.status_code = 500
        retryable, code = lc._is_retryable_exception(exc)
        assert retryable is True

    def test_400_not_retryable(self):
        lc = _get_llm_client()
        exc = Exception("bad request")
        exc.status_code = 400
        retryable, code = lc._is_retryable_exception(exc)
        assert retryable is False

    def test_value_error_not_retryable(self):
        lc = _get_llm_client()
        retryable, code = lc._is_retryable_exception(ValueError("bad"))
        assert retryable is False

    def test_asyncio_timeout_retryable(self):
        lc = _get_llm_client()
        retryable, code = lc._is_retryable_exception(asyncio.TimeoutError())
        assert retryable is True


# ══════════════════════════════════════════════════════════════
# _ensure_json_text
# ══════════════════════════════════════════════════════════════

class TestEnsureJsonText:
    def test_valid_json_returned_as_is(self):
        lc = _get_llm_client()
        raw = '{"tool": "search", "argument": "python"}'
        result = lc._ensure_json_text(raw, "openai")
        assert result == raw

    def test_invalid_json_wrapped_in_final_answer(self):
        lc = _get_llm_client()
        import json
        result = lc._ensure_json_text("plain text response", "openai")
        parsed = json.loads(result)
        assert parsed["tool"] == "final_answer"
        assert parsed["argument"] == "plain text response"

    def test_empty_text_wrapped(self):
        lc = _get_llm_client()
        import json
        result = lc._ensure_json_text("", "openai")
        parsed = json.loads(result)
        assert "UYARI" in parsed["argument"]

    def test_markdown_not_json_wrapped(self):
        lc = _get_llm_client()
        import json
        result = lc._ensure_json_text("```json\n{}\n```", "openai")
        # starts with ``` so not valid JSON — gets wrapped
        parsed = json.loads(result)
        assert "thought" in parsed


# ══════════════════════════════════════════════════════════════
# _extract_usage_tokens
# ══════════════════════════════════════════════════════════════

class TestExtractUsageTokens:
    def test_standard_fields(self):
        lc = _get_llm_client()
        data = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        prompt, completion = lc._extract_usage_tokens(data)
        assert prompt == 100
        assert completion == 50

    def test_output_tokens_alias(self):
        lc = _get_llm_client()
        data = {"usage": {"prompt_tokens": 80, "output_tokens": 30}}
        prompt, completion = lc._extract_usage_tokens(data)
        assert prompt == 80
        assert completion == 30

    def test_missing_usage_returns_zeros(self):
        lc = _get_llm_client()
        prompt, completion = lc._extract_usage_tokens({})
        assert prompt == 0
        assert completion == 0

    def test_empty_dict(self):
        lc = _get_llm_client()
        prompt, completion = lc._extract_usage_tokens({"usage": {}})
        assert prompt == 0
        assert completion == 0

    def test_non_dict_input(self):
        lc = _get_llm_client()
        prompt, completion = lc._extract_usage_tokens("not a dict")
        assert prompt == 0
        assert completion == 0


# ══════════════════════════════════════════════════════════════
# _SemanticCacheManager._cosine_similarity
# ══════════════════════════════════════════════════════════════

class TestCosineSimilarity:
    def _sim(self, a, b):
        lc = _get_llm_client()
        return lc._SemanticCacheManager._cosine_similarity(a, b)

    def test_identical_vectors(self):
        assert abs(self._sim([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        assert abs(self._sim([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_opposite_vectors(self):
        assert abs(self._sim([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-6

    def test_empty_vector_returns_zero(self):
        assert self._sim([], [1.0, 0.0]) == 0.0

    def test_different_lengths_returns_zero(self):
        assert self._sim([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0

    def test_zero_vector_returns_zero(self):
        assert self._sim([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_partial_similarity(self):
        import math
        sim = self._sim([1.0, 1.0], [1.0, 0.0])
        assert abs(sim - 1.0 / math.sqrt(2)) < 1e-5


class TestSemanticCacheManagerEdgeCases:
    def test_get_returns_none_when_cached_embedding_is_malformed_json(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            ENABLE_SEMANTIC_CACHE = True
            SEMANTIC_CACHE_THRESHOLD = 0.8

        class _FakeRedis:
            async def lrange(self, *_args, **_kwargs):
                return ["k1"]

            async def hgetall(self, _key):
                return {"embedding": "{bad-json", "response": "cached response"}

        cache = lc._SemanticCacheManager(_Cfg())
        monkeypatch.setattr(cache, "_get_redis", AsyncMock(return_value=_FakeRedis()))
        monkeypatch.setattr(cache, "_embed_prompt", lambda _prompt: [0.1, 0.2, 0.3])

        result = _run(cache.get("prompt"))

        assert result is None


# ══════════════════════════════════════════════════════════════
# _retry_with_backoff
# ══════════════════════════════════════════════════════════════

class TestRetryWithBackoff:
    def test_success_on_first_attempt(self):
        lc = _get_llm_client()

        class _Cfg:
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.01
            LLM_RETRY_MAX_DELAY = 0.1

        call_count = [0]

        async def operation():
            call_count[0] += 1
            return "ok"

        result = _run(lc._retry_with_backoff("openai", operation, config=_Cfg(), retry_hint="test"))
        assert result == "ok"
        assert call_count[0] == 1

    def test_retries_on_retryable_error(self):
        lc = _get_llm_client()

        class _Cfg:
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01

        call_count = [0]

        async def operation():
            call_count[0] += 1
            if call_count[0] < 3:
                err = asyncio.TimeoutError("timeout")
                raise err
            return "success"

        result = _run(lc._retry_with_backoff("openai", operation, config=_Cfg(), retry_hint="test"))
        assert result == "success"
        assert call_count[0] == 3

    def test_raises_after_max_retries(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            LLM_MAX_RETRIES = 1
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01

        async def operation():
            raise asyncio.TimeoutError("always fails")

        with pytest.raises(lc.LLMAPIError):
            _run(lc._retry_with_backoff("openai", operation, config=_Cfg(), retry_hint="test"))

    def test_non_retryable_error_raises_immediately(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            LLM_MAX_RETRIES = 3
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01

        call_count = [0]

        async def operation():
            call_count[0] += 1
            raise ValueError("bad request")

        with pytest.raises(lc.LLMAPIError):
            _run(lc._retry_with_backoff("openai", operation, config=_Cfg(), retry_hint="test"))
        assert call_count[0] == 1  # No retries


class TestStreamHelpers:
    def test_fallback_stream_yields_single_message(self):
        lc = _get_llm_client()

        async def _collect():
            out = []
            async for chunk in lc._fallback_stream("fallback-error"):
                out.append(chunk)
            return out

        assert _run(_collect()) == ["fallback-error"]

    def test_track_stream_completion_records_success_metric(self, monkeypatch):
        lc = _get_llm_client()
        metric_calls = []
        monkeypatch.setattr(lc, "_record_llm_metric", lambda **kwargs: metric_calls.append(kwargs))

        async def _stream():
            yield "a"
            yield "b"

        async def _collect():
            chunks = []
            async for chunk in lc._track_stream_completion(
                _stream(),
                provider="openai",
                model="gpt-test",
                started_at=1.0,
            ):
                chunks.append(chunk)
            return chunks

        assert _run(_collect()) == ["a", "b"]
        assert metric_calls[-1]["success"] is True

    def test_track_stream_completion_records_failure_metric(self, monkeypatch):
        lc = _get_llm_client()
        metric_calls = []
        monkeypatch.setattr(lc, "_record_llm_metric", lambda **kwargs: metric_calls.append(kwargs))

        async def _broken_stream():
            yield "before-error"
            raise RuntimeError("stream boom")

        async def _consume():
            async for _ in lc._track_stream_completion(
                _broken_stream(),
                provider="anthropic",
                model="claude-test",
                started_at=2.0,
            ):
                pass

        import pytest

        with pytest.raises(RuntimeError, match="stream boom"):
            _run(_consume())
        assert metric_calls[-1]["success"] is False
        assert "stream boom" in metric_calls[-1]["error"]


class TestOpenAIApiMocking:
    def test_openai_chat_uses_mocked_http_client(self):
        lc = _get_llm_client()

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {
                    "choices": [{"message": {"content": '{"thought":"t","tool":"final_answer","argument":"ok"}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            out = _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert '"tool":"final_answer"' in out
        fake_client.post.assert_awaited_once()

    def test_openai_chat_without_api_key_stream_returns_fallback_chunk(self):
        lc = _get_llm_client()

        class _Cfg:
            OPENAI_API_KEY = ""
            OPENAI_MODEL = "gpt-4o-mini"
            ENABLE_TRACING = False

        client = lc.OpenAIClient(_Cfg())

        async def _collect():
            stream = await client.chat([{"role": "user", "content": "selam"}], stream=True, json_mode=True)
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)
            return chunks

        chunks = _run(_collect())
        assert len(chunks) == 1
        assert "OPENAI_API_KEY" in chunks[0]

    def test_openai_chat_http_failure_raises_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _FakeClientCM:
            async def __aenter__(self_inner):
                raise RuntimeError("socket closed")

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError):
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

    def test_openai_chat_404_maps_to_non_retryable_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 404

            @staticmethod
            def json():
                return {"error": {"message": "not found"}}

            def raise_for_status(self):
                exc = RuntimeError("404")
                exc.status_code = 404
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.status_code == 404
        assert exc_info.value.retryable is False
        fake_client.post.assert_awaited_once()

    def test_openai_chat_401_invalid_api_key_is_non_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "bad-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 401

            @staticmethod
            def json():
                return {"error": {"message": "Invalid API key"}}

            def raise_for_status(self):
                exc = RuntimeError("401")
                exc.status_code = 401
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.status_code == 401
        assert exc_info.value.retryable is False
        assert fake_client.post.await_count == 1

    def test_openai_chat_500_retries_then_raises_retryable_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 1
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 500

            @staticmethod
            def json():
                return {"error": {"message": "server error"}}

            def raise_for_status(self):
                exc = RuntimeError("500")
                exc.status_code = 500
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.status_code == 500
        assert exc_info.value.retryable is True
        assert fake_client.post.await_count == 2  # 1 ilk çağrı + 1 retry


class TestBaseClientHelpers:
    def test_inject_json_instruction_prepends_system_message(self):
        lc = _get_llm_client()

        class _DummyClient(lc.BaseLLMClient):
            def json_mode_config(self):
                return {}

            async def chat(self, messages, stream=False, json_mode=False):
                return "ok"

            async def list_models(self):
                return []

            async def is_available(self):
                return True

        client = _DummyClient(config=types.SimpleNamespace())
        messages = [{"role": "user", "content": "merhaba"}]
        out = client._inject_json_instruction(messages)
        assert out[0]["role"] == "system"
        assert "JSON" in out[0]["content"]
        assert out[1:] == messages

    def test_get_tracer_returns_none_when_tracing_disabled(self):
        lc = _get_llm_client()
        tracer = lc._get_tracer(types.SimpleNamespace(ENABLE_TRACING=False))
        assert tracer is None

    def test_fallback_stream_yields_single_message(self):
        lc = _get_llm_client()

        async def _collect():
            chunks = []
            async for item in lc._fallback_stream("fallback-message"):
                chunks.append(item)
            return chunks

        chunks = _run(_collect())
        assert chunks == ["fallback-message"]

    def test_openai_chat_429_rate_limit_is_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 429

            @staticmethod
            def json():
                return {"error": {"message": "rate limit exceeded"}}

            def raise_for_status(self):
                exc = RuntimeError("429")
                exc.status_code = 429
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is True

    def test_openai_chat_timeout_raises_retryable_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=lc.httpx.TimeoutException("request timeout"))

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.provider == "openai"


class TestLLMProviderFailureScenarios:
    def test_openai_token_limit_error_is_non_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 400

            @staticmethod
            def json():
                return {"error": {"message": "context_length_exceeded"}}

            def raise_for_status(self):
                exc = RuntimeError("400")
                exc.status_code = 400
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "uzun prompt"}], stream=False, json_mode=True))

        assert exc_info.value.status_code == 400
        assert exc_info.value.retryable is False
        assert fake_client.post.await_count == 1

    def test_openai_connect_error_is_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=lc.httpx.ConnectError("network disconnected"))

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "openai"
        assert exc_info.value.retryable is True

    def test_openai_malformed_json_content_is_wrapped_in_safe_json(self):
        lc = _get_llm_client()
        import json

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {
                    "choices": [{"message": {"content": "{broken-json"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            out = _run(client.chat([{"role": "user", "content": "çıktıyı json dön"}], stream=False, json_mode=True))

        parsed = json.loads(out)
        assert parsed["tool"] == "final_answer"
        assert parsed["argument"] == "{broken-json"

    def test_anthropic_429_rate_limit_is_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            ANTHROPIC_API_KEY = "test-key"
            ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
            ANTHROPIC_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Messages:
            async def create(self, **_kwargs):
                err = RuntimeError("rate limit")
                err.status_code = 429
                raise err

        class _FakeAsyncAnthropic:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self.messages = _Messages()

        with patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(AsyncAnthropic=_FakeAsyncAnthropic)}):
            client = lc.AnthropicClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is True


class TestOllamaApiMocking:
    def test_ollama_chat_429_rate_limit_is_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OLLAMA_URL = "http://localhost:11434"
            CODING_MODEL = "qwen2.5-coder:7b"
            OLLAMA_TIMEOUT = 20
            USE_GPU = False
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 429

            def raise_for_status(self):
                exc = RuntimeError("429 rate limit")
                exc.status_code = 429
                raise exc

            @staticmethod
            def json():
                return {"error": "too many requests"}

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OllamaClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "ollama"
        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is True

    def test_ollama_chat_timeout_is_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OLLAMA_URL = "http://localhost:11434"
            CODING_MODEL = "qwen2.5-coder:7b"
            OLLAMA_TIMEOUT = 20
            USE_GPU = False
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=lc.httpx.TimeoutException("request timeout"))

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OllamaClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "ollama"
        assert exc_info.value.retryable is True

    def test_ollama_chat_malformed_json_payload_is_wrapped_to_safe_json(self):
        lc = _get_llm_client()
        import json

        class _Cfg:
            OLLAMA_URL = "http://localhost:11434"
            CODING_MODEL = "qwen2.5-coder:7b"
            OLLAMA_TIMEOUT = 20
            USE_GPU = False
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {"message": {"content": "JSON olmayan düz metin"}}

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OllamaClient(_Cfg())
            output = _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        payload = json.loads(output)
        assert payload["tool"] == "final_answer"
        assert "JSON olmayan düz metin" in payload["argument"]

    def test_openai_chat_token_limit_error_is_non_retryable(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 2
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 413

            @staticmethod
            def json():
                return {"error": {"message": "maximum context length exceeded"}}

            def raise_for_status(self):
                exc = RuntimeError("token limit")
                exc.status_code = 413
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "uzun prompt"}], stream=False, json_mode=True))
        assert exc_info.value.status_code == 413
        assert exc_info.value.retryable is False
        assert fake_client.post.await_count == 1

    def test_openai_chat_invalid_http_json_maps_to_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                raise ValueError("invalid json payload")

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))
        assert exc_info.value.provider == "openai"
        assert exc_info.value.retryable is False

    def test_openai_chat_malformed_json_content_is_wrapped_to_final_answer(self):
        lc = _get_llm_client()
        import json

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {
                    "choices": [{"message": {"content": "{invalid json"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            out = _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        parsed = json.loads(out)
        assert parsed.get("tool") == "final_answer"

    def test_openai_chat_unexpected_choice_shape_raises_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                # Beklenmeyen içerik: message bir dict yerine string
                return {
                    "choices": [{"message": "unexpected-raw-string"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.OpenAIClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "openai"
        assert exc_info.value.retryable is False


class TestLiteLLMApiMocking:
    def test_litellm_401_invalid_token_raises_llm_api_error(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            LITELLM_GATEWAY_URL = "https://litellm.example"
            LITELLM_API_KEY = "bad-token"
            LITELLM_MODEL = "gpt-4o-mini"
            LITELLM_FALLBACK_MODELS = []
            LITELLM_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Resp:
            status_code = 401

            def raise_for_status(self):
                exc = RuntimeError("invalid token")
                exc.status_code = 401
                raise exc

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(return_value=_Resp())

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.LiteLLMClient(_Cfg())
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "litellm"
        assert "LiteLLM hata" in str(exc_info.value)
        assert fake_client.post.await_count == 1

    def test_litellm_fallback_model_succeeds_after_primary_rate_limit(self):
        lc = _get_llm_client()

        class _Cfg:
            LITELLM_GATEWAY_URL = "https://litellm.example"
            LITELLM_API_KEY = "token"
            LITELLM_MODEL = "primary-model"
            LITELLM_FALLBACK_MODELS = ["fallback-model"]
            LITELLM_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _RateLimitedResp:
            status_code = 429

            def raise_for_status(self):
                exc = RuntimeError("rate limited")
                exc.status_code = 429
                raise exc

        class _OkResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": '{"tool":"final_answer","argument":"ok"}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=[_RateLimitedResp(), _OkResp()])

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.LiteLLMClient(_Cfg())
            out = _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        assert '"argument":"ok"' in out.replace(" ", "")
        assert fake_client.post.await_count == 2
        first_model = fake_client.post.await_args_list[0].kwargs["json"]["model"]
        second_model = fake_client.post.await_args_list[1].kwargs["json"]["model"]
        assert first_model == "primary-model"
        assert second_model == "fallback-model"

    def test_litellm_timeout_on_primary_falls_back_and_malformed_json_is_wrapped(self):
        lc = _get_llm_client()
        import json

        class _Cfg:
            LITELLM_GATEWAY_URL = "https://litellm.example"
            LITELLM_API_KEY = "token"
            LITELLM_MODEL = "primary-model"
            LITELLM_FALLBACK_MODELS = ["fallback-model"]
            LITELLM_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _MalformedOkResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": "{bad json"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=[lc.httpx.TimeoutException("timeout"), _MalformedOkResp()])

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return fake_client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("core.llm_client.httpx.AsyncClient", return_value=_FakeClientCM()):
            client = lc.LiteLLMClient(_Cfg())
            out = _run(client.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=True))

        parsed = json.loads(out)
        assert parsed["tool"] == "final_answer"
        assert fake_client.post.await_count == 2


class TestGeminiAndAnthropicApiMocking:
    def test_gemini_timeout_in_stream_returns_fallback_error_chunk(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            GEMINI_API_KEY = "gem-key"
            GEMINI_MODEL = "gemini-1.5-flash"
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _ChatSession:
            async def send_message_async(self, _prompt, stream=False):
                assert stream is True
                raise asyncio.TimeoutError("gemini timeout")

        class _Model:
            def __init__(self, *args, **kwargs):
                pass

            def start_chat(self, history=None):
                return _ChatSession()

        fake_genai = types.SimpleNamespace(
            configure=lambda **kwargs: None,
            GenerativeModel=_Model,
        )
        fake_google_pkg = types.ModuleType("google")
        fake_google_pkg.generativeai = fake_genai
        monkeypatch.setitem(sys.modules, "google", fake_google_pkg)
        monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

        client = lc.GeminiClient(_Cfg())

        async def _collect():
            stream_iter = await client.chat([{"role": "user", "content": "selam"}], stream=True, json_mode=True)
            chunks = []
            async for item in stream_iter:
                chunks.append(item)
            return chunks

        chunks = _run(_collect())
        assert len(chunks) == 1
        assert "Gemini" in chunks[0]
        assert '"tool": "final_answer"' in chunks[0]

    def test_anthropic_429_raises_retryable_llm_api_error(self, monkeypatch):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            ANTHROPIC_API_KEY = "anth-key"
            ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
            ANTHROPIC_TIMEOUT = 15
            LLM_MAX_RETRIES = 1
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _RateLimitError(Exception):
            def __init__(self):
                super().__init__("rate limit")
                self.status_code = 429

        class _MessagesAPI:
            async def create(self, **kwargs):
                raise _RateLimitError()

        class _AsyncAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = _MessagesAPI()

        fake_anthropic_module = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)

        client = lc.AnthropicClient(_Cfg())
        with pytest.raises(lc.LLMAPIError) as exc_info:
            _run(client.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is True

    def test_anthropic_timeout_raises_retryable_llm_api_error(self, monkeypatch):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            ANTHROPIC_API_KEY = "anth-key"
            ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
            ANTHROPIC_TIMEOUT = 15
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _MessagesAPI:
            async def create(self, **kwargs):
                raise asyncio.TimeoutError("request timed out")

        class _AsyncAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = _MessagesAPI()

        fake_anthropic_module = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)

        client = lc.AnthropicClient(_Cfg())
        with pytest.raises(lc.LLMAPIError) as exc_info:
            _run(client.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))

        assert exc_info.value.status_code is None
        assert exc_info.value.retryable is True


class TestProviderStreamAndFormatEdgeCases:
    def test_openai_stream_retries_after_timeout_and_yields_content(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 1
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        attempts = {"count": 0}

        class _Resp:
            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                for line in [
                    "data: {bad json",
                    'data: {"choices":[{"delta":{"content":"Merhaba"}}]}',
                    "data: [DONE]",
                ]:
                    yield line

        class _StreamCM:
            async def __aenter__(self):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise lc.httpx.TimeoutException("timeout")
                return _Resp()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _AsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            def stream(self, *_args, **_kwargs):
                return _StreamCM()

            async def aclose(self):
                return None

        monkeypatch.setattr(lc.httpx, "AsyncClient", _AsyncClient)
        client = lc.OpenAIClient(_Cfg())

        async def _collect():
            chunks = []
            async for item in client._stream_openai(
                payload={"stream": True},
                headers={"Authorization": "Bearer test-key"},
                timeout=lc.httpx.Timeout(10),
                json_mode=True,
            ):
                chunks.append(item)
            return chunks

        chunks = _run(_collect())
        assert attempts["count"] == 2
        assert chunks == ["Merhaba"]

    def test_anthropic_chat_wraps_unexpected_empty_content_as_json(self, monkeypatch):
        lc = _get_llm_client()
        import json

        class _Cfg:
            ANTHROPIC_API_KEY = "anth-key"
            ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
            ANTHROPIC_TIMEOUT = 15
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _Usage:
            input_tokens = 1
            output_tokens = 1

        class _Response:
            usage = _Usage()
            # text alanı olmayan beklenmedik bloklar
            content = [types.SimpleNamespace(type="tool_use")]

        class _MessagesAPI:
            async def create(self, **_kwargs):
                return _Response()

        class _AsyncAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = _MessagesAPI()

        monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))

        client = lc.AnthropicClient(_Cfg())
        out = _run(client.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))
        parsed = json.loads(out)
        assert parsed["tool"] == "final_answer"
        assert "UYARI" in parsed["argument"]

    def test_openai_stream_line_iteration_error_returns_fallback_and_closes_resources(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o-mini"
            OPENAI_TIMEOUT = 20
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        called = {"exit": 0, "close": 0}

        class _Resp:
            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                raise RuntimeError("stream parse failed")
                yield

        class _StreamCM:
            async def __aenter__(self):
                return _Resp()

            async def __aexit__(self, exc_type, exc, tb):
                called["exit"] += 1
                return False

        class _AsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            def stream(self, *_args, **_kwargs):
                return _StreamCM()

            async def aclose(self):
                called["close"] += 1

        monkeypatch.setattr(lc.httpx, "AsyncClient", _AsyncClient)
        client = lc.OpenAIClient(_Cfg())

        async def _collect():
            out = []
            async for chunk in client._stream_openai(
                payload={"stream": True},
                headers={"Authorization": "Bearer test-key"},
                timeout=lc.httpx.Timeout(10),
                json_mode=True,
            ):
                out.append(chunk)
            return out

        chunks = _run(_collect())
        import json
        assert len(chunks) == 1
        payload = json.loads(chunks[0])
        assert "OpenAI akış hatası" in payload["argument"]
        assert called["exit"] == 1
        assert called["close"] == 1


class TestStreamMetricHelpers:
    def test_track_stream_completion_records_success(self):
        lc = _get_llm_client()
        observed = []

        async def _stream():
            yield "a"
            yield "b"

        async def _collect():
            out = []
            async for chunk in lc._track_stream_completion(
                _stream(),
                provider="openai",
                model="gpt-4o-mini",
                started_at=time.monotonic(),
            ):
                out.append(chunk)
            return out

        with patch("core.llm_client._record_llm_metric", side_effect=lambda **kwargs: observed.append(kwargs)):
            chunks = _run(_collect())

        assert chunks == ["a", "b"]
        assert len(observed) == 1
        assert observed[0]["success"] is True
        assert observed[0]["provider"] == "openai"

    def test_track_stream_completion_records_failure_and_reraises(self):
        lc = _get_llm_client()
        observed = []

        async def _broken():
            yield "ok"
            raise RuntimeError("stream exploded")

        async def _consume():
            items = []
            async for x in lc._track_stream_completion(
                _broken(),
                provider="anthropic",
                model="claude",
                started_at=time.monotonic(),
            ):
                items.append(x)
            return items

        with patch("core.llm_client._record_llm_metric", side_effect=lambda **kwargs: observed.append(kwargs)):
            import pytest
            with pytest.raises(RuntimeError, match="stream exploded"):
                _run(_consume())

        assert observed
        assert observed[0]["success"] is False
        assert "exploded" in observed[0]["error"]

    def test_record_llm_metric_forwards_current_user_id(self):
        lc = _get_llm_client()
        observed = {}

        class _Collector:
            def record(self, **kwargs):
                observed.update(kwargs)

        with (
            patch("core.llm_client.get_llm_metrics_collector", return_value=_Collector()),
            patch("core.llm_client.get_current_metrics_user_id", return_value="tenant-user-7"),
        ):
            lc._record_llm_metric(
                provider="openai",
                model="gpt-4o-mini",
                started_at=time.monotonic(),
                prompt_tokens=12,
                completion_tokens=5,
                success=True,
            )

        assert observed["user_id"] == "tenant-user-7"
        assert observed["provider"] == "openai"
        assert observed["model"] == "gpt-4o-mini"

    def test_trace_stream_metrics_sets_span_attributes_and_ends(self):
        lc = _get_llm_client()

        class _Span:
            def __init__(self):
                self.attrs = {}
                self.ended = False

            def set_attribute(self, key, value):
                self.attrs[key] = value

            def end(self):
                self.ended = True

        span = _Span()

        async def _stream():
            yield "chunk-1"
            yield "chunk-2"

        async def _collect():
            collected = []
            async for c in lc._trace_stream_metrics(_stream(), span, time.monotonic()):
                collected.append(c)
            return collected

        chunks = _run(_collect())
        assert chunks == ["chunk-1", "chunk-2"]
        assert span.ended is True
        assert "sidar.llm.total_ms" in span.attrs
        assert "sidar.llm.ttft_ms" in span.attrs


class TestRetryBackoffHttpStatusError:
    def test_http_status_error_503_is_retryable_and_exposed(self):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            LLM_MAX_RETRIES = 0
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01

        if all(hasattr(lc.httpx, attr) for attr in ("Request", "Response", "HTTPStatusError")):
            request = lc.httpx.Request("GET", "https://example.com")
            response = lc.httpx.Response(503, request=request)
            status_exc = lc.httpx.HTTPStatusError("server err", request=request, response=response)
        else:
            status_exc = RuntimeError("server err")
            status_exc.status_code = 503

        async def _operation():
            raise status_exc

        with pytest.raises(lc.LLMAPIError) as exc_info:
            _run(lc._retry_with_backoff("openai", _operation, config=_Cfg(), retry_hint="openai test"))
        assert exc_info.value.status_code == 503
        assert exc_info.value.retryable is True


class TestAnthropicInvalidApiKeyHandling:
    def test_anthropic_401_invalid_key_is_non_retryable(self, monkeypatch):
        lc = _get_llm_client()
        import pytest

        class _Cfg:
            ANTHROPIC_API_KEY = "bad-key"
            ANTHROPIC_MODEL = "claude-3-haiku-20240307"
            ANTHROPIC_TIMEOUT = 10
            LLM_MAX_RETRIES = 1
            LLM_RETRY_BASE_DELAY = 0.001
            LLM_RETRY_MAX_DELAY = 0.01
            ENABLE_TRACING = False

        class _MessagesAPI:
            async def create(self, **_kwargs):
                err = RuntimeError("invalid api key")
                err.status_code = 401
                raise err

        class _AsyncAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = _MessagesAPI()

        fake_anthropic_module = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)

        client = lc.AnthropicClient(_Cfg())
        with pytest.raises(lc.LLMAPIError) as exc_info:
            _run(client.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))

        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.status_code == 401
        assert exc_info.value.retryable is False


class TestLLMClientRoutingAndCachePaths:
    def test_chat_routing_failure_falls_back_to_primary_client(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            COST_ROUTING_TOKEN_COST_USD = 2e-6

        class _FakeCache:
            async def get(self, _prompt):
                return None

            async def set(self, _prompt, _response):
                return None

        class _PrimaryClient:
            async def chat(self, **_kwargs):
                return "primary-response"

        class _BrokenRoutedClient:
            async def chat(self, **_kwargs):
                raise RuntimeError("routed provider down")

        class _Router:
            def select(self, _messages, _provider, _model):
                return "gemini", "gemini-pro"

        monkeypatch.setattr(lc, "_SemanticCacheManager", lambda _cfg: _FakeCache())
        monkeypatch.setattr(lc, "CostAwareRouter", lambda _cfg: _Router())
        monkeypatch.setattr(lc, "OpenAIClient", lambda _cfg: _PrimaryClient())
        monkeypatch.setattr(lc, "GeminiClient", lambda _cfg: _BrokenRoutedClient())

        client = lc.LLMClient("openai", _Cfg())
        out = _run(client.chat(messages=[{"role": "user", "content": "merhaba"}], stream=False, json_mode=False))
        assert out == "primary-response"

    def test_chat_non_stream_records_cost_and_sets_semantic_cache(self, monkeypatch):
        lc = _get_llm_client()

        class _Cfg:
            COST_ROUTING_TOKEN_COST_USD = 1e-6

        state = {"set_calls": 0, "cost_calls": 0}

        class _FakeCache:
            async def get(self, _prompt):
                return None

            async def set(self, _prompt, _response):
                state["set_calls"] += 1

        class _PrimaryClient:
            async def chat(self, **_kwargs):
                return "yanit"

        class _Router:
            def select(self, _messages, provider, model):
                return provider, model

        monkeypatch.setattr(lc, "_SemanticCacheManager", lambda _cfg: _FakeCache())
        monkeypatch.setattr(lc, "CostAwareRouter", lambda _cfg: _Router())
        monkeypatch.setattr(lc, "OpenAIClient", lambda _cfg: _PrimaryClient())
        monkeypatch.setattr(lc, "record_routing_cost", lambda _value: state.__setitem__("cost_calls", state["cost_calls"] + 1))

        client = lc.LLMClient("openai", _Cfg())
        out = _run(
            client.chat(
                messages=[{"role": "user", "content": "kullanici sorusu"}],
                stream=False,
                json_mode=False,
            )
        )
        assert out == "yanit"
        assert state["set_calls"] == 1
        assert state["cost_calls"] == 1

# ===== MERGED FROM tests/test_core_llm_client_extra.py =====

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────
# Helper: heavy deps stub et ve modülü taze yükle
# ──────────────────────────────────────────────────────────────

def _stub_deps():
    """redis, opentelemetry, google.generativeai, anthropic gibi ağır bağımlılıkları stub'la."""
    # redis stub
    if "redis" not in sys.modules:
        redis_stub = types.ModuleType("redis")
        redis_asyncio = types.ModuleType("redis.asyncio")

        class _FakeRedis:
            @classmethod
            def from_url(cls, *a, **kw):
                return cls()

            async def ping(self):
                return True

            async def lrange(self, *a, **kw):
                return []

            async def hgetall(self, *a, **kw):
                return {}

            async def llen(self, *a, **kw):
                return 0

            def pipeline(self, *a, **kw):
                return _FakePipeline()

        class _FakePipeline:
            def __init__(self):
                pass

            def hset(self, *a, **kw):
                return self

            def expire(self, *a, **kw):
                return self

            def lrem(self, *a, **kw):
                return self

            def lpush(self, *a, **kw):
                return self

            def ltrim(self, *a, **kw):
                return self

            async def execute(self):
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        redis_asyncio.Redis = _FakeRedis
        redis_stub.asyncio = redis_asyncio
        sys.modules["redis"] = redis_stub
        sys.modules["redis.asyncio"] = redis_asyncio


def _get_llm_client():
    _stub_deps()
    if "core.llm_client" in sys.modules:
        del sys.modules["core.llm_client"]
    import core.llm_client as lc
    return lc


def _run(coro):
    return asyncio.run(coro)


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.OLLAMA_URL = "http://localhost:11434/api"
    cfg.CODING_MODEL = "qwen2.5-coder:7b"
    cfg.OLLAMA_TIMEOUT = 120
    cfg.USE_GPU = False
    cfg.OLLAMA_CONTEXT_MAX_CHARS = 12000
    cfg.GEMINI_API_KEY = ""
    cfg.GEMINI_MODEL = "gemini-pro"
    cfg.OPENAI_API_KEY = ""
    cfg.OPENAI_MODEL = "gpt-4o-mini"
    cfg.OPENAI_TIMEOUT = 60
    cfg.ANTHROPIC_API_KEY = ""
    cfg.ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
    cfg.ANTHROPIC_TIMEOUT = 60
    cfg.LITELLM_GATEWAY_URL = ""
    cfg.LITELLM_MODEL = ""
    cfg.LITELLM_API_KEY = ""
    cfg.LITELLM_TIMEOUT = 60
    cfg.LITELLM_FALLBACK_MODELS = []
    cfg.ENABLE_TRACING = False
    cfg.ENABLE_SEMANTIC_CACHE = False
    cfg.SEMANTIC_CACHE_THRESHOLD = 0.95
    cfg.SEMANTIC_CACHE_TTL = 3600
    cfg.SEMANTIC_CACHE_MAX_ITEMS = 500
    cfg.REDIS_URL = "redis://localhost:6379/0"
    cfg.REDIS_MAX_CONNECTIONS = 50
    cfg.LLM_MAX_RETRIES = 0
    cfg.LLM_RETRY_BASE_DELAY = 0.01
    cfg.LLM_RETRY_MAX_DELAY = 0.02
    cfg.COST_ROUTING_TOKEN_COST_USD = 2e-6
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ══════════════════════════════════════════════════════════════
# _get_tracer
# ══════════════════════════════════════════════════════════════

class Extra_TestGetTracer:
    def test_returns_none_when_tracing_disabled(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_TRACING=False)
        result = lc._get_tracer(cfg)
        assert result is None

    def test_returns_none_when_trace_module_absent(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_TRACING=True)
        orig_trace = lc.trace
        try:
            lc.trace = None
            result = lc._get_tracer(cfg)
            assert result is None
        finally:
            lc.trace = orig_trace


# ══════════════════════════════════════════════════════════════
# _trace_stream_metrics
# ══════════════════════════════════════════════════════════════

class Extra_TestTraceStreamMetrics:
    def test_yields_all_chunks_no_span(self):
        lc = _get_llm_client()

        async def _src():
            for c in ["a", "b", "c"]:
                yield c

        async def _collect():
            chunks = []
            async for c in lc._trace_stream_metrics(_src(), None, 0.0):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        assert result == ["a", "b", "c"]

    def test_with_span_sets_total_ms(self):
        lc = _get_llm_client()
        span = MagicMock()

        async def _src():
            yield "hello"
            yield "world"

        async def _collect():
            chunks = []
            async for c in lc._trace_stream_metrics(_src(), span, 0.0):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        assert result == ["hello", "world"]
        span.set_attribute.assert_called()
        span.end.assert_called()

    def test_with_span_sets_ttft_when_chunks(self):
        lc = _get_llm_client()
        span = MagicMock()

        async def _src():
            yield "first"

        async def _collect():
            chunks = []
            async for c in lc._trace_stream_metrics(_src(), span, 0.0):
                chunks.append(c)
            return chunks

        _run(_collect())
        calls = [str(c) for c in span.set_attribute.call_args_list]
        assert any("ttft_ms" in c for c in calls)


# ══════════════════════════════════════════════════════════════
# _SemanticCacheManager
# ══════════════════════════════════════════════════════════════

class Extra_TestSemanticCacheManager:
    def test_disabled_by_default_get_returns_none(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_SEMANTIC_CACHE=False)
        mgr = lc._SemanticCacheManager(cfg)
        result = _run(mgr.get("test prompt"))
        assert result is None

    def test_disabled_set_is_noop(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_SEMANTIC_CACHE=False)
        mgr = lc._SemanticCacheManager(cfg)
        _run(mgr.set("prompt", "response"))  # should not raise

    def test_cosine_similarity_identical_vectors(self):
        lc = _get_llm_client()
        cfg = _make_config()
        mgr = lc._SemanticCacheManager(cfg)
        result = mgr._cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert abs(result - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self):
        lc = _get_llm_client()
        cfg = _make_config()
        mgr = lc._SemanticCacheManager(cfg)
        result = mgr._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(result) < 1e-6

    def test_cosine_similarity_empty_returns_zero(self):
        lc = _get_llm_client()
        cfg = _make_config()
        mgr = lc._SemanticCacheManager(cfg)
        assert mgr._cosine_similarity([], [1.0]) == 0.0
        assert mgr._cosine_similarity([1.0], []) == 0.0

    def test_cosine_similarity_mismatched_len(self):
        lc = _get_llm_client()
        cfg = _make_config()
        mgr = lc._SemanticCacheManager(cfg)
        assert mgr._cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_embed_prompt_fallback_on_import_error(self):
        lc = _get_llm_client()
        cfg = _make_config()
        mgr = lc._SemanticCacheManager(cfg)
        with patch.dict(sys.modules, {"core.rag": None}):
            result = mgr._embed_prompt("hello")
        assert result == []

    def test_get_returns_none_when_empty_prompt(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_SEMANTIC_CACHE=True)
        mgr = lc._SemanticCacheManager(cfg)
        result = _run(mgr.get(""))
        assert result is None

    def test_get_redis_returns_none_when_redis_unavailable(self):
        lc = _get_llm_client()
        cfg = _make_config(ENABLE_SEMANTIC_CACHE=True, REDIS_URL="redis://invalid:9999")

        class _FailRedis:
            @classmethod
            def from_url(cls, *a, **kw):
                raise ConnectionError("refused")

        orig_redis = lc.Redis
        try:
            lc.Redis = _FailRedis
            mgr = lc._SemanticCacheManager(cfg)
            result = _run(mgr._get_redis())
            assert result is None
        finally:
            lc.Redis = orig_redis


# ══════════════════════════════════════════════════════════════
# OllamaClient
# ══════════════════════════════════════════════════════════════

class Extra_TestOllamaClient:
    def _make_fake_async_client(self, response_data):
        """Return a context-manager-compatible fake httpx.AsyncClient."""
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = response_data

        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        fake_client.get = AsyncMock(return_value=fake_resp)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        class _FakeAsyncClientCls:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return fake_client
            async def __aexit__(self2, *a):
                return False

        return _FakeAsyncClientCls, fake_client

    def test_chat_non_stream_success(self):
        lc = _get_llm_client()
        cfg = _make_config()
        FakeCls, fake_client = self._make_fake_async_client(
            {"message": {"content": '{"thought":"t","tool":"final_answer","argument":"ok"}'}}
        )
        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OllamaClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hello"}]))
        finally:
            httpx.AsyncClient = orig
        assert isinstance(result, str)

    def test_chat_json_mode_false(self):
        lc = _get_llm_client()
        cfg = _make_config()
        FakeCls, fake_client = self._make_fake_async_client(
            {"message": {"content": "plain text response"}}
        )
        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OllamaClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hi"}], json_mode=False))
        finally:
            httpx.AsyncClient = orig
        assert result == "plain text response"

    def test_list_models_returns_names(self):
        lc = _get_llm_client()
        cfg = _make_config()
        FakeCls, fake_client = self._make_fake_async_client(
            {"models": [{"name": "llama3"}, {"name": "mistral"}]}
        )
        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OllamaClient(cfg)
            result = _run(client.list_models())
        finally:
            httpx.AsyncClient = orig
        assert "llama3" in result
        assert "mistral" in result

    def test_list_models_returns_empty_on_error(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _ErrorClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def get(self2, *a, **kw):
                raise ConnectionError("offline")

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _ErrorClient
            client = lc.OllamaClient(cfg)
            result = _run(client.list_models())
        finally:
            httpx.AsyncClient = orig
        assert result == []

    def test_is_available_true(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _OkClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def get(self2, *a, **kw):
                return MagicMock()

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _OkClient
            client = lc.OllamaClient(cfg)
            result = _run(client.is_available())
        finally:
            httpx.AsyncClient = orig
        assert result is True

    def test_is_available_false_on_error(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _ErrorClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def get(self2, *a, **kw):
                raise ConnectionError("offline")

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _ErrorClient
            client = lc.OllamaClient(cfg)
            result = _run(client.is_available())
        finally:
            httpx.AsyncClient = orig
        assert result is False

    def test_chat_raises_llm_api_error_on_failure(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _ErrorClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def post(self2, *a, **kw):
                raise RuntimeError("server error")

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _ErrorClient
            client = lc.OllamaClient(cfg)
            try:
                _run(client.chat([{"role": "user", "content": "hello"}]))
                assert False, "should have raised"
            except lc.LLMAPIError as e:
                assert e.provider == "ollama"
        finally:
            httpx.AsyncClient = orig

    def test_base_url_strips_api_suffix(self):
        lc = _get_llm_client()
        cfg = _make_config(OLLAMA_URL="http://localhost:11434/api")
        client = lc.OllamaClient(cfg)
        assert client.base_url == "http://localhost:11434"

    def test_json_mode_config(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.OllamaClient(cfg)
        cfg_res = client.json_mode_config()
        assert "format" in cfg_res


# ══════════════════════════════════════════════════════════════
# GeminiClient
# ══════════════════════════════════════════════════════════════

class Extra_TestGeminiClient:
    def test_chat_missing_import_returns_error_msg(self):
        lc = _get_llm_client()
        cfg = _make_config(GEMINI_API_KEY="fake-key")
        client = lc.GeminiClient(cfg)
        with patch.dict(sys.modules, {"google.generativeai": None}):
            result = _run(client.chat([{"role": "user", "content": "hi"}]))
        assert "HATA" in result or "final_answer" in result

    def test_chat_missing_api_key_returns_error_msg(self):
        lc = _get_llm_client()
        cfg = _make_config(GEMINI_API_KEY="")
        client = lc.GeminiClient(cfg)
        # Stub google.generativeai so the import succeeds but API key check fires
        genai_stub = types.ModuleType("google.generativeai")
        genai_stub.configure = MagicMock()
        genai_stub.GenerativeModel = MagicMock()
        google_stub = types.ModuleType("google")
        google_stub.generativeai = genai_stub
        with patch.dict(sys.modules, {"google": google_stub, "google.generativeai": genai_stub}):
            result = _run(client.chat([{"role": "user", "content": "hi"}]))
        assert "GEMINI_API_KEY" in result

    def test_chat_stream_missing_key_returns_async_gen(self):
        lc = _get_llm_client()
        cfg = _make_config(GEMINI_API_KEY="")
        client = lc.GeminiClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hi"}], stream=True))
        # Should return async generator
        assert hasattr(result, "__aiter__")

    def test_json_mode_config(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.GeminiClient(cfg)
        cfg_res = client.json_mode_config()
        assert "generation_config" in cfg_res


# ══════════════════════════════════════════════════════════════
# OpenAIClient
# ══════════════════════════════════════════════════════════════

class Extra_TestOpenAIClient:
    def test_chat_missing_api_key_returns_error_msg(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="")
        client = lc.OpenAIClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hello"}]))
        assert "OPENAI_API_KEY" in result

    def test_chat_stream_missing_key_returns_async_gen(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="")
        client = lc.OpenAIClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hi"}], stream=True))
        assert hasattr(result, "__aiter__")

    def _make_fake_client_cls(self, response_data=None, raise_exc=None):
        class _FakeClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def post(self2, *a, **kw):
                if raise_exc:
                    raise raise_exc
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = response_data or {}
                return resp
        return _FakeClient

    def test_chat_success_with_mock_http(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="test-key")
        FakeCls = self._make_fake_client_cls({
            "choices": [{"message": {"content": '{"thought":"t","tool":"final_answer","argument":"ok"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OpenAIClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hello"}]))
        finally:
            httpx.AsyncClient = orig
        assert isinstance(result, str)

    def test_chat_raises_llm_api_error_on_http_failure(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="test-key")
        FakeCls = self._make_fake_client_cls(raise_exc=RuntimeError("network error"))
        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OpenAIClient(cfg)
            try:
                _run(client.chat([{"role": "user", "content": "hello"}]))
                assert False, "should have raised"
            except lc.LLMAPIError as e:
                assert e.provider == "openai"
        finally:
            httpx.AsyncClient = orig

    def test_json_mode_config_structure(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.OpenAIClient(cfg)
        cfg_res = client.json_mode_config()
        assert cfg_res.get("response_format", {}).get("type") == "json_schema"

    def test_chat_http_429_raises_retryable_llm_api_error(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="test-key", LLM_MAX_RETRIES=0)

        class _FakeClient:
            def __init__(self2, *a, **kw):
                pass

            async def __aenter__(self2):
                return self2

            async def __aexit__(self2, *a):
                return False

            async def post(self2, *a, **kw):
                err = RuntimeError("429 rate limit")
                err.status_code = 429
                raise err

        import httpx

        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _FakeClient
            client = lc.OpenAIClient(cfg)
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "hello"}]))
        finally:
            httpx.AsyncClient = orig

        assert exc_info.value.provider == "openai"
        assert exc_info.value.retryable is True
        assert exc_info.value.status_code == 429

    def test_chat_empty_content_is_wrapped_in_json_mode(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="test-key")
        FakeCls = self._make_fake_client_cls(
            {
                "choices": [{"message": {"content": ""}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0},
            }
        )
        import httpx

        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = FakeCls
            client = lc.OpenAIClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hello"}], json_mode=True))
        finally:
            httpx.AsyncClient = orig

        assert '"tool": "final_answer"' in result


class Extra_TestProviderErrorHandlingViaHttpx:
    def test_ollama_chat_malformed_json_response_raises_llm_api_error(self):
        lc = _get_llm_client()
        cfg = _make_config(LLM_MAX_RETRIES=0)

        class _BadJsonClient:
            def __init__(self2, *a, **kw):
                pass

            async def __aenter__(self2):
                return self2

            async def __aexit__(self2, *a):
                return False

            async def post(self2, *a, **kw):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.side_effect = ValueError("invalid json payload")
                return resp

        import httpx

        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _BadJsonClient
            client = lc.OllamaClient(cfg)
            with pytest.raises(lc.LLMAPIError) as exc_info:
                _run(client.chat([{"role": "user", "content": "hi"}]))
        finally:
            httpx.AsyncClient = orig

        assert exc_info.value.provider == "ollama"
        assert "invalid json payload" in str(exc_info.value)

    def test_gemini_chat_empty_text_is_json_wrapped(self):
        lc = _get_llm_client()
        cfg = _make_config(GEMINI_API_KEY="gem-key", GEMINI_MODEL="gemini-1.5-flash")
        client = lc.GeminiClient(cfg)

        class _FakeChatSession:
            async def send_message_async(self, *_args, **_kwargs):
                return types.SimpleNamespace(text="")

        class _FakeGenerativeModel:
            def __init__(self, *args, **kwargs):
                pass

            def start_chat(self, history=None):
                return _FakeChatSession()

        genai_stub = types.ModuleType("google.generativeai")
        genai_stub.configure = MagicMock()
        genai_stub.GenerativeModel = _FakeGenerativeModel
        google_stub = types.ModuleType("google")
        google_stub.generativeai = genai_stub

        with patch.dict(sys.modules, {"google": google_stub, "google.generativeai": genai_stub}):
            result = _run(client.chat([{"role": "user", "content": "soru"}], json_mode=True))

        assert '"tool": "final_answer"' in result


# ══════════════════════════════════════════════════════════════
# AnthropicClient
# ══════════════════════════════════════════════════════════════

class Extra_TestAnthropicClient:
    def test_chat_missing_api_key_returns_error_msg(self):
        lc = _get_llm_client()
        cfg = _make_config(ANTHROPIC_API_KEY="")
        client = lc.AnthropicClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hello"}]))
        assert "ANTHROPIC_API_KEY" in result

    def test_chat_missing_package_returns_error_msg(self):
        lc = _get_llm_client()
        cfg = _make_config(ANTHROPIC_API_KEY="fake-key")
        client = lc.AnthropicClient(cfg)
        with patch.dict(sys.modules, {"anthropic": None}):
            result = _run(client.chat([{"role": "user", "content": "hello"}]))
        assert "HATA" in result or "final_answer" in result

    def test_json_mode_config_returns_empty(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.AnthropicClient(cfg)
        assert client.json_mode_config() == {}

    def test_split_system_and_messages(self):
        lc = _get_llm_client()
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hello"},
        ]
        system, conv = lc.AnthropicClient._split_system_and_messages(msgs)
        assert "You are helpful" in system
        assert len(conv) == 1
        assert conv[0]["role"] == "user"

    def test_split_system_empty_content_skipped(self):
        lc = _get_llm_client()
        msgs = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "hi"},
        ]
        system, conv = lc.AnthropicClient._split_system_and_messages(msgs)
        assert system == ""
        assert len(conv) == 1

    def test_chat_stream_missing_key_returns_async_gen(self):
        lc = _get_llm_client()
        cfg = _make_config(ANTHROPIC_API_KEY="")
        client = lc.AnthropicClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hi"}], stream=True))
        assert hasattr(result, "__aiter__")

    def test_chat_success_with_mock_anthropic(self):
        lc = _get_llm_client()
        cfg = _make_config(ANTHROPIC_API_KEY="test-key")

        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        mock_response.content = [MagicMock(text='{"thought":"t","tool":"final_answer","argument":"ok"}')]

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        class _FakeAnthropic:
            def __init__(self, *a, **kw):
                pass

            @property
            def messages(self):
                return mock_client.messages

        anthropic_stub = types.ModuleType("anthropic")
        anthropic_stub.AsyncAnthropic = _FakeAnthropic
        with patch.dict(sys.modules, {"anthropic": anthropic_stub}):
            client = lc.AnthropicClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hello"}]))
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# LiteLLMClient
# ══════════════════════════════════════════════════════════════

class Extra_TestLiteLLMClient:
    def test_chat_missing_gateway_url_returns_error(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_GATEWAY_URL="")
        client = lc.LiteLLMClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hi"}]))
        assert "LITELLM_GATEWAY_URL" in result

    def test_chat_stream_missing_url_returns_async_gen(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_GATEWAY_URL="")
        client = lc.LiteLLMClient(cfg)
        result = _run(client.chat([{"role": "user", "content": "hi"}], stream=True))
        assert hasattr(result, "__aiter__")

    def test_candidate_models_deduplication(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_MODEL="gpt-4", LITELLM_FALLBACK_MODELS=["gpt-4", "gpt-3.5"])
        client = lc.LiteLLMClient(cfg)
        models = client._candidate_models(None)
        # gpt-4 should appear only once
        assert models.count("gpt-4") == 1
        assert "gpt-3.5" in models

    def test_candidate_models_with_explicit_model(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_MODEL="default-model", LITELLM_FALLBACK_MODELS=[])
        client = lc.LiteLLMClient(cfg)
        models = client._candidate_models("override-model")
        assert models[0] == "override-model"

    def test_chat_raises_on_all_models_fail(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_GATEWAY_URL="http://litellm.local", LITELLM_MODEL="gpt-4")

        class _ErrClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def post(self2, *a, **kw):
                raise RuntimeError("all down")

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _ErrClient
            client = lc.LiteLLMClient(cfg)
            try:
                _run(client.chat([{"role": "user", "content": "hi"}]))
                assert False, "should have raised"
            except lc.LLMAPIError as e:
                assert e.provider == "litellm"
        finally:
            httpx.AsyncClient = orig

    def test_json_mode_config(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LiteLLMClient(cfg)
        cfg_res = client.json_mode_config()
        assert cfg_res.get("response_format", {}).get("type") == "json_object"

    def test_chat_success(self):
        lc = _get_llm_client()
        cfg = _make_config(LITELLM_GATEWAY_URL="http://litellm.local", LITELLM_MODEL="gpt-4")
        response_data = {
            "choices": [{"message": {"content": '{"thought":"t","tool":"final_answer","argument":"ok"}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }

        class _FakeClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def post(self2, *a, **kw):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = response_data
                return resp

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _FakeClient
            client = lc.LiteLLMClient(cfg)
            result = _run(client.chat([{"role": "user", "content": "hi"}]))
        finally:
            httpx.AsyncClient = orig
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# LLMClient factory
# ══════════════════════════════════════════════════════════════

class Extra_TestLLMClientFactory:
    def test_ollama_provider_creates_ollama_client(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("ollama", cfg)
        assert isinstance(client._client, lc.OllamaClient)

    def test_gemini_provider_creates_gemini_client(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("gemini", cfg)
        assert isinstance(client._client, lc.GeminiClient)

    def test_openai_provider_creates_openai_client(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("openai", cfg)
        assert isinstance(client._client, lc.OpenAIClient)

    def test_anthropic_provider_creates_anthropic_client(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("anthropic", cfg)
        assert isinstance(client._client, lc.AnthropicClient)

    def test_litellm_provider_creates_litellm_client(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("litellm", cfg)
        assert isinstance(client._client, lc.LiteLLMClient)

    def test_unknown_provider_raises_value_error(self):
        lc = _get_llm_client()
        cfg = _make_config()
        try:
            lc.LLMClient("nonexistent", cfg)
            assert False, "should raise ValueError"
        except ValueError as e:
            assert "nonexistent" in str(e)

    def test_ollama_base_url_property(self):
        lc = _get_llm_client()
        cfg = _make_config(OLLAMA_URL="http://localhost:11434/api")
        client = lc.LLMClient("ollama", cfg)
        assert "localhost" in client._ollama_base_url

    def test_build_ollama_timeout_returns_timeout(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("ollama", cfg)
        timeout = client._build_ollama_timeout()
        assert timeout is not None

    def test_list_ollama_models_via_factory(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _FakeClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def get(self2, *a, **kw):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = {"models": [{"name": "llama3"}]}
                return resp

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _FakeClient
            client = lc.LLMClient("ollama", cfg)
            result = _run(client.list_ollama_models())
        finally:
            httpx.AsyncClient = orig
        assert "llama3" in result

    def test_list_ollama_models_returns_empty_for_non_ollama(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("openai", cfg)
        result = _run(client.list_ollama_models())
        assert result == []

    def test_is_ollama_available_via_factory(self):
        lc = _get_llm_client()
        cfg = _make_config()

        class _FakeClient:
            def __init__(self2, *a, **kw):
                pass
            async def __aenter__(self2):
                return self2
            async def __aexit__(self2, *a):
                return False
            async def get(self2, *a, **kw):
                return MagicMock()

        import httpx
        orig = httpx.AsyncClient
        try:
            httpx.AsyncClient = _FakeClient
            client = lc.LLMClient("ollama", cfg)
            result = _run(client.is_ollama_available())
        finally:
            httpx.AsyncClient = orig
        assert result is True

    def test_is_ollama_available_false_for_non_ollama(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("openai", cfg)
        result = _run(client.is_ollama_available())
        assert result is False


# ══════════════════════════════════════════════════════════════
# LLMClient._truncate_messages_for_local_model
# ══════════════════════════════════════════════════════════════

class Extra_TestTruncateMessages:
    def _get_client(self):
        lc = _get_llm_client()
        cfg = _make_config(OLLAMA_CONTEXT_MAX_CHARS=200)
        return lc.LLMClient("ollama", cfg)

    def test_short_messages_unchanged(self):
        client = self._get_client()
        msgs = [{"role": "user", "content": "hello"}]
        result = client._truncate_messages_for_local_model(msgs)
        assert result[0]["content"] == "hello"

    def test_empty_messages_unchanged(self):
        client = self._get_client()
        result = client._truncate_messages_for_local_model([])
        assert result == []

    def test_long_messages_truncated(self):
        # max_chars has a floor of 1200 in the implementation, so use large content
        lc = _get_llm_client()
        cfg = _make_config(OLLAMA_CONTEXT_MAX_CHARS=1200)
        client = lc.LLMClient("ollama", cfg)
        long_content = "x" * 5000
        msgs = [{"role": "user", "content": long_content}]
        result = client._truncate_messages_for_local_model(msgs)
        total = sum(len(m["content"]) for m in result)
        assert total <= 1200

    def test_system_message_preserved_first(self):
        lc = _get_llm_client()
        cfg = _make_config(OLLAMA_CONTEXT_MAX_CHARS=500)
        client = lc.LLMClient("ollama", cfg)
        msgs = [
            {"role": "system", "content": "sys " * 10},
            {"role": "user", "content": "user msg"},
        ]
        result = client._truncate_messages_for_local_model(msgs)
        roles = [m["role"] for m in result]
        assert "system" in roles


# ══════════════════════════════════════════════════════════════
# LLMClient.chat — DLP, cache, routing
# ══════════════════════════════════════════════════════════════

class Extra_TestLLMClientChat:
    def test_chat_with_system_prompt_prepends_message(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="")
        client = lc.LLMClient("openai", cfg)

        captured_messages = []

        async def _fake_chat(messages, model=None, temperature=0.3, stream=False, json_mode=True):
            captured_messages.extend(messages)
            return '{"thought":"t","tool":"final_answer","argument":"ok"}'

        client._client.chat = _fake_chat
        _run(client.chat([{"role": "user", "content": "hi"}], system_prompt="Be helpful"))
        roles = [m["role"] for m in captured_messages]
        assert "system" in roles

    def test_chat_stream_true_skips_cache(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("openai", cfg)

        async def _fake_stream_gen():
            yield "chunk"

        async def _fake_chat(messages, model=None, temperature=0.3, stream=False, json_mode=True):
            return _fake_stream_gen()

        client._client.chat = _fake_chat
        result = _run(client.chat([{"role": "user", "content": "hi"}], stream=True))
        assert result is not None

    def test_stream_gemini_generator_non_gemini(self):
        lc = _get_llm_client()
        cfg = _make_config()
        client = lc.LLMClient("openai", cfg)

        class _FakeChunk:
            text = "hello chunk"

        async def _fake_response_stream():
            yield _FakeChunk()

        async def _collect():
            chunks = []
            async for c in client._stream_gemini_generator(_fake_response_stream()):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        assert "hello chunk" in result

    def test_chat_cost_tracking_cloud_provider(self):
        lc = _get_llm_client()
        cfg = _make_config(OPENAI_API_KEY="fake")
        client = lc.LLMClient("openai", cfg)

        async def _fake_chat(messages, model=None, temperature=0.3, stream=False, json_mode=True):
            return '{"thought":"t","tool":"final_answer","argument":"ok"}'

        client._client.chat = _fake_chat
        # Should not raise when cost tracking runs
        result = _run(client.chat([{"role": "user", "content": "hello"}]))
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# BaseLLMClient._inject_json_instruction
# ══════════════════════════════════════════════════════════════

class Extra_TestInjectJsonInstruction:
    def test_prepends_system_when_no_system_msg(self):
        lc = _get_llm_client()
        msgs = [{"role": "user", "content": "hi"}]
        result = lc.OllamaClient._inject_json_instruction(msgs)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_appends_to_existing_system_msg(self):
        lc = _get_llm_client()
        msgs = [
            {"role": "system", "content": "Existing instruction"},
            {"role": "user", "content": "hi"},
        ]
        result = lc.OllamaClient._inject_json_instruction(msgs)
        assert result[0]["role"] == "system"
        assert "Existing instruction" in result[0]["content"]
        assert lc.SIDAR_TOOL_JSON_INSTRUCTION in result[0]["content"]

    def test_original_messages_not_mutated(self):
        lc = _get_llm_client()
        msgs = [{"role": "user", "content": "hi"}]
        original = list(msgs)
        lc.OllamaClient._inject_json_instruction(msgs)
        assert msgs == original


# ══════════════════════════════════════════════════════════════
# _retry_with_backoff
# ══════════════════════════════════════════════════════════════

class Extra_TestRetryWithBackoff:
    def test_no_retry_on_success(self):
        lc = _get_llm_client()
        cfg = _make_config()
        call_count = 0

        async def _op():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = _run(lc._retry_with_backoff("test", _op, config=cfg, retry_hint="hint"))
        assert result == "ok"
        assert call_count == 1

    def test_raises_llm_api_error_on_non_retryable(self):
        lc = _get_llm_client()
        cfg = _make_config(LLM_MAX_RETRIES=0)

        async def _op():
            raise ValueError("not retryable")

        try:
            _run(lc._retry_with_backoff("test", _op, config=cfg, retry_hint="hint"))
            assert False, "should raise"
        except lc.LLMAPIError as e:
            assert e.provider == "test"

    def test_retries_on_429(self):
        lc = _get_llm_client()
        cfg = _make_config(LLM_MAX_RETRIES=1, LLM_RETRY_BASE_DELAY=0.001, LLM_RETRY_MAX_DELAY=0.01)
        call_count = 0

        async def _op():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                err = lc.LLMAPIError("test", "rate limit", status_code=429, retryable=True)
                raise err
            return "success after retry"

        # Patch sleep to not actually wait
        with patch("asyncio.sleep", AsyncMock()):
            result = _run(lc._retry_with_backoff("test", _op, config=cfg, retry_hint="hint"))
        assert result == "success after retry"
        assert call_count == 2


# ══════════════════════════════════════════════════════════════
# _fallback_stream
# ══════════════════════════════════════════════════════════════

class Extra_TestFallbackStream:
    def test_yields_single_message(self):
        lc = _get_llm_client()

        async def _collect():
            chunks = []
            async for c in lc._fallback_stream("error msg"):
                chunks.append(c)
            return chunks

        result = _run(_collect())
        assert result == ["error msg"]


# ══════════════════════════════════════════════════════════════
# _ensure_json_text
# ══════════════════════════════════════════════════════════════

class Extra_TestEnsureJsonText:
    def test_valid_json_returned_as_is(self):
        lc = _get_llm_client()
        valid = '{"thought":"t","tool":"final_answer","argument":"ok"}'
        result = lc._ensure_json_text(valid, "test")
        assert json.loads(result) == json.loads(valid)

    def test_invalid_json_wrapped_in_schema(self):
        lc = _get_llm_client()
        result = lc._ensure_json_text("not json at all", "test")
        parsed = json.loads(result)
        assert "tool" in parsed
        assert "argument" in parsed
        assert "thought" in parsed

    def test_empty_string_wrapped_with_warning(self):
        lc = _get_llm_client()
        result = lc._ensure_json_text("", "test")
        parsed = json.loads(result)
        assert "UYARI" in parsed.get("argument", "")


# ══════════════════════════════════════════════════════════════
# _is_retryable_exception
# ══════════════════════════════════════════════════════════════

class Extra_TestIsRetryableException:
    def test_timeout_exception_is_retryable(self):
        lc = _get_llm_client()
        import httpx
        exc = httpx.TimeoutException("timeout")
        retryable, status = lc._is_retryable_exception(exc)
        assert retryable is True

    def test_connect_error_is_retryable(self):
        lc = _get_llm_client()
        import httpx
        exc = httpx.ConnectError("connect failed")
        retryable, status = lc._is_retryable_exception(exc)
        assert retryable is True

    def test_500_status_is_retryable(self):
        lc = _get_llm_client()
        exc = MagicMock()
        exc.status_code = 503
        retryable, status = lc._is_retryable_exception(exc)
        assert retryable is True
        assert status == 503

    def test_400_status_not_retryable(self):
        lc = _get_llm_client()
        exc = MagicMock()
        exc.status_code = 400
        retryable, status = lc._is_retryable_exception(exc)
        assert retryable is False

    def test_generic_exception_not_retryable(self):
        lc = _get_llm_client()
        exc = ValueError("bad value")
        retryable, status = lc._is_retryable_exception(exc)
        assert retryable is False
