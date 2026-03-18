import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from tests.test_llm_client_critical_gap_closers import _FakeRedis, _collect, _load_llm_module


llm = _load_llm_module()


def test_semantic_cache_embeds_first_vector_and_returns_none_for_empty_index(monkeypatch):
    cfg = SimpleNamespace(
        ENABLE_SEMANTIC_CACHE=True,
        REDIS_URL="redis://test",
        SEMANTIC_CACHE_THRESHOLD=0.5,
        SEMANTIC_CACHE_TTL=30,
        SEMANTIC_CACHE_MAX_ITEMS=10,
    )
    cache = llm._SemanticCacheManager(cfg)

    rag_mod = types.ModuleType("core.rag")
    rag_mod.embed_texts_for_semantic_cache = lambda texts, cfg=None: [[1, 2.5]]
    monkeypatch.setitem(sys.modules, "core.rag", rag_mod)

    assert cache._embed_prompt("hello") == [1.0, 2.5]

    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr(cache, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(cache, "_embed_prompt", lambda _prompt: [1.0, 0.0])
    assert asyncio.run(cache.get("hello")) is None


def test_litellm_stream_open_handles_non_data_and_http_5xx(monkeypatch):
    cfg = SimpleNamespace(LITELLM_TIMEOUT=20, LLM_MAX_RETRIES=0, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.02)
    client = llm.LiteLLMClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield "event: ping"
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield "data: [DONE]"

    class _CM:
        def __init__(self, response):
            self.response = response
            self.closed = False

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *_args):
            self.closed = True
            return False

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout
            self.closed = False

        def stream(self, method, endpoint, json=None, headers=None):
            return _CM(_Resp())

        async def aclose(self):
            self.closed = True

    async def _call_operation(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm, "_retry_with_backoff", _call_operation)

    out = asyncio.run(_collect(client._stream_openai_compatible("http://gateway/chat/completions", {}, {}, llm.httpx.Timeout(10), json_mode=False)))
    assert out == ["ok"]

    class _Resp5xx:
        def raise_for_status(self):
            raise llm.httpx.HTTPStatusError(503)

        async def aiter_lines(self):
            if False:
                yield ""

    class _Client5xx(_Client):
        def stream(self, method, endpoint, json=None, headers=None):
            return _CM(_Resp5xx())

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client5xx)
    err = asyncio.run(_collect(client._stream_openai_compatible("http://gateway/chat/completions", {}, {}, llm.httpx.Timeout(10), json_mode=True)))
    payload = json.loads(err[0])
    assert "LiteLLM akış hatası" in payload["argument"]


def test_provider_error_paths_cover_timeout_bad_json_and_5xx(monkeypatch):
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    openai = llm.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", OPENAI_TIMEOUT=10))

    async def _raise_openai_timeout(*_args, **_kwargs):
        raise llm.httpx.TimeoutException("openai timeout")

    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_openai_timeout)
    with pytest.raises(llm.LLMAPIError) as openai_timeout:
        asyncio.run(openai.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False))
    assert "openai timeout" in str(openai_timeout.value)

    async def _raise_openai_5xx(*_args, **_kwargs):
        raise llm.LLMAPIError("openai", "server exploded", status_code=503, retryable=True)

    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_openai_5xx)
    with pytest.raises(llm.LLMAPIError) as openai_5xx:
        asyncio.run(openai.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    assert openai_5xx.value.status_code == 503

    ollama = llm.OllamaClient(SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=10, CODING_MODEL="qwen", USE_GPU=False))

    async def _raise_ollama_timeout(*_args, **_kwargs):
        raise llm.httpx.TimeoutException("ollama timeout")

    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_ollama_timeout)
    with pytest.raises(llm.LLMAPIError) as ollama_timeout:
        asyncio.run(ollama.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False))
    assert "ollama timeout" in str(ollama_timeout.value)

    async def _raise_ollama_bad_json(*_args, **_kwargs):
        raise ValueError("bad ollama json")

    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_ollama_bad_json)
    with pytest.raises(llm.LLMAPIError) as ollama_json:
        asyncio.run(ollama.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    assert "bad ollama json" in str(ollama_json.value)

    class _AsyncAnthropic:
        def __init__(self, api_key, timeout):
            self.api_key = api_key
            self.timeout = timeout

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    anthropic = llm.AnthropicClient(SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ANTHROPIC_TIMEOUT=10))

    async def _raise_anthropic_timeout(*_args, **_kwargs):
        raise llm.httpx.TimeoutException("anthropic timeout")

    monkeypatch.setattr(llm, "_retry_with_backoff", _raise_anthropic_timeout)
    with pytest.raises(llm.LLMAPIError) as anthropic_timeout:
        asyncio.run(anthropic.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False))
    assert "anthropic timeout" in str(anthropic_timeout.value)

    async def _return_bad_json(*_args, **_kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text="{broken")], usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(llm, "_retry_with_backoff", _return_bad_json)
    anthropic_json = asyncio.run(anthropic.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    parsed = json.loads(anthropic_json)
    assert "JSON dışı" in parsed["thought"]

    calls = {}

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Session:
        async def send_message_async(self, prompt, stream=False):
            calls.setdefault("prompts", []).append((prompt, stream))
            if prompt == "timeout":
                raise llm.httpx.TimeoutException("gemini timeout")
            if prompt == "server":
                raise RuntimeError("HTTP 503 from gemini")
            return _Resp("{broken")

    class _Model:
        def __init__(self, **kwargs):
            calls["model_kwargs"] = kwargs

        def start_chat(self, history):
            calls["history"] = history
            return _Session()

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key: calls.setdefault("api_key", api_key)
    fake_genai.GenerativeModel = _Model
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.delitem(sys.modules, "google.generativeai.types", raising=False)

    gemini = llm.GeminiClient(SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=False))
    timeout_msg = asyncio.run(gemini.chat([{"role": "user", "content": "timeout"}], stream=False, json_mode=True))
    assert "gemini timeout" in json.loads(timeout_msg)["argument"]

    server_msg = asyncio.run(gemini.chat([{"role": "user", "content": "server"}], stream=False, json_mode=True))
    assert "HTTP 503" in json.loads(server_msg)["argument"]

    bad_json_msg = asyncio.run(gemini.chat([{"role": "user", "content": "broken"}], stream=False, json_mode=True))
    assert "JSON dışı" in json.loads(bad_json_msg)["thought"]


def test_llm_client_ollama_truncation_edge_branches():
    cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_CONTEXT_MAX_CHARS=1300,
        ENABLE_SEMANTIC_CACHE=False,
    )
    cli = llm.LLMClient("ollama", cfg)

    empty = []
    assert cli._truncate_messages_for_local_model(empty) is empty

    under_budget = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    normalized = cli._truncate_messages_for_local_model(under_budget)
    assert normalized == under_budget

    oversized = [
        {"role": "system", "content": "S" * 300},
        {"role": "user", "content": "U" * 100},
        {"role": "system", "content": "IGNORED"},
        {"role": "assistant", "content": "A" * 50},
        {"role": "user", "content": "L" * 1000},
    ]
    truncated = cli._truncate_messages_for_local_model(oversized)
    assert sum(len(m["content"]) for m in truncated) <= 1300
    assert truncated[0]["role"] == "system"
    assert all(not (m["role"] == "system" and m["content"] == "IGNORED") for m in truncated)