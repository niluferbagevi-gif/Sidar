import asyncio
import builtins
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_llm_client_runtime import _collect, _load_llm_client_module


@pytest.fixture
def llm_mod():
    return _load_llm_client_module()


def test_module_sets_redis_none_when_import_fails(monkeypatch):
    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis.asyncio":
            raise ImportError("redis unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    sys.modules["httpx"] = types.SimpleNamespace(Timeout=lambda *a, **k: None, ConnectError=Exception, AsyncClient=None)
    path = Path("core/llm_client.py")
    spec = importlib.util.spec_from_file_location("llm_client_no_redis", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    assert module.Redis is None


def test_semantic_cache_get_set_and_helper_branches(llm_mod, monkeypatch):
    cfg = SimpleNamespace(
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.5,
        SEMANTIC_CACHE_TTL=30,
        SEMANTIC_CACHE_MAX_ITEMS=5,
        REDIS_URL="redis://unused",
    )
    mgr = llm_mod._SemanticCacheManager(cfg)
    monkeypatch.setattr(llm_mod, "Redis", type("_DummyRedis", (), {}))

    # _cosine_similarity guard branches
    assert mgr._cosine_similarity([], [1.0]) == 0.0
    assert mgr._cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    class _Pipe:
        def __init__(self):
            self.ops = []
            self.executed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def hset(self, key, mapping):
            self.ops.append(("hset", key, mapping))

        def expire(self, key, ttl):
            self.ops.append(("expire", key, ttl))

        def lrem(self, idx_key, zero, key):
            self.ops.append(("lrem", idx_key, zero, key))

        def lpush(self, idx_key, key):
            self.ops.append(("lpush", idx_key, key))

        def ltrim(self, idx_key, start, end):
            self.ops.append(("ltrim", idx_key, start, end))

        async def execute(self):
            self.executed = True

    class _Redis:
        def __init__(self):
            self.pipe = _Pipe()

        async def lrange(self, key, _start, _end):
            return ["k1", "k2", "k3"]

        async def hgetall(self, key):
            if key == "k1":
                return {"embedding": "bad-json", "response": "ignore"}
            if key == "k2":
                return {"embedding": "[1,1]", "response": "hit"}
            return {}

        def pipeline(self, transaction=True):
            return self.pipe

    redis = _Redis()
    mgr._redis = redis
    monkeypatch.setattr(mgr, "_embed_prompt", lambda _p: [1.0, 1.0])

    # _get_redis cached branch
    assert asyncio.run(mgr._get_redis()) is redis

    # get() should skip bad json, compare sims and return hit
    assert asyncio.run(mgr.get("prompt")) == "hit"

    # set() writes into pipeline
    asyncio.run(mgr.set("prompt", "resp"))
    assert redis.pipe.executed is True

    # get() exception branch
    async def _boom(*_a, **_k):
        raise RuntimeError("boom")

    redis.lrange = _boom
    assert asyncio.run(mgr.get("prompt")) is None


def test_semantic_cache_embed_and_redis_connection_failures(llm_mod, monkeypatch):
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True, REDIS_URL="redis://bad")
    mgr = llm_mod._SemanticCacheManager(cfg)
    monkeypatch.setattr(llm_mod, "Redis", type("_DummyRedis", (), {}))

    class _RedisCls:
        @staticmethod
        def from_url(*args, **kwargs):
            raise RuntimeError("no redis")

    monkeypatch.setattr(llm_mod, "Redis", _RedisCls)
    assert asyncio.run(mgr._get_redis()) is None

    # _embed_prompt except branch
    fake_rag = types.SimpleNamespace(embed_texts_for_semantic_cache=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("emb")))
    monkeypatch.setitem(sys.modules, "core.rag", fake_rag)
    assert mgr._embed_prompt("hello") == []

    # set() no vector branch
    mgr._redis = object()
    monkeypatch.setattr(mgr, "_embed_prompt", lambda _p: [])
    asyncio.run(mgr.set("p", "r"))


def test_openai_chat_llmapierror_closes_span_with_exc_info(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=30, OPENAI_MODEL="gpt", ENABLE_TRACING=True)
    client = llm_mod.OpenAIClient(cfg)

    class _Span:
        def set_attribute(self, *_a):
            return None

    class _SpanCM:
        def __init__(self):
            self.exited = None

        def __enter__(self):
            return _Span()

        def __exit__(self, exc_type, exc, tb):
            self.exited = (exc_type, exc, tb)

    span_cm = _SpanCM()

    class _Tracer:
        def start_as_current_span(self, _name):
            return span_cm

    monkeypatch.setattr(llm_mod, "_get_tracer", lambda _cfg: _Tracer())

    async def _raise(*args, **kwargs):
        raise llm_mod.LLMAPIError("openai", "retry fail", retryable=True)

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise)

    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    assert span_cm.exited[0] is not None


def test_stream_openai_compatible_handles_error_and_closes_resources(llm_mod, monkeypatch):
    cfg = SimpleNamespace()
    client = llm_mod.LiteLLMClient(cfg)

    class _Resp:
        async def aiter_lines(self):
            yield "data: {\"choices\":[{\"delta\":{\"content\":\"A\"}}]}"
            yield "data: [DONE]"

    class _CM:
        def __init__(self):
            self.exited = False

        async def __aexit__(self, *args):
            self.exited = True

    class _Client:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    stream_cm = _CM()
    stream_client = _Client()

    async def _ok_retry(*args, **kwargs):
        return stream_client, stream_cm, _Resp()

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _ok_retry)
    out = asyncio.run(_collect(
        client._stream_openai_compatible("http://x", {"a": 1}, {}, llm_mod.httpx.Timeout(10), json_mode=True)
    ))
    assert out == ["A"]
    assert stream_cm.exited is True
    assert stream_client.closed is True

    async def _err_retry(*args, **kwargs):
        raise RuntimeError("stream-fail")

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _err_retry)
    out2 = asyncio.run(_collect(
        client._stream_openai_compatible("http://x", {"a": 1}, {}, llm_mod.httpx.Timeout(10), json_mode=True)
    ))
    import json
    assert "LiteLLM akış hatası" in json.loads(out2[0])["argument"]


def test_llm_client_truncates_ollama_messages_and_applies_budget(llm_mod, monkeypatch):
    cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_CONTEXT_MAX_CHARS=2000,
        ENABLE_SEMANTIC_CACHE=False,
    )
    fac = llm_mod.LLMClient("ollama", cfg)

    messages = [
        {"role": "system", "content": "S" * 500},
        {"role": "user", "content": "u1" * 600},
        {"role": "assistant", "content": "a1" * 500},
        {"role": "user", "content": "LAST" * 300},
    ]
    truncated = fac._truncate_messages_for_local_model(messages)
    assert sum(len(m["content"]) for m in truncated) <= 2000
    assert truncated[-1]["content"].endswith("LAST")
    assert any(m["role"] == "system" for m in truncated)

    called = {"flag": False}

    def _fake_truncate(msgs):
        called["flag"] = True
        return msgs

    async def _fake_chat(**kwargs):
        return "ok"

    monkeypatch.setattr(fac, "_truncate_messages_for_local_model", _fake_truncate)
    monkeypatch.setattr(fac, "_client", SimpleNamespace(chat=_fake_chat))

    out = asyncio.run(fac.chat(messages=[{"role": "user", "content": "hello"}], stream=False))
    assert out == "ok"
    assert called["flag"] is True
