from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import core.cache.semantic_cache as semantic_cache_module
from core.cache.semantic_cache import SemanticCacheManager
from core.llm_client import LLMClient, OllamaClient


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
async def test_semantic_cache_miss_calls_llm_and_populates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
async def test_semantic_cache_get_batches_reads_into_single_pipeline(
    fake_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: get() must not issue one sequential hgetall await per

    cached item (N Redis round-trips for N items); it should batch all reads
    for the candidate keys into a single pipelined round-trip instead.
    """
    manager = SemanticCacheManager(_cfg())
    manager._get_redis = AsyncMock(return_value=fake_redis)

    embeddings = {
        "prompt one": [1.0, 0.0, 0.0],
        "prompt two": [0.9, 0.1, 0.0],
        "prompt three": [0.8, 0.2, 0.0],
        "query": [1.0, 0.0, 0.0],
    }
    monkeypatch.setattr(manager, "_embed_prompt", lambda prompt: embeddings.get(prompt, []))

    for prompt in ("prompt one", "prompt two", "prompt three"):
        await manager.set(prompt, f"{prompt}-answer")

    direct_hgetall_calls = {"count": 0}
    original_hgetall = type(fake_redis).hgetall

    async def _counting_hgetall(self, *args, **kwargs):
        direct_hgetall_calls["count"] += 1
        return await original_hgetall(self, *args, **kwargs)

    monkeypatch.setattr(type(fake_redis), "hgetall", _counting_hgetall)

    pipeline_execute_calls = {"count": 0}
    original_pipeline = fake_redis.pipeline

    def _counting_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        original_execute = pipe.execute

        async def _counting_execute(*e_args, **e_kwargs):
            pipeline_execute_calls["count"] += 1
            return await original_execute(*e_args, **e_kwargs)

        pipe.execute = _counting_execute
        return pipe

    monkeypatch.setattr(fake_redis, "pipeline", _counting_pipeline)

    hit = await manager.get("query")

    assert hit == "prompt one-answer"
    assert direct_hgetall_calls["count"] == 0
    assert pipeline_execute_calls["count"] == 1


class _MinimalFakePipeline:
    """Lightweight stand-in for a Redis pipeline, avoiding a fakeredis dependency."""

    def __init__(self, client: _MinimalFakeRedis) -> None:
        self.client = client
        self.commands: list[tuple[object, ...]] = []

    def hgetall(self, key: str) -> _MinimalFakePipeline:
        self.commands.append(("hgetall", key))
        return self

    def hset(self, key: str, mapping: dict[str, str]) -> _MinimalFakePipeline:
        self.commands.append(("hset", key, mapping))
        return self

    def expire(self, key: str, ttl: int) -> _MinimalFakePipeline:
        self.commands.append(("expire", key, ttl))
        return self

    def lrem(self, key: str, count: int, value: str) -> _MinimalFakePipeline:
        self.commands.append(("lrem", key, count, value))
        return self

    def lpush(self, key: str, value: str) -> _MinimalFakePipeline:
        self.commands.append(("lpush", key, value))
        return self

    def ltrim(self, key: str, start: int, end: int) -> _MinimalFakePipeline:
        self.commands.append(("ltrim", key, start, end))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for cmd in self.commands:
            name = cmd[0]
            if name == "hgetall":
                results.append(dict(self.client.hashes.get(cmd[1], {})))
            elif name == "hset":
                self.client.hashes.setdefault(cmd[1], {}).update(cmd[2])
                results.append(True)
            elif name == "expire":
                results.append(True)
            elif name == "lrem":
                _, key, count, value = cmd
                lst = self.client.lists.setdefault(key, [])
                removed = 0
                while value in lst:
                    lst.remove(value)
                    removed += 1
                results.append(removed)
            elif name == "lpush":
                _, key, value = cmd
                self.client.lists.setdefault(key, []).insert(0, value)
                results.append(len(self.client.lists[key]))
            elif name == "ltrim":
                _, key, start, end = cmd
                lst = self.client.lists.setdefault(key, [])
                self.client.lists[key] = lst[start : end + 1] if end != -1 else lst[start:]
                results.append(True)
        return results

    async def __aenter__(self) -> _MinimalFakePipeline:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _MinimalFakeRedis:
    """Lightweight stand-in for an async Redis client, avoiding a fakeredis dependency."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self.lists.get(key, [])
        return lst[start:] if end == -1 else lst[start : end + 1]

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def pipeline(self, transaction: bool = True) -> _MinimalFakePipeline:
        return _MinimalFakePipeline(self)


@pytest.mark.asyncio
async def test_semantic_cache_get_and_set_offload_embed_prompt_to_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: _embed_prompt (which may run a real, CPU-bound

    sentence-transformers model) must be offloaded via asyncio.to_thread in
    both get() and set(), matching how core/rag/__init__.py already offloads
    its own embedding/search work, instead of blocking the event loop.
    """
    manager = SemanticCacheManager(_cfg())
    fake_redis = _MinimalFakeRedis()
    manager._get_redis = AsyncMock(return_value=fake_redis)

    embed_call_threads: list[int] = []
    event_loop_thread = threading.get_ident()

    def _tracking_embed(prompt: str) -> list[float]:
        embed_call_threads.append(threading.get_ident())
        return {"cached prompt": [1.0, 0.0, 0.0], "similar prompt": [0.99, 0.01, 0.0]}.get(
            prompt, []
        )

    manager._embed_prompt = _tracking_embed

    await manager.set("cached prompt", "cached-answer")
    hit = await manager.get("similar prompt")

    assert hit == "cached-answer"
    assert len(embed_call_threads) == 2
    assert all(
        thread_id != event_loop_thread for thread_id in embed_call_threads
    ), "get()/set() must run _embed_prompt off the event loop thread via asyncio.to_thread"


@pytest.mark.asyncio
async def test_get_redis_records_error_and_opens_circuit_on_ping_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
async def test_get_redis_records_error_and_opens_circuit_on_from_url_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            raise AssertionError(
                "Redis.from_url should not be called when circuit opens inside lock"
            )

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


@pytest.mark.asyncio
async def test_get_redis_returns_existing_client_initialized_inside_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SemanticCacheManager(_cfg())
    redis_client = object()

    class _InjectRedisLock:
        async def __aenter__(self):
            manager._redis = redis_client
            return self

        async def __aexit__(self, *_args):
            return False

    class _ShouldNotInitRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            raise AssertionError(
                "Redis.from_url should not run when redis client already exists inside lock"
            )

    monkeypatch.setattr(manager, "_redis_init_lock", _InjectRedisLock())
    monkeypatch.setattr(semantic_cache_module, "Redis", _ShouldNotInitRedis)

    redis = await manager._get_redis()

    assert redis is redis_client


@pytest.mark.asyncio
async def test_get_redis_handles_connection_refused_with_invalid_redis_url() -> None:
    if semantic_cache_module.Redis is None:
        pytest.skip("redis.asyncio mevcut değil")

    cfg = _cfg(
        REDIS_URL="redis://127.0.0.1:1/0",
        SEMANTIC_CACHE_REDIS_PING_TIMEOUT=0.2,
        SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD=1,
    )
    manager = SemanticCacheManager(cfg)

    redis = await manager._get_redis()

    assert redis is None
    assert manager._redis_failures == 1
    assert manager._redis_circuit_open_until > 0.0
