"""
Coverage tests for core/llm_client.py missing lines:
  23-24: Redis import handling
  225-238: SemanticCache._get_redis (connected, not connected)
  242-249: _cosine_similarity
  252-260: _embed_prompt
  267-298: SemanticCache.get (with keys, empty, exception)
  305-325: SemanticCache.set
  784: OpenAI streaming
  958-991: _stream_openai_compatible
"""
from __future__ import annotations

import asyncio
import importlib
import json
import math
import sys
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _ensure_real_llm_client():
    """Ensure core.llm_client in sys.modules is the real module, not a web_server stub."""
    # The web_server_runtime tests stub core.llm_client and core.llm_metrics.
    # If stubbed, pop both and re-import the real modules.
    metrics_mod = sys.modules.get("core.llm_metrics")
    if metrics_mod is not None and not hasattr(metrics_mod, "get_current_metrics_user_id"):
        sys.modules.pop("core.llm_metrics", None)
        sys.modules.pop("core.llm_client", None)
        import core.llm_metrics  # noqa: F401
        import core.llm_client  # noqa: F401
    else:
        llm_mod = sys.modules.get("core.llm_client")
        if llm_mod is not None and not hasattr(llm_mod, "_SemanticCacheManager"):
            sys.modules.pop("core.llm_client", None)
            import core.llm_client  # noqa: F401
    yield


# ── _cosine_similarity ────────────────────────────────────────────────────────

def test_cosine_similarity_basic():
    """Lines 242-249: cosine similarity of identical vectors is 1.0."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    a = [1.0, 0.0, 0.0]
    sim = cache._cosine_similarity(a, a)
    assert abs(sim - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    """Lines 242-249: cosine similarity of orthogonal vectors is 0.0."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    sim = cache._cosine_similarity([1.0, 0.0], [0.0, 1.0])
    assert abs(sim) < 1e-6


def test_cosine_similarity_empty():
    """Line 242: empty vectors return 0.0."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    assert cache._cosine_similarity([], []) == 0.0


def test_cosine_similarity_zero_norm():
    """Lines 247-248: zero norm vectors return 0.0."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    sim = cache._cosine_similarity([0.0, 0.0], [0.0, 0.0])
    assert sim == 0.0


# ── _embed_prompt ─────────────────────────────────────────────────────────────

def test_embed_prompt_returns_empty_on_exception():
    """Lines 252-260: _embed_prompt returns [] when embedding fails."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    # Test the fallback path directly (no pre-patching needed)

    # Test the fallback path directly
    with patch("core.rag.embed_texts_for_semantic_cache", side_effect=Exception("fail")):
        result = cache._embed_prompt("test prompt")
    assert result == []


# ── SemanticCache._get_redis ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_redis_when_disabled():
    """Lines 223-224: _get_redis returns None when cache disabled."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = False
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    result = await cache._get_redis()
    assert result is None


@pytest.mark.asyncio
async def test_get_redis_already_connected():
    """Lines 225-226: _get_redis returns existing connection."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    mock_redis = MagicMock()
    cache._redis = mock_redis

    result = await cache._get_redis()
    assert result is mock_redis


@pytest.mark.asyncio
async def test_get_redis_connection_fails():
    """Lines 235-238: _get_redis returns None on connection failure."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    with patch("core.llm_client.Redis") as MockRedis:
        mock_instance = AsyncMock()
        mock_instance.ping = AsyncMock(side_effect=ConnectionError("no redis"))
        MockRedis.from_url.return_value = mock_instance
        result = await cache._get_redis()
    assert result is None


# ── SemanticCache.get ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_cache_get_no_redis():
    """Lines 263-265: get returns None when redis unavailable."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = False
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    result = await cache.get("test prompt")
    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_get_empty_keys():
    """Lines 272-274: get returns None when no keys in index."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=[0.1, 0.2, 0.3]):
            result = await cache.get("test prompt")
    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_get_with_hit():
    """Lines 276-293: get returns cached response when similarity >= threshold."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.5
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    cache.threshold = 0.5

    embedding = [1.0, 0.0, 0.0]
    cached_response = "This is the cached answer"
    cache_key = "sidar:semantic_cache:item:abc123"
    payload_data = {
        "embedding": json.dumps(embedding),
        "response": cached_response,
    }

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[cache_key])
    mock_redis.hgetall = AsyncMock(return_value=payload_data)

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=embedding):
            result = await cache.get("test prompt")

    assert result == cached_response


@pytest.mark.asyncio
async def test_semantic_cache_get_miss():
    """Line 294: cache miss returns None."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.99
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    cache.threshold = 0.99

    embedding = [1.0, 0.0, 0.0]
    other_embedding = [0.0, 1.0, 0.0]  # orthogonal, similarity=0
    cache_key = "sidar:semantic_cache:item:abc"

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[cache_key])
    mock_redis.hgetall = AsyncMock(return_value={
        "embedding": json.dumps(other_embedding),
        "response": "cached",
    })

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=embedding):
            result = await cache.get("test prompt")

    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_get_exception():
    """Lines 296-298: exception during get returns None."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(side_effect=Exception("redis error"))

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=[0.1, 0.2]):
            result = await cache.get("test prompt")

    assert result is None


@pytest.mark.asyncio
async def test_semantic_cache_get_no_embedding():
    """Lines 267-269: get returns None when _embed_prompt returns empty."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    mock_redis = AsyncMock()

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=[]):
            result = await cache.get("test prompt")

    assert result is None


# ── SemanticCache.set ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_cache_set_no_redis():
    """Lines 300-302: set does nothing when redis unavailable."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = False
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    # Should not raise
    await cache.set("prompt", "response")


@pytest.mark.asyncio
async def test_semantic_cache_set_success():
    """Lines 305-323: set writes to redis pipeline."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())
    embedding = [0.1, 0.2, 0.3]

    mock_pipe = AsyncMock()
    mock_pipe.hset = AsyncMock()
    mock_pipe.expire = AsyncMock()
    mock_pipe.lrem = AsyncMock()
    mock_pipe.lpush = AsyncMock()
    mock_pipe.ltrim = AsyncMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True, 0, 1, None])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=embedding):
            await cache.set("my prompt", "my response")

    mock_pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_semantic_cache_set_exception():
    """Lines 324-325: exception during set is swallowed."""
    from core.llm_client import _SemanticCacheManager as SemanticCache

    class _Cfg:
        ENABLE_SEMANTIC_CACHE = True
        REDIS_URL = "redis://localhost:6379/0"
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    cache = SemanticCache(config=_Cfg())

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(side_effect=Exception("pipeline error"))

    with patch.object(cache, "_get_redis", return_value=mock_redis):
        with patch.object(cache, "_embed_prompt", return_value=[0.1, 0.2]):
            # Should not raise
            await cache.set("prompt", "response")


# ── _stream_openai_compatible (lines 958-991) ─────────────────────────────────

@pytest.mark.asyncio
async def test_stream_openai_compatible_yields_content():
    """Lines 958-991: _stream_openai_compatible yields text chunks."""
    from core.llm_client import OpenAIClient

    class _Cfg:
        OPENAI_API_KEY = "test-key"
        OPENAI_MODEL = "gpt-4"
        LITELLM_GATEWAY_URL = "http://localhost:4000"
        LITELLM_MODEL = "gpt-4"
        LLM_TIMEOUT = 30
        LLM_MAX_RETRIES = 1
        LLM_RETRY_DELAY = 0
        ENABLE_SEMANTIC_CACHE = False
        REDIS_URL = ""
        SEMANTIC_CACHE_THRESHOLD = 0.95
        SEMANTIC_CACHE_TTL = 3600
        SEMANTIC_CACHE_MAX_ITEMS = 500

    # We test LiteLLMClient._stream_openai_compatible instead
    from core.llm_client import LiteLLMClient

    cfg = _Cfg()
    client = LiteLLMClient(config=cfg)

    sse_lines = [
        b'data: {"choices": [{"delta": {"content": "hello"}}]}',
        b'data: {"choices": [{"delta": {"content": " world"}}]}',
        b'data: [DONE]',
    ]

    async def _mock_aiter_lines():
        for line in sse_lines:
            yield line.decode()

    mock_resp = MagicMock()
    mock_resp.aiter_lines = _mock_aiter_lines
    mock_resp.raise_for_status = MagicMock()

    mock_stream_cm = AsyncMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

    mock_http_client = AsyncMock()
    mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
    mock_http_client.aclose = AsyncMock()

    import httpx

    with patch("httpx.AsyncClient") as MockClient:
        MockClient.return_value = mock_http_client
        with patch("core.llm_client._retry_with_backoff") as mock_retry:
            mock_retry.return_value = (mock_http_client, mock_stream_cm, mock_resp)
            chunks = []
            async for chunk in client._stream_openai_compatible(
                endpoint="http://localhost:4000/v1/chat/completions",
                payload={"messages": []},
                headers={},
                timeout=httpx.Timeout(30),
                json_mode=False,
            ):
                chunks.append(chunk)

    assert "hello" in chunks


@pytest.mark.asyncio
async def test_stream_openai_compatible_exception():
    """Lines 984-991: exception in _stream_openai_compatible yields error message."""
    from core.llm_client import LiteLLMClient
    import httpx

    class _Cfg:
        OPENAI_API_KEY = "test-key"
        OPENAI_MODEL = "gpt-4"
        LITELLM_GATEWAY_URL = "http://localhost:4000"
        LITELLM_MODEL = "gpt-4"
        LLM_TIMEOUT = 30
        LLM_MAX_RETRIES = 1
        LLM_RETRY_DELAY = 0
        ENABLE_SEMANTIC_CACHE = False

    client = LiteLLMClient(config=_Cfg())

    with patch("core.llm_client._retry_with_backoff", side_effect=Exception("stream error")):
        chunks = []
        async for chunk in client._stream_openai_compatible(
            endpoint="http://localhost:4000/v1/chat/completions",
            payload={},
            headers={},
            timeout=httpx.Timeout(30),
            json_mode=False,
        ):
            chunks.append(chunk)

    assert any("HATA" in c or "stream error" in c for c in chunks)
