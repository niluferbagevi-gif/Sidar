from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import core.llm_client as llm_client


def _run(coro):
    return asyncio.run(coro)


def _make_config(**overrides):
    base = {
        "LLM_MAX_RETRIES": 2,
        "LLM_RETRY_BASE_DELAY": 0.01,
        "LLM_RETRY_MAX_DELAY": 0.02,
        "ENABLE_SEMANTIC_CACHE": True,
        "SEMANTIC_CACHE_THRESHOLD": 0.9,
        "SEMANTIC_CACHE_TTL": 60,
        "SEMANTIC_CACHE_MAX_ITEMS": 2,
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_MAX_CONNECTIONS": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    ("provider", "key"),
    [
        ("ollama", "format"),
        ("openai", "response_format"),
        ("litellm", "response_format"),
        ("gemini", "generation_config"),
        ("anthropic", None),
        ("unknown", None),
    ],
)
def test_build_provider_json_mode_config(provider: str, key: str | None) -> None:
    data = llm_client.build_provider_json_mode_config(provider)
    if key is None:
        assert data == {}
    else:
        assert key in data


def test_ensure_json_text_returns_original_for_valid_json() -> None:
    text = '{"tool": "final_answer", "argument": "ok", "thought": "t"}'
    assert llm_client._ensure_json_text(text, "OpenAI") == text


def test_ensure_json_text_wraps_invalid_payload() -> None:
    wrapped = llm_client._ensure_json_text("plain-text", "Gemini")
    data = json.loads(wrapped)
    assert data["tool"] == "final_answer"
    assert data["argument"] == "plain-text"


def test_extract_usage_tokens_supports_prompt_and_output_tokens() -> None:
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 12, "completion_tokens": 34}}) == (12, 34)
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 1, "output_tokens": 3}}) == (1, 3)
    assert llm_client._extract_usage_tokens("invalid") == (0, 0)


def test_is_retryable_exception_for_timeout_and_status() -> None:
    retryable, status = llm_client._is_retryable_exception(httpx.TimeoutException("x"))
    assert retryable is True
    assert status is None

    exc = Exception("boom")
    setattr(exc, "status_code", 503)
    retryable, status = llm_client._is_retryable_exception(exc)
    assert retryable is True
    assert status == 503


def test_is_retryable_exception_for_non_retryable_status() -> None:
    exc = Exception("bad request")
    setattr(exc, "status_code", 400)
    retryable, status = llm_client._is_retryable_exception(exc)
    assert retryable is False
    assert status == 400


class _DummyClient(llm_client.BaseLLMClient):
    def json_mode_config(self):
        return {}

    async def chat(self, *args, **kwargs):
        return "ok"


def test_inject_json_instruction_handles_existing_and_missing_system() -> None:
    with_system = [{"role": "system", "content": "base"}, {"role": "user", "content": "u"}]
    out = _DummyClient._inject_json_instruction(with_system)
    assert out[0]["content"].startswith("base")
    assert llm_client.SIDAR_TOOL_JSON_INSTRUCTION in out[0]["content"]

    without_system = [{"role": "user", "content": "u"}]
    out2 = _DummyClient._inject_json_instruction(without_system)
    assert out2[0]["role"] == "system"
    assert llm_client.SIDAR_TOOL_JSON_INSTRUCTION in out2[0]["content"]


def test_retry_with_backoff_succeeds_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep
    monkeypatch.setattr(llm_client.asyncio, "sleep", lambda *_args, **_kwargs: real_sleep(0))
    monkeypatch.setattr(llm_client.random, "uniform", lambda *_args, **_kwargs: 0.0)
    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] == 1:
            err = Exception("temp")
            setattr(err, "status_code", 429)
            raise err
        return "done"

    result = _run(llm_client._retry_with_backoff("openai", op, config=_make_config(), retry_hint="retry"))
    assert result == "done"
    assert state["n"] == 2


def test_retry_with_backoff_raises_llm_api_error() -> None:
    async def op():
        raise ValueError("fatal")

    with pytest.raises(llm_client.LLMAPIError) as exc:
        _run(llm_client._retry_with_backoff("openai", op, config=_make_config(), retry_hint="retry"))

    assert exc.value.provider == "openai"
    assert exc.value.retryable is False


def test_get_tracer_uses_trace_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    fake_trace = SimpleNamespace(get_tracer=lambda _name: token)
    monkeypatch.setattr(llm_client, "trace", fake_trace)
    assert llm_client._get_tracer(SimpleNamespace(ENABLE_TRACING=True)) is token


def test_fallback_stream_single_chunk() -> None:
    async def consume():
        return [c async for c in llm_client._fallback_stream("err")]

    assert _run(consume()) == ["err"]


def test_record_llm_metric_forwards_metrics_user(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []

    class Collector:
        def record(self, **kwargs):
            events.append(kwargs)

    monkeypatch.setattr(llm_client, "get_llm_metrics_collector", lambda: Collector())
    monkeypatch.setattr(llm_client, "get_current_metrics_user_id", lambda: "u-1")
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: 5.0)
    llm_client._record_llm_metric(provider="openai", model="gpt", started_at=3.5, prompt_tokens=1, completion_tokens=2)
    assert events[0]["user_id"] == "u-1"
    assert events[0]["latency_ms"] == pytest.approx(1500.0)


def test_semantic_cache_cosine_similarity() -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    assert manager._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert manager._cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert manager._cosine_similarity([], [1.0]) == 0.0


class _FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.index: list[str] = []

    async def lrange(self, _key: str, _start: int, _end: int):
        return list(self.index)

    async def hgetall(self, key: str):
        return self.hashes.get(key, {})

    async def llen(self, _key: str):
        return len(self.index)

    def pipeline(self, transaction: bool = True):
        return _FakePipe(self)


class _FakePipe:
    def __init__(self, redis: _FakeRedis):
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def hset(self, key: str, mapping: dict[str, str]):
        self.ops.append(("hset", key, mapping))

    def expire(self, key: str, ttl: int):
        self.ops.append(("expire", key, ttl))

    def lrem(self, _index_key: str, _count: int, key: str):
        self.ops.append(("lrem", key))

    def lpush(self, _index_key: str, key: str):
        self.ops.append(("lpush", key))

    def ltrim(self, _index_key: str, _start: int, end: int):
        self.ops.append(("ltrim", end))

    async def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                self.redis.hashes[op[1]] = op[2]
            elif op[0] == "lrem":
                self.redis.index = [k for k in self.redis.index if k != op[1]]
            elif op[0] == "lpush":
                self.redis.index.insert(0, op[1])
            elif op[0] == "ltrim":
                self.redis.index = self.redis.index[: op[1] + 1]


def test_semantic_cache_get_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    fake = _FakeRedis()
    fake.index = ["k1"]
    fake.hashes["k1"] = {"embedding": json.dumps([1.0, 0.0]), "response": "cached"}

    async def _get_redis():
        return fake

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])

    assert _run(manager.get("hello")) == "cached"


def test_semantic_cache_get_returns_none_without_prompt() -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    assert _run(manager.get("")) is None


def test_semantic_cache_get_records_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config(SEMANTIC_CACHE_THRESHOLD=0.99))
    fake = _FakeRedis()
    fake.index = ["k1"]
    fake.hashes["k1"] = {"embedding": json.dumps([1.0, 0.0]), "response": "cached"}
    misses = {"n": 0}

    async def _get_redis():
        return fake

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [0.0, 1.0])
    monkeypatch.setattr(llm_client, "record_cache_miss", lambda: misses.__setitem__("n", misses["n"] + 1))
    assert _run(manager.get("hello")) is None
    assert misses["n"] == 1


def test_semantic_cache_set_records_item(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    fake = _FakeRedis()
    fake.index = ["old1", "old2"]

    async def _get_redis():
        return fake

    counters = {"eviction": 0}
    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [0.1, 0.2])
    monkeypatch.setattr(llm_client, "record_cache_eviction", lambda: counters.__setitem__("eviction", counters["eviction"] + 1))

    _run(manager.set("prompt", "resp"))

    assert len(fake.index) == 2
    assert any(v.get("response") == "resp" for v in fake.hashes.values())
    assert counters["eviction"] == 1


def test_semantic_cache_set_skips_without_response() -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    assert _run(manager.set("prompt", "")) is None


def test_track_stream_completion_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []

    def recorder(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(llm_client, "_record_llm_metric", recorder)

    async def broken_stream():
        yield "a"
        raise RuntimeError("x")

    async def consume():
        out = []
        with pytest.raises(RuntimeError):
            async for token in llm_client._track_stream_completion(
                broken_stream(), provider="openai", model="m", started_at=0.0
            ):
                out.append(token)
        return out

    chunks = _run(consume())
    assert chunks == ["a"]
    assert events[-1]["success"] is False


def test_trace_stream_metrics_sets_ttft_and_total() -> None:
    class Span:
        def __init__(self):
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def end(self):
            self.ended = True

    span = Span()

    async def stream():
        yield "first"
        yield "second"

    async def consume():
        return [c async for c in llm_client._trace_stream_metrics(stream(), span, 0.0)]

    chunks = _run(consume())
    assert chunks == ["first", "second"]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" in span.attrs
    assert span.ended is True


def test_trace_stream_metrics_without_nonempty_chunk_skips_ttft() -> None:
    class Span:
        def __init__(self):
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def end(self):
            self.ended = True

    span = Span()

    async def stream():
        yield ""

    async def consume():
        return [c async for c in llm_client._trace_stream_metrics(stream(), span, 0.0)]

    chunks = _run(consume())
    assert chunks == [""]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" not in span.attrs
    assert span.ended is True


async def _consume_async_iter(it, max_items: int = 20):
    out = []
    async for item in it:
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def test_semantic_cache_get_redis_none_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())

    async def _get_redis():
        return None

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    assert _run(manager.get("hello")) is None


def test_semantic_cache_get_handles_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    called = {"n": 0}

    class BoomRedis:
        async def lrange(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    async def _get_redis():
        return BoomRedis()

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0])
    monkeypatch.setattr(llm_client, "record_cache_redis_error", lambda: called.__setitem__("n", called["n"] + 1))
    assert _run(manager.get("hello")) is None
    assert called["n"] == 1


def test_semantic_cache_set_returns_without_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())

    async def _get_redis():
        return _FakeRedis()

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [])
    assert _run(manager.set("prompt", "resp")) is None


def test_semantic_cache_set_records_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    called = {"n": 0}

    class BoomRedis(_FakeRedis):
        async def lrange(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    async def _get_redis():
        return BoomRedis()

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0])
    monkeypatch.setattr(llm_client, "record_cache_redis_error", lambda: called.__setitem__("n", called["n"] + 1))
    _run(manager.set("prompt", "resp"))
    assert called["n"] == 1


def test_ollama_helpers_base_url_and_timeout() -> None:
    client = llm_client.OllamaClient(SimpleNamespace(OLLAMA_URL="http://host:11434/api", OLLAMA_TIMEOUT=5))
    assert client.base_url == "http://host:11434"
    assert client._build_timeout().connect == 10.0


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('data: {"choices":[{"delta":{"content":"A"}}]}', ["A"]),
        ("data: [DONE]", []),
    ],
)
def test_openai_stream_parser(monkeypatch: pytest.MonkeyPatch, line: str, expected: list[str]) -> None:
    client = llm_client.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=30, OPENAI_MODEL="m"))

    class Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield line

    class StreamCM:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_exc):
            return False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, *_args, **_kwargs):
            return StreamCM()

        async def aclose(self):
            return None

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)
    chunks = _run(_consume_async_iter(client._stream_openai({}, {}, llm_client.httpx.Timeout(10), True)))
    assert chunks == expected


def test_llmclient_constructor_and_helpers() -> None:
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=11)
    c = llm_client.LLMClient("ollama", cfg)
    assert c._ollama_base_url == "http://localhost:11434"
    assert c._build_ollama_timeout().connect == 10.0
    with pytest.raises(ValueError):
        llm_client.LLMClient("unknown", cfg)


def test_truncate_messages_for_local_model_keeps_last_and_system() -> None:
    cfg = SimpleNamespace(OLLAMA_CONTEXT_MAX_CHARS=500)
    c = llm_client.LLMClient("ollama", cfg)
    messages = [
        {"role": "system", "content": "s" * 600},
        {"role": "user", "content": "u" * 600},
        {"role": "assistant", "content": "a" * 600},
    ]
    out = c._truncate_messages_for_local_model(messages)
    assert sum(len(m["content"]) for m in out) <= 1200
    assert out[-1]["role"] == "assistant"


def test_anthropic_split_system_and_messages() -> None:
    system, conv = llm_client.AnthropicClient._split_system_and_messages(
        [
            {"role": "system", "content": "A"},
            {"role": "system", "content": "B"},
            {"role": "user", "content": "U"},
        ]
    )
    assert system == "A\n\nB"
    assert conv == [{"role": "user", "content": "U"}]


def test_litellm_candidate_models_dedup() -> None:
    cfg = SimpleNamespace(LITELLM_MODEL=" m1 ", OPENAI_MODEL="m2", LITELLM_FALLBACK_MODELS=["m2", "m1", "m3"])
    client = llm_client.LiteLLMClient(cfg)
    assert client._candidate_models(None) == ["m1", "m2", "m3"]


def test_openai_chat_returns_missing_key_error_stream() -> None:
    client = llm_client.OpenAIClient(SimpleNamespace(OPENAI_API_KEY="", OPENAI_MODEL="m", OPENAI_TIMEOUT=5))
    stream = _run(client.chat(messages=[{"role": "user", "content": "hi"}], stream=True))
    chunks = _run(_consume_async_iter(stream))
    assert "OPENAI_API_KEY" in chunks[0]


def test_gemini_chat_returns_missing_package_message() -> None:
    client = llm_client.GeminiClient(SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="g"))
    out = _run(client.chat(messages=[{"role": "user", "content": "hi"}], stream=False))
    assert "google-genai" in out


def test_llmclient_stream_records_cache_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(OLLAMA_CONTEXT_MAX_CHARS=1200)
    c = llm_client.LLMClient("ollama", cfg)
    called = {"n": 0}

    class FakeRouter:
        def select(self, messages, provider, model):
            return provider, model

    class FakeClient:
        async def chat(self, **_kwargs):
            async def gen():
                yield "ok"

            return gen()

    c._router = FakeRouter()
    c._client = FakeClient()
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(llm_client, "record_cache_skip", lambda: called.__setitem__("n", called["n"] + 1))

    stream = _run(c.chat(messages=[{"role": "user", "content": "hello"}], stream=True))
    chunks = _run(_consume_async_iter(stream))
    assert chunks == ["ok"]
    assert called["n"] == 1


def test_llmclient_non_stream_uses_cache_and_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(COST_ROUTING_TOKEN_COST_USD=1e-6)
    c = llm_client.LLMClient("openai", cfg)

    class FakeRouter:
        def select(self, messages, provider, model):
            return provider, model

    class FakeClient:
        async def chat(self, **_kwargs):
            return "response"

    class FakeCache:
        async def get(self, _prompt):
            return None

        async def set(self, prompt, response):
            self.last = (prompt, response)

    c._router = FakeRouter()
    c._client = FakeClient()
    c._semantic_cache = FakeCache()

    costs = []
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(llm_client, "record_routing_cost", lambda v: costs.append(v))

    out = _run(c.chat(messages=[{"role": "user", "content": "hello"}], stream=False))
    assert out == "response"
    assert c._semantic_cache.last == ("hello", "response")
    assert costs and costs[0] > 0


def test_llmclient_non_stream_cache_hit_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace()
    c = llm_client.LLMClient("openai", cfg)

    class FakeRouter:
        def select(self, messages, provider, model):
            return provider, model

    class FakeCache:
        async def get(self, _prompt):
            return "cached"

    class FakeClient:
        async def chat(self, **_kwargs):
            raise AssertionError("should not be called")

    c._router = FakeRouter()
    c._semantic_cache = FakeCache()
    c._client = FakeClient()
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)

    out = _run(c.chat(messages=[{"role": "user", "content": "hello"}], stream=False))
    assert out == "cached"
