"""
core/llm_client.py için birim testleri.
Saf yardımcı fonksiyonlar (build_provider_json_mode_config, LLMAPIError,
_is_retryable_exception, _ensure_json_text, _extract_usage_tokens,
_cosine_similarity) ve retry mekanizmasını kapsar.
HTTP/LLM çağrıları gerektiren provider sınıfları stub'lanır.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch


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
