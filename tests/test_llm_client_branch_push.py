import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from tests.test_llm_client_runtime import _collect, _load_llm_client_module


@pytest.fixture
def llm_mod():
    return _load_llm_client_module()


def test_semantic_cache_get_keeps_best_match_when_later_similarity_is_lower(llm_mod, monkeypatch):
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True)
    cache = llm_mod._SemanticCacheManager(cfg)
    cache.threshold = 0.75

    class _Redis:
        async def lrange(self, *_args, **_kwargs):
            return ["k1", "k2"]

        async def hgetall(self, key):
            if key == "k1":
                return {"embedding": json.dumps([1.0, 0.0]), "response": "best"}
            return {"embedding": json.dumps([0.1, 0.9]), "response": "worse"}

    monkeypatch.setattr(cache, "_get_redis", lambda: asyncio.sleep(0, result=_Redis()))
    monkeypatch.setattr(cache, "_embed_prompt", lambda _prompt: [1.0, 0.0])
    monkeypatch.setattr(llm_mod, "record_cache_hit", lambda: None)
    monkeypatch.setattr(llm_mod, "observe_cache_redis_latency", lambda *_args: None)
    monkeypatch.setattr(llm_mod, "set_cache_items", lambda *_args: None)

    assert asyncio.run(cache.get("hello")) == "best"


def test_semantic_cache_set_skips_eviction_metric_for_existing_key(llm_mod, monkeypatch):
    cfg = SimpleNamespace(ENABLE_SEMANTIC_CACHE=True)
    cache = llm_mod._SemanticCacheManager(cfg)
    cache.max_items = 2

    class _Pipe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def hset(self, *_args, **_kwargs):
            return None

        def expire(self, *_args, **_kwargs):
            return None

        def lrem(self, *_args, **_kwargs):
            return None

        def lpush(self, *_args, **_kwargs):
            return None

        def ltrim(self, *_args, **_kwargs):
            return None

        async def execute(self):
            return None

    class _Redis:
        async def lrange(self, *_args, **_kwargs):
            return [
                "sidar:semantic_cache:item:existing",
                "sidar:semantic_cache:item:other",
            ]

        def pipeline(self, transaction=True):
            assert transaction is True
            return _Pipe()

        async def llen(self, *_args, **_kwargs):
            return 2

    monkeypatch.setattr(cache, "_get_redis", lambda: asyncio.sleep(0, result=_Redis()))
    monkeypatch.setattr(cache, "_embed_prompt", lambda _prompt: [0.3, 0.7])
    monkeypatch.setattr(
        llm_mod.hashlib,
        "sha256",
        lambda *_args, **_kwargs: types.SimpleNamespace(hexdigest=lambda: "existing"),
    )
    monkeypatch.setattr(llm_mod, "set_cache_items", lambda *_args: None)
    monkeypatch.setattr(llm_mod, "observe_cache_redis_latency", lambda *_args: None)

    evictions = []
    monkeypatch.setattr(llm_mod, "record_cache_eviction", lambda: evictions.append(True))

    asyncio.run(cache.set("hello", "world"))

    assert evictions == []


def test_ollama_stream_ignores_empty_content_in_line_trailing_and_buffer(llm_mod, monkeypatch):
    client = llm_mod.OllamaClient(SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=10, USE_GPU=False))
    state = {"client_closed": False, "stream_closed": False}

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":""}}\n'
            yield b'{"message":{"content":""}}\n'
            yield b'{"message":{"content":""}}'

    class _StreamCM:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            state["stream_closed"] = True
            return False

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, *_args, **_kwargs):
            return _StreamCM()

        async def aclose(self):
            state["client_closed"] = True

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)

    out = asyncio.run(_collect(client._stream_response("http://localhost/api/chat", {"x": 1}, llm_mod.httpx.Timeout(10))))

    assert out == []
    assert state == {"client_closed": True, "stream_closed": True}


def test_gemini_chat_skips_empty_first_user_message_from_history(llm_mod, monkeypatch):
    seen = {}

    class _ChatSession:
        async def send_message_async(self, prompt, stream=False):
            seen["prompt"] = prompt
            seen["stream"] = stream
            return types.SimpleNamespace(text="gemini-ok")

    class _Model:
        def __init__(self, **kwargs):
            seen["model_kwargs"] = kwargs

        def start_chat(self, history):
            seen["history"] = history
            return _ChatSession()

    genai_mod = types.SimpleNamespace(configure=lambda **_kwargs: None, GenerativeModel=_Model)
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(generativeai=genai_mod))
    monkeypatch.setitem(sys.modules, "google.generativeai", genai_mod)

    client = llm_mod.GeminiClient(SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="gemini", ENABLE_TRACING=False))
    result = asyncio.run(
        client.chat(
            [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": "assistant-reply"},
            ],
            stream=False,
            json_mode=False,
        )
    )

    assert result == "gemini-ok"
    assert seen["history"] == []
    assert seen["prompt"] == "assistant-reply"


def test_openai_stream_skips_empty_deltas_and_closes_resources(llm_mod, monkeypatch):
    client = llm_mod.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", OPENAI_TIMEOUT=10, LLM_MAX_RETRIES=0))
    state = {"client_closed": False, "stream_closed": False}

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":""}}]}'
            yield "data: [DONE]"

    class _StreamCM:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *_args):
            state["stream_closed"] = True
            return False

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def stream(self, *_args, **_kwargs):
            return _StreamCM()

        async def aclose(self):
            state["client_closed"] = True

    async def _call_operation(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _call_operation)

    out = asyncio.run(_collect(client._stream_openai({"model": "gpt", "messages": []}, {}, llm_mod.httpx.Timeout(10), json_mode=False)))

    assert out == []
    assert state == {"client_closed": True, "stream_closed": True}


def test_litellm_candidate_models_deduplicates_and_skips_blank_entries(llm_mod):
    client = llm_mod.LiteLLMClient(
        SimpleNamespace(
            LITELLM_MODEL="primary",
            OPENAI_MODEL="fallback-openai",
            LITELLM_FALLBACK_MODELS=["", "primary", "backup", "backup", "  ", "alt"],
        )
    )

    assert client._candidate_models(None) == ["primary", "backup", "alt"]


def test_litellm_chat_raises_after_all_models_fail_and_records_failure(llm_mod, monkeypatch):
    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://gateway",
        LITELLM_API_KEY="",
        LITELLM_MODEL="primary",
        LITELLM_FALLBACK_MODELS=["backup"],
        LITELLM_TIMEOUT=10,
        LLM_MAX_RETRIES=0,
        ENABLE_TRACING=False,
    )
    client = llm_mod.LiteLLMClient(cfg)
    metrics = []
    warnings = []

    async def _fail(_provider, _operation, **_kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _fail)
    monkeypatch.setattr(llm_mod, "_record_llm_metric", lambda **kwargs: metrics.append(kwargs))
    monkeypatch.setattr(llm_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(client.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False))

    assert "gateway down" in str(exc.value)
    assert len(warnings) == 2
    assert metrics[-1]["provider"] == "litellm"
    assert metrics[-1]["success"] is False


def test_litellm_stream_skips_empty_delta_chunks(llm_mod, monkeypatch):
    client = llm_mod.LiteLLMClient(SimpleNamespace(LITELLM_GATEWAY_URL="http://gateway", LITELLM_TIMEOUT=10, LLM_MAX_RETRIES=0))
    state = {"client_closed": False, "stream_closed": False}

    class _Resp:
        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": ""}}]}'
            yield "data: [DONE]"

    class _CM:
        async def __aexit__(self, *_args):
            state["stream_closed"] = True
            return False

    class _Client:
        async def aclose(self):
            state["client_closed"] = True

    async def _ok(*_args, **_kwargs):
        return _Client(), _CM(), _Resp()

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _ok)

    out = asyncio.run(_collect(client._stream_openai_compatible("u", {}, {}, llm_mod.httpx.Timeout(10), json_mode=False)))

    assert out == []
    assert state == {"client_closed": True, "stream_closed": True}


def test_anthropic_stream_skips_empty_text_delta(llm_mod, monkeypatch):
    class _Delta:
        def __init__(self, text):
            self.type = "text_delta"
            self.text = text

    class _Event:
        def __init__(self, text):
            self.type = "content_block_delta"
            self.delta = _Delta(text)

    class _CM:
        def __init__(self, stream):
            self.stream = stream
            self.closed = False

        async def __aenter__(self):
            return self.stream

        async def __aexit__(self, *_args):
            self.closed = True
            return False

    cm_holder = {}

    class _AsyncEvents:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_done", False):
                raise StopAsyncIteration
            self._done = True
            return _Event("")

    class _Messages:
        def stream(self, **_kwargs):
            cm = _CM(_AsyncEvents())
            cm_holder["cm"] = cm
            return cm

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))

    client = llm_mod.AnthropicClient(SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ANTHROPIC_TIMEOUT=10))
    stream = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=False))
    out = asyncio.run(_collect(stream))

    assert out == []
    assert cm_holder["cm"].closed is True


def test_llmclient_stream_records_cache_skip_without_cache_lookup(llm_mod, monkeypatch):
    cfg = SimpleNamespace(
        OPENAI_API_KEY="k",
        OPENAI_MODEL="gpt",
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=10,
        ENABLE_SEMANTIC_CACHE=False,
    )
    client = llm_mod.LLMClient("openai", cfg)

    skip_calls = []
    cache_get_calls = []

    async def _cache_get(_prompt):
        cache_get_calls.append(True)
        return "cached"

    async def _chat(**kwargs):
        async def _gen():
            yield "streamed"
        return _gen()

    monkeypatch.setattr(client._semantic_cache, "get", _cache_get)
    monkeypatch.setattr(client._client, "chat", _chat)
    monkeypatch.setattr(llm_mod, "record_cache_skip", lambda: skip_calls.append(True))

    stream = asyncio.run(client.chat([{"role": "user", "content": "hello"}], stream=True, json_mode=False))
    out = asyncio.run(_collect(stream))

    assert out == ["streamed"]
    assert skip_calls == [True]
    assert cache_get_calls == []


def test_truncate_messages_skips_empty_system_and_empty_history_entries(llm_mod):
    cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_CONTEXT_MAX_CHARS=1200,
        ENABLE_SEMANTIC_CACHE=False,
    )
    client = llm_mod.LLMClient("ollama", cfg)

    messages = [
        {"role": "assistant", "content": "A" * 600},
        {"role": "system", "content": ""},
        {"role": "user", "content": ""},
        {"role": "user", "content": "L" * 1000},
    ]

    truncated = client._truncate_messages_for_local_model(messages)

    assert sum(len(item["content"]) for item in truncated) <= 1200
    assert all(item["role"] != "system" for item in truncated)
    assert all(item["content"] for item in truncated)
