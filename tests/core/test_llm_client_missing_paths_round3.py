from __future__ import annotations

import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

import importlib.util

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.Timeout = object
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

import core.llm_client as llm


def test_semantic_cache_get_redis_disabled_and_reuse_instance() -> None:
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=False)
    cache = llm._SemanticCacheManager(cfg)
    assert asyncio.run(cache._get_redis()) is None

    llm.Redis = object  # type: ignore[assignment]
    cfg2 = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True)
    cache2 = llm._SemanticCacheManager(cfg2)
    sentinel = object()
    cache2._redis = sentinel  # type: ignore[assignment]
    assert asyncio.run(cache2._get_redis()) is sentinel


def test_semantic_cache_get_handles_empty_and_bad_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = llm._SemanticCacheManager(SimpleNamespace(ENABLE_SEMANTIC_CACHE=True))

    class _Redis:
        async def lrange(self, *_args):
            return ["k1", "k2"]

        async def hgetall(self, key):
            if key == "k1":
                return {"embedding": "not-json", "response": "bad"}
            return {"embedding": json.dumps([1.0, 0.0]), "response": "ok"}

    async def _fake_get_redis():
        return _Redis()

    monkeypatch.setattr(cache, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(cache, "_embed_prompt", lambda _p: [1.0, 0.0])
    assert asyncio.run(cache.get("prompt")) == "ok"


def test_ollama_list_models_and_is_available_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client = llm.OllamaClient(SimpleNamespace(OLLAMA_URL="http://localhost:11434"))

    class _BrokenAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            raise RuntimeError("down")

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm.httpx, "AsyncClient", _BrokenAsyncClient)
    assert asyncio.run(client.list_models()) == []
    assert asyncio.run(client.is_available()) is False


def test_ollama_stream_response_parses_trailing_and_error_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = llm.OllamaClient(SimpleNamespace())

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":"par"}}\n'
            yield b'{"message":{"content":"ca"}}'

    async def _retry_ok(*_args, **_kwargs):
        class _Client:
            async def aclose(self):
                return None

        class _CM:
            async def __aexit__(self, *_x):
                return None

        return _Client(), _CM(), _Resp()

    monkeypatch.setattr(llm, "_retry_with_backoff", _retry_ok)

    async def _collect_ok():
        return [c async for c in client._stream_response("u", {}, timeout=object())]

    assert asyncio.run(_collect_ok()) == ["par", "ca"]

    async def _retry_fail(*_args, **_kwargs):
        raise RuntimeError("stream-open-fail")

    monkeypatch.setattr(llm, "_retry_with_backoff", _retry_fail)

    async def _collect_fail():
        return [c async for c in client._stream_response("u", {}, timeout=object())]

    err_payload = json.loads(asyncio.run(_collect_fail())[0])
    assert "Akış kesildi" in err_payload["argument"]


def test_gemini_chat_missing_package_and_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def _fake_import_missing(name, *args, **kwargs):
        if name in {"google", "google.genai"}:
            raise ImportError("missing google-genai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import_missing)
    client_missing_pkg = llm.GeminiClient(SimpleNamespace(GEMINI_API_KEY="x", GEMINI_MODEL="m"))
    msg = asyncio.run(client_missing_pkg.chat(messages=[{"role": "user", "content": "hi"}], stream=False))
    assert "google-genai" in json.loads(msg)["argument"]
    monkeypatch.setattr("builtins.__import__", real_import)

    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")

    class _DummyClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    genai_mod.Client = _DummyClient
    genai_mod.types = SimpleNamespace()
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod

    client_missing_key = llm.GeminiClient(SimpleNamespace(GEMINI_API_KEY="", GEMINI_MODEL="m"))
    msg2 = asyncio.run(client_missing_key.chat(messages=[{"role": "user", "content": "hi"}], stream=False))
    assert "GEMINI_API_KEY" in json.loads(msg2)["argument"]


def test_openai_and_litellm_missing_config_paths() -> None:
    openai = llm.OpenAIClient(SimpleNamespace(OPENAI_API_KEY=""))
    msg = asyncio.run(openai.chat(messages=[{"role": "user", "content": "x"}], stream=False))
    assert "OPENAI_API_KEY" in json.loads(msg)["argument"]

    litellm = llm.LiteLLMClient(SimpleNamespace(LITELLM_GATEWAY_URL="", LITELLM_API_KEY=""))
    msg2 = asyncio.run(litellm.chat(messages=[{"role": "user", "content": "x"}], stream=False))
    assert "LITELLM_GATEWAY_URL" in json.loads(msg2)["argument"]


def test_anthropic_chat_missing_key_and_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    no_key_client = llm.AnthropicClient(SimpleNamespace(ANTHROPIC_API_KEY=""))
    payload = json.loads(asyncio.run(no_key_client.chat(messages=[{"role": "user", "content": "x"}])))
    assert "ANTHROPIC_API_KEY" in payload["argument"]

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m", ENABLE_TRACING=False)
    client = llm.AnthropicClient(cfg)

    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("missing anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    payload2 = json.loads(asyncio.run(client.chat(messages=[{"role": "user", "content": "x"}])))
    assert "anthropic paketi" in payload2["argument"]


def test_llm_client_helpers_for_non_ollama_provider() -> None:
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=22)
    client = llm.LLMClient("openai", cfg)
    assert client._ollama_base_url == "http://localhost:11434"

    llm.httpx.Timeout = lambda *_a, **_k: {"ok": True}  # type: ignore[assignment]
    timeout = client._build_ollama_timeout()
    assert timeout is not None

    assert asyncio.run(client.list_ollama_models()) == []
    assert asyncio.run(client.is_ollama_available()) is False


def test_llm_client_chat_saves_cache_and_records_routing_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(COST_ROUTING_TOKEN_COST_USD=1e-6)
    client = llm.LLMClient("openai", cfg)

    class _Inner:
        async def chat(self, **_kwargs):
            return "plain-response"

    class _Cache:
        def __init__(self):
            self.saved = None

        async def get(self, _prompt):
            return None

        async def set(self, prompt, response):
            self.saved = (prompt, response)

    cache = _Cache()
    client._client = _Inner()
    client._semantic_cache = cache
    client._router.select = lambda _messages, provider, model: (provider, model)

    costs: list[float] = []
    monkeypatch.setattr(llm, "record_routing_cost", lambda c: costs.append(c))
    monkeypatch.setattr(llm, "_dlp_mask_messages", lambda messages: messages)

    result = asyncio.run(client.chat(messages=[{"role": "user", "content": "Merhaba"}], stream=False, json_mode=False))
    assert result == "plain-response"
    assert cache.saved == ("Merhaba", "plain-response")
    assert costs and costs[0] > 0


def test_llm_client_chat_ollama_truncates_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(OLLAMA_CONTEXT_MAX_CHARS=10)
    client = llm.LLMClient("ollama", cfg)

    class _Inner:
        def __init__(self):
            self.seen = None

        async def chat(self, **kwargs):
            self.seen = kwargs["messages"]
            return "ok"

    inner = _Inner()
    client._client = inner
    client._router.select = lambda _messages, provider, model: (provider, model)
    monkeypatch.setattr(llm, "_dlp_mask_messages", lambda messages: messages)

    asyncio.run(
        client.chat(
            messages=[
                {"role": "system", "content": "S" * 50},
                {"role": "user", "content": "U" * 50},
            ],
            stream=False,
            json_mode=False,
        )
    )

    assert inner.seen is not None
    assert sum(len(m["content"]) for m in inner.seen) <= 400
