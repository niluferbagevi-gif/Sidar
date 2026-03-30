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
        assert exc_info.value.retryable is True

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

        request = lc.httpx.Request("GET", "https://example.com")
        response = lc.httpx.Response(503, request=request)
        status_exc = lc.httpx.HTTPStatusError("server err", request=request, response=response)

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
