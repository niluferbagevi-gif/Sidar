from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from types import SimpleNamespace
import types

import pytest

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.Timeout = object
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

import core.llm_client as llm


class _DummyPipe:
    def __init__(self, redis) -> None:
        self.redis = redis

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def hset(self, key, mapping):
        self.redis.hashes[key] = dict(mapping)

    def expire(self, _key, _ttl):
        return None

    def lrem(self, _idx_key, _count, key):
        self.redis.index = [k for k in self.redis.index if k != key]

    def lpush(self, _idx_key, key):
        self.redis.index.insert(0, key)

    def ltrim(self, _idx_key, start, end):
        self.redis.index = self.redis.index[start : end + 1]

    async def execute(self):
        return None


class _FakeRedis:
    def __init__(self) -> None:
        self.index: list[str] = []
        self.hashes: dict[str, dict[str, str]] = {}

    async def ping(self):
        return True

    async def lrange(self, _key, start, end):
        end_idx = None if end == -1 else end + 1
        return self.index[start:end_idx]

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def llen(self, _key):
        return len(self.index)

    def pipeline(self, transaction=True):
        return _DummyPipe(self)


def test_semantic_cache_get_hit_and_miss_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True, SEMANTIC_CACHE_THRESHOLD=0.80)
    cache = llm._SemanticCacheManager(cfg)
    fake = _FakeRedis()
    fake.index = ["k1", "k2"]
    fake.hashes = {
        "k1": {"embedding": json.dumps([1.0, 0.0]), "response": "A"},
        "k2": {"embedding": json.dumps([0.2, 1.0]), "response": "B"},
    }

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr(cache, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [1.0, 0.0])

    assert asyncio.run(cache.get("prompt")) == "A"

    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [0.0, 1.0])
    cache.threshold = 0.999999
    assert asyncio.run(cache.get("prompt")) is None


def test_semantic_cache_set_records_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True, SEMANTIC_CACHE_MAX_ITEMS=1, SEMANTIC_CACHE_TTL=30)
    cache = llm._SemanticCacheManager(cfg)
    fake = _FakeRedis()
    fake.index = ["old-key"]

    async def _fake_get_redis():
        return fake

    evictions: list[int] = []
    monkeypatch.setattr(cache, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [0.1, 0.2, 0.3])
    monkeypatch.setattr(llm, "record_cache_eviction", lambda: evictions.append(1))

    asyncio.run(cache.set("new prompt", "new response"))

    assert len(fake.index) == 1
    assert fake.hashes
    assert evictions == [1]


def test_semantic_cache_handles_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True)
    cache = llm._SemanticCacheManager(cfg)

    class _BrokenRedis:
        async def lrange(self, *_args, **_kwargs):
            raise RuntimeError("redis down")

    async def _fake_get_redis():
        return _BrokenRedis()

    errors: list[int] = []
    monkeypatch.setattr(cache, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [1.0])
    monkeypatch.setattr(llm, "record_cache_redis_error", lambda: errors.append(1))

    assert asyncio.run(cache.get("prompt")) is None
    assert errors == [1]


def test_llm_client_constructor_and_helpers() -> None:
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=15)

    with pytest.raises(ValueError):
        llm.LLMClient("unknown", cfg)

    c = llm.LLMClient("ollama", cfg)
    assert c._ollama_base_url == "http://localhost:11434"
    llm.httpx.Timeout = lambda *_args, **_kwargs: {"ok": True}  # type: ignore[assignment]
    assert c._build_ollama_timeout() == {"ok": True}


def test_truncate_messages_for_local_model_keeps_recent_and_system() -> None:
    cfg = SimpleNamespace(OLLAMA_CONTEXT_MAX_CHARS=30)
    client = llm.LLMClient("ollama", cfg)

    messages = [
        {"role": "system", "content": "S" * 30},
        {"role": "user", "content": "U" * 30},
        {"role": "assistant", "content": "A" * 30},
    ]

    truncated = client._truncate_messages_for_local_model(messages)

    assert truncated[-1]["role"] == "assistant"
    assert len("".join(m["content"] for m in truncated)) <= 400  # guarded lower-bound behavior


def test_llm_client_chat_stream_records_skip_and_fallback_route(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(COST_ROUTING_TOKEN_COST_USD=2e-6)
    client = llm.LLMClient("openai", cfg)

    class _FakeInnerClient:
        async def chat(self, **_kwargs):
            async def _gen():
                yield "chunk"

            return _gen()

    calls = {"skip": 0}
    client._client = _FakeInnerClient()
    client._router.select = lambda _messages, provider, model: (provider, model)
    monkeypatch.setattr(llm, "record_cache_skip", lambda: calls.__setitem__("skip", calls["skip"] + 1))
    monkeypatch.setattr(llm, "_dlp_mask_messages", lambda msgs: msgs)

    async def _consume():
        stream = await client.chat(messages=[{"role": "user", "content": "hello"}], stream=True)
        return [c async for c in stream]

    chunks = asyncio.run(_consume())
    assert chunks == ["chunk"]
    assert calls["skip"] == 1


def test_llm_client_chat_uses_cache_hit_without_calling_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(COST_ROUTING_TOKEN_COST_USD=2e-6)
    client = llm.LLMClient("openai", cfg)

    class _FakeSemanticCache:
        async def get(self, _prompt: str):
            return '{"tool":"final_answer","argument":"cached"}'

        async def set(self, _prompt: str, _resp: str):
            raise AssertionError("set should not be called when cache hits")

    class _FailClient:
        async def chat(self, **_kwargs):
            raise AssertionError("provider should not be called on cache hit")

    client._semantic_cache = _FakeSemanticCache()
    client._client = _FailClient()
    client._router.select = lambda _messages, provider, model: (provider, model)
    monkeypatch.setattr(llm, "_dlp_mask_messages", lambda msgs: msgs)

    result = asyncio.run(client.chat(messages=[{"role": "user", "content": "find me"}], stream=False))
    assert json.loads(result)["argument"] == "cached"
