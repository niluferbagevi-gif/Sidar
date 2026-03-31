"""
core/llm_client.py için ek birim testleri - kapsam artırma.
Missing lines hedefleniyor: provider chat çağrıları, stream, cache manager, LLMClient factory, vb.
"""
from __future__ import annotations

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

class TestGetTracer:
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

class TestTraceStreamMetrics:
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

class TestSemanticCacheManager:
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

class TestOllamaClient:
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

class TestGeminiClient:
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

class TestOpenAIClient:
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


# ══════════════════════════════════════════════════════════════
# AnthropicClient
# ══════════════════════════════════════════════════════════════

class TestAnthropicClient:
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

class TestLiteLLMClient:
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

class TestLLMClientFactory:
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

class TestTruncateMessages:
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

class TestLLMClientChat:
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

class TestInjectJsonInstruction:
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

class TestRetryWithBackoff:
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

class TestFallbackStream:
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

class TestEnsureJsonText:
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

class TestIsRetryableException:
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
