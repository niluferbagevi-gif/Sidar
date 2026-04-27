from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
