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

def test_provider_retry_warnings_cover_openai_ollama_and_anthropic(monkeypatch):
    warnings = []
    monkeypatch.setattr(llm.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))
    async def _fast_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    openai_attempts = {"count": 0}

    class _OpenAIResponse:
        def raise_for_status(self):
            if openai_attempts["count"] == 0:
                openai_attempts["count"] += 1
                raise llm.httpx.HTTPStatusError(429)

        def json(self):
            return {"choices": [{"message": {"content": "openai-ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class _OpenAIClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return _OpenAIResponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _OpenAIClient)
    openai_cfg = SimpleNamespace(
        OPENAI_API_KEY="key",
        OPENAI_MODEL="gpt-test",
        OPENAI_TIMEOUT=10,
        LLM_MAX_RETRIES=1,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.01,
    )
    openai = llm.OpenAIClient(openai_cfg)
    openai_result = asyncio.run(openai.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=False))
    assert openai_result == "openai-ok"
    assert openai_attempts["count"] == 1

    ollama_attempts = {"count": 0}

    class _OllamaResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ollama-ok"}}

    class _OllamaClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            if ollama_attempts["count"] == 0:
                ollama_attempts["count"] += 1
                raise llm.httpx.TimeoutException("ollama timeout")
            return _OllamaResponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _OllamaClient)
    ollama_cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=10,
        CODING_MODEL="qwen2.5-coder:7b",
        USE_GPU=False,
        LLM_MAX_RETRIES=1,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.01,
    )
    ollama = llm.OllamaClient(ollama_cfg)
    ollama_result = asyncio.run(ollama.chat([{"role": "user", "content": "selam"}], stream=False, json_mode=False))
    assert ollama_result == "ollama-ok"
    assert ollama_attempts["count"] == 1

    anthropic_attempts = {"count": 0}

    class _MessagesAPI:
        async def create(self, **_kwargs):
            if anthropic_attempts["count"] == 0:
                anthropic_attempts["count"] += 1
                raise llm.httpx.TimeoutException("anthropic timeout")
            return SimpleNamespace(
                content=[SimpleNamespace(text="anthropic-ok")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    class _AsyncAnthropic:
        def __init__(self, api_key, timeout):
            self.api_key = api_key
            self.timeout = timeout
            self.messages = _MessagesAPI()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    anthropic_cfg = SimpleNamespace(
        ANTHROPIC_API_KEY="anth-key",
        ANTHROPIC_MODEL="claude-test",
        ANTHROPIC_TIMEOUT=10,
        LLM_MAX_RETRIES=1,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.01,
    )
    anthropic = llm.AnthropicClient(anthropic_cfg)
    anthropic_result = asyncio.run(anthropic.chat([{"role": "user", "content": "hey"}], stream=False, json_mode=False))
    assert anthropic_result == "anthropic-ok"
    assert anthropic_attempts["count"] == 1

    assert any("openai geçici hata" in entry and "429" in entry for entry in warnings)
    assert any("ollama geçici hata" in entry and "ollama timeout" in entry for entry in warnings)
    assert any("anthropic geçici hata" in entry and "anthropic timeout" in entry for entry in warnings)


@pytest.mark.parametrize(
    ("client_factory", "cfg", "expected_fragment"),
    [
        (
            lambda cfg: llm.OpenAIClient(cfg),
            SimpleNamespace(OPENAI_API_KEY="", OPENAI_MODEL="gpt-test", OPENAI_TIMEOUT=10),
            "OPENAI_API_KEY ayarlanmamış",
        ),
        (
            lambda cfg: llm.GeminiClient(cfg),
            SimpleNamespace(GEMINI_API_KEY="", GEMINI_MODEL="gemini-test", ENABLE_TRACING=False),
            "GEMINI_API_KEY ayarlanmamış",
        ),
        (
            lambda cfg: llm.AnthropicClient(cfg),
            SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL="claude-test", ANTHROPIC_TIMEOUT=10),
            "ANTHROPIC_API_KEY ayarlanmamış",
        ),
    ],
)
def test_provider_missing_api_keys_return_fallback_payloads(monkeypatch, client_factory, cfg, expected_fragment):
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda **_kwargs: None
    fake_genai.GenerativeModel = object
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    client = client_factory(cfg)
    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    payload = json.loads(result)
    assert expected_fragment in payload["argument"]


def test_gemini_stream_retry_warns_on_transient_timeout(monkeypatch):
    warnings = []
    monkeypatch.setattr(llm.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))
    async def _fast_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda *_args, **_kwargs: 0.0)

    calls = {"stream_attempts": 0, "configured_key": None}

    class _Chunk:
        def __init__(self, text):
            self.text = text

    class _Session:
        async def send_message_async(self, prompt, stream=False):
            assert prompt == "retry please"
            if stream:
                if calls["stream_attempts"] == 0:
                    calls["stream_attempts"] += 1
                    raise llm.httpx.TimeoutException("gemini stream timeout")

                async def _iter():
                    yield _Chunk("gemini-ok")

                return _iter()
            raise AssertionError("non-stream path should not be used")

    class _Model:
        def __init__(self, **_kwargs):
            pass

        def start_chat(self, history):
            assert history == []
            return _Session()

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key: calls.__setitem__("configured_key", api_key)
    fake_genai.GenerativeModel = _Model
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.delitem(sys.modules, "google.generativeai.types", raising=False)

    gemini = llm.GeminiClient(
        SimpleNamespace(
            GEMINI_API_KEY="gem-key",
            GEMINI_MODEL="gemini-test",
            ENABLE_TRACING=False,
            LLM_MAX_RETRIES=1,
            LLM_RETRY_BASE_DELAY=0.01,
            LLM_RETRY_MAX_DELAY=0.01,
        )
    )

    async def _run():
        stream = await gemini.chat([{"role": "user", "content": "retry please"}], stream=True, json_mode=False)
        return await _collect(stream)

    out = asyncio.run(_run())
    assert out == ["gemini-ok"]
    assert calls["configured_key"] == "gem-key"
    assert calls["stream_attempts"] == 1
    assert any("gemini geçici hata" in entry and "gemini stream timeout" in entry for entry in warnings)
