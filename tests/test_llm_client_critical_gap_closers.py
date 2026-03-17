import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest



def _load_llm_module(*, break_redis=False):
    name = "llm_client_under_test" if not break_redis else "llm_client_no_redis_for_test"
    sys.modules.pop(name, None)

    class _Timeout:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _ConnectError(Exception):
        pass

    class _TimeoutException(Exception):
        pass

    class _HTTPStatusError(Exception):
        def __init__(self, code=500):
            self.response = SimpleNamespace(status_code=code)

    httpx_stub = types.SimpleNamespace(
        Timeout=_Timeout,
        ConnectError=_ConnectError,
        TimeoutException=_TimeoutException,
        HTTPStatusError=_HTTPStatusError,
        AsyncClient=None,
    )
    sys.modules["httpx"] = httpx_stub

    if break_redis:
        sys.modules["redis"] = types.ModuleType("redis")

    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = [str(Path("core").resolve())]
    sys.modules.setdefault("core", core_pkg)

    llm_metrics_mod = types.ModuleType("core.llm_metrics")
    llm_metrics_mod.get_current_metrics_user_id = lambda: ""

    class _Collector:
        def record(self, **_kwargs):
            return None

    llm_metrics_mod.get_llm_metrics_collector = lambda: _Collector()
    sys.modules["core.llm_metrics"] = llm_metrics_mod

    spec = importlib.util.spec_from_file_location(name, Path("core/llm_client.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


llm = _load_llm_module()


def test_import_fallback_sets_redis_none_when_redis_import_fails():
    mod = _load_llm_module(break_redis=True)
    assert mod.Redis is None


class _FakePipe:
    def __init__(self):
        self.calls = []
        self.executed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def hset(self, *args, **kwargs):
        self.calls.append(("hset", args, kwargs))

    def expire(self, *args, **kwargs):
        self.calls.append(("expire", args, kwargs))

    def lrem(self, *args, **kwargs):
        self.calls.append(("lrem", args, kwargs))

    def lpush(self, *args, **kwargs):
        self.calls.append(("lpush", args, kwargs))

    def ltrim(self, *args, **kwargs):
        self.calls.append(("ltrim", args, kwargs))

    async def execute(self):
        self.executed = True


class _FakeRedis:
    def __init__(self):
        self.pinged = False
        self.items = {}
        self.index = []
        self.pipe = _FakePipe()

    async def ping(self):
        self.pinged = True

    async def lrange(self, _key, _start, _end):
        return list(self.index)

    async def hgetall(self, key):
        return self.items.get(key, {})

    def pipeline(self, transaction=True):
        assert transaction is True
        return self.pipe


def test_semantic_cache_core_paths(monkeypatch):
    cfg = SimpleNamespace(
        ENABLE_SEMANTIC_CACHE=True,
        REDIS_URL="redis://test",
        SEMANTIC_CACHE_THRESHOLD=0.5,
        SEMANTIC_CACHE_TTL=30,
        SEMANTIC_CACHE_MAX_ITEMS=10,
    )
    cache = llm._SemanticCacheManager(cfg)

    # _get_redis exception path
    class _BrokenRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(llm, "Redis", _BrokenRedis, raising=False)
    assert asyncio.run(cache._get_redis()) is None

    # _get_redis success + reuse
    fake = _FakeRedis()

    class _GoodRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return fake

    monkeypatch.setattr(llm, "Redis", _GoodRedis, raising=False)
    got = asyncio.run(cache._get_redis())
    assert got is fake
    assert fake.pinged is True
    assert asyncio.run(cache._get_redis()) is fake

    # cosine edge paths
    assert cache._cosine_similarity([], [1.0]) == 0.0
    assert cache._cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cache._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    # embed path exception
    rag_mod = types.ModuleType("core.rag")

    def _raise_embed(*_args, **_kwargs):
        raise RuntimeError("embed fail")

    rag_mod.embed_texts_for_semantic_cache = _raise_embed
    monkeypatch.setitem(sys.modules, "core.rag", rag_mod)
    assert cache._embed_prompt("hello") == []

    # get(): empty query vector branch
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [])
    assert asyncio.run(cache.get("hello")) is None

    # get(): parse failures + miss + hit
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [1.0, 0.0])
    fake.index = ["k1", "k2", "k3"]
    fake.items = {
        "k1": {"embedding": "not-json", "response": "x"},
        "k2": {"embedding": json.dumps([0.0, 1.0]), "response": "low"},
        "k3": {"embedding": json.dumps([1.0, 0.0]), "response": "high"},
    }
    assert asyncio.run(cache.get("hello")) == "high"

    fake.items = {"k2": {"embedding": json.dumps([0.0, 1.0]), "response": "low"}}
    assert asyncio.run(cache.get("hello")) is None

    class _FailRedis(_FakeRedis):
        async def lrange(self, *_args):
            raise RuntimeError("boom")

    cache._redis = _FailRedis()
    assert asyncio.run(cache.get("hello")) is None

    # set(): short-circuit when embed empty, then success, then exception
    cache._redis = fake
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [])
    asyncio.run(cache.set("p", "r"))

    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [0.2, 0.8])
    asyncio.run(cache.set("p", "r"))
    assert fake.pipe.executed is True

    class _ExplodingPipeRedis(_FakeRedis):
        def pipeline(self, transaction=True):
            raise RuntimeError("pipe fail")

    cache._redis = _ExplodingPipeRedis()
    asyncio.run(cache.set("p", "r"))


def test_openai_llmapierror_calls_span_exit_with_exc_info(monkeypatch):
    cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="m", OPENAI_TIMEOUT=30)
    client = llm.OpenAIClient(cfg)

    class _Span:
        def set_attribute(self, *_args):
            return None

    class _CM:
        def __init__(self):
            self.exit_args = None

        def __enter__(self):
            return _Span()

        def __exit__(self, *args):
            self.exit_args = args
            return False

    cm = _CM()

    class _Tracer:
        def start_as_current_span(self, _name):
            return cm

    async def _raise_api_error(*_args, **_kwargs):
        raise llm.LLMAPIError("openai", "retry fail", retryable=True)

    monkeypatch.setattr(llm, "_get_tracer", lambda _cfg: _Tracer())
    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_api_error)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    with pytest.raises(llm.LLMAPIError):
        asyncio.run(client.chat(messages=[{"role": "user", "content": "x"}], stream=False))

    assert cm.exit_args is not None
    assert cm.exit_args[0] is llm.LLMAPIError


def test_stream_openai_compatible_cleanup_and_fallback(monkeypatch):
    cfg = SimpleNamespace(LITELLM_TIMEOUT=20)
    client = llm.LiteLLMClient(cfg)

    class _Resp:
        async def aiter_lines(self):
            yield "data: [DONE]"

    class _CM:
        def __init__(self):
            self.closed = False

        async def __aexit__(self, *_args):
            self.closed = True

    class _Client:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    c = _Client()
    cm = _CM()

    async def _ok(*_args, **_kwargs):
        return c, cm, _Resp()

    monkeypatch.setattr(llm, "_retry_with_backoff", _ok)
    out = asyncio.run(_collect(client._stream_openai_compatible("u", {}, {}, llm.httpx.Timeout(10), json_mode=False)))
    assert out == []
    assert cm.closed is True
    assert c.closed is True

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("stream fail")

    monkeypatch.setattr(llm, "_retry_with_backoff", _boom)
    out = asyncio.run(_collect(client._stream_openai_compatible("u", {}, {}, llm.httpx.Timeout(10), json_mode=True)))
    assert len(out) == 1
    payload = json.loads(out[0])
    assert "LiteLLM" in payload["argument"]


def test_llm_client_ollama_truncation_path_and_message_budget():
    cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_CONTEXT_MAX_CHARS=1300,
        ENABLE_SEMANTIC_CACHE=False,
    )
    cli = llm.LLMClient("ollama", cfg)

    messages = [
        {"role": "system", "content": "S" * 500},
        {"role": "user", "content": "U1" * 300},
        {"role": "assistant", "content": "A" * 400},
        {"role": "user", "content": "LAST" * 200},
    ]
    truncated = cli._truncate_messages_for_local_model(messages)
    assert sum(len(m["content"]) for m in truncated) <= 1300
    assert truncated[-1]["role"] == "user"

    async def _fake_chat(**kwargs):
        return kwargs["messages"]

    cli._client.chat = _fake_chat
    out = asyncio.run(cli.chat(messages=messages, stream=False, json_mode=False))
    assert isinstance(out, list)
    assert sum(len(m["content"]) for m in out) <= 1300


async def _collect(aiter):
    return [x async for x in aiter]