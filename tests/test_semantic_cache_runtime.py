import asyncio

import core.llm_client as llm


class _Cfg:
    ENABLE_SEMANTIC_CACHE = True
    SEMANTIC_CACHE_THRESHOLD = 0.9
    SEMANTIC_CACHE_TTL = 60
    SEMANTIC_CACHE_MAX_ITEMS = 10
    REDIS_URL = "redis://localhost:6379/0"
    OPENAI_API_KEY = "x"
    OPENAI_MODEL = "gpt-4o-mini"


class _FakeClient:
    def __init__(self):
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return "fresh-response"


class _FakeCache:
    def __init__(self, hit=None):
        self.hit = hit
        self.set_calls = []

    async def get(self, prompt):
        return self.hit

    async def set(self, prompt, response):
        self.set_calls.append((prompt, response))


def test_llm_client_uses_semantic_cache_hit():
    fac = llm.LLMClient("openai", _Cfg())
    client = _FakeClient()
    fac._client = client
    fac._semantic_cache = _FakeCache(hit="cached-response")

    out = asyncio.run(fac.chat(messages=[{"role": "user", "content": "Merhaba"}], stream=False))

    assert out == "cached-response"
    assert client.calls == 0


def test_llm_client_writes_semantic_cache_on_miss():
    fac = llm.LLMClient("openai", _Cfg())
    client = _FakeClient()
    cache = _FakeCache(hit=None)
    fac._client = client
    fac._semantic_cache = cache

    out = asyncio.run(fac.chat(messages=[{"role": "user", "content": "Nasılsın"}], stream=False))

    assert out == "fresh-response"
    assert client.calls == 1
    assert cache.set_calls == [("Nasılsın", "fresh-response")]