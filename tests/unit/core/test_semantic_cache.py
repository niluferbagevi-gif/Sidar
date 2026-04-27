from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import core.cache.semantic_cache as semantic_cache_module
from core.llm_client import LLMClient, OllamaClient
from core.cache.semantic_cache import SemanticCacheManager


def _cfg(**overrides: object) -> SimpleNamespace:
    base = {
        "ENABLE_COST_ROUTING": False,
        "ENABLE_SEMANTIC_CACHE": True,
        "SEMANTIC_CACHE_THRESHOLD": 0.90,
        "SEMANTIC_CACHE_TTL": 3600,
        "SEMANTIC_CACHE_MAX_ITEMS": 100,
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_MAX_CONNECTIONS": 10,
        "OLLAMA_URL": "http://localhost:11434",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_semantic_cache_hit_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    cache_get = AsyncMock(return_value="cached-response")
    cache_set = AsyncMock()
    llm_chat = AsyncMock(return_value="llm-response")

    monkeypatch.setattr(SemanticCacheManager, "get", cache_get)
    monkeypatch.setattr(SemanticCacheManager, "set", cache_set)
    monkeypatch.setattr(OllamaClient, "chat", llm_chat)

    client = LLMClient("ollama", _cfg())

    result = await client.chat([{"role": "user", "content": "cache me"}], stream=False)

    assert result == "cached-response"
    llm_chat.assert_not_called()
    cache_set.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_cache_miss_calls_llm_and_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache_get = AsyncMock(return_value=None)
    cache_set = AsyncMock()
    llm_chat = AsyncMock(return_value="llm-response")

    monkeypatch.setattr(SemanticCacheManager, "get", cache_get)
    monkeypatch.setattr(SemanticCacheManager, "set", cache_set)
    monkeypatch.setattr(OllamaClient, "chat", llm_chat)

    client = LLMClient("ollama", _cfg())

    result = await client.chat([{"role": "user", "content": "new prompt"}], stream=False)

    assert result == "llm-response"
    llm_chat.assert_awaited_once()
    cache_set.assert_awaited_once_with("new prompt", "llm-response")


@pytest.mark.asyncio
async def test_semantic_cache_manager_hit_and_miss_with_fake_redis(
    fake_redis,
    frozen_time,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SemanticCacheManager(_cfg())
    manager._get_redis = AsyncMock(return_value=fake_redis)

    embeddings = {
        "cached prompt": [1.0, 0.0, 0.0],
        "similar prompt": [0.99, 0.01, 0.0],
        "different prompt": [0.0, 1.0, 0.0],
    }
    monkeypatch.setattr(manager, "_embed_prompt", lambda prompt: embeddings.get(prompt, []))

    await manager.set("cached prompt", "cached-answer")

    hit = await manager.get("similar prompt")
    assert hit == "cached-answer"

    frozen_time.move_to("2026-04-01 12:10:00")
    miss = await manager.get("different prompt")
    assert miss is None


@pytest.mark.asyncio
async def test_get_redis_records_error_and_opens_circuit_on_ping_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD=1)
    manager = SemanticCacheManager(cfg)

    class _FailingRedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            client = AsyncMock()
            client.ping = AsyncMock(side_effect=TimeoutError("redis ping timeout"))
            return client

    errors = {"count": 0}
    monkeypatch.setattr(semantic_cache_module, "Redis", _FailingRedisFactory)
    monkeypatch.setattr(
        semantic_cache_module,
        "record_cache_redis_error",
        lambda: errors.__setitem__("count", errors["count"] + 1),
    )

    redis = await manager._get_redis()

    assert redis is None
    assert errors["count"] == 1
    assert manager._redis_failures == 1
    assert manager._redis_circuit_open_until > 0.0


@pytest.mark.asyncio
async def test_get_redis_records_error_and_opens_circuit_on_from_url_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD=1)
    manager = SemanticCacheManager(cfg)

    class _FailingRedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    errors = {"count": 0}
    monkeypatch.setattr(semantic_cache_module, "Redis", _FailingRedisFactory)
    monkeypatch.setattr(
        semantic_cache_module,
        "record_cache_redis_error",
        lambda: errors.__setitem__("count", errors["count"] + 1),
    )

    redis = await manager._get_redis()

    assert redis is None
    assert errors["count"] == 1
    assert manager._redis_failures == 1
    assert manager._redis_circuit_open_until > 0.0


def test_embed_prompt_returns_empty_vector_when_embedding_fn_raises() -> None:
    def _failing_embedding(*_args, **_kwargs):
        raise ValueError("Embedding model down")

    manager = SemanticCacheManager(_cfg(), embedding_fn=_failing_embedding)

    assert manager._embed_prompt("prompt") == []


@pytest.mark.asyncio
async def test_get_redis_returns_none_when_circuit_opens_after_waiting_for_init_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SemanticCacheManager(_cfg())
    manager._redis_circuit_open_until = 0.0

    class _FlipCircuitLock:
        async def __aenter__(self):
            manager._redis_circuit_open_until = time.monotonic() + 30.0
            return self

        async def __aexit__(self, *_args):
            return False

    class _ShouldNotInitRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            raise AssertionError("Redis.from_url should not be called when circuit opens inside lock")

    skips = {"count": 0}
    circuit_bypasses = {"count": 0}
    monkeypatch.setattr(manager, "_redis_init_lock", _FlipCircuitLock())
    monkeypatch.setattr(semantic_cache_module, "Redis", _ShouldNotInitRedis)
    monkeypatch.setattr(
        semantic_cache_module,
        "record_cache_skip",
        lambda: skips.__setitem__("count", skips["count"] + 1),
    )
    monkeypatch.setattr(
        semantic_cache_module,
        "record_cache_circuit_open_bypass",
        lambda: circuit_bypasses.__setitem__("count", circuit_bypasses["count"] + 1),
    )

    redis = await manager._get_redis()

    assert redis is None
    assert skips["count"] == 1
    assert circuit_bypasses["count"] == 1
