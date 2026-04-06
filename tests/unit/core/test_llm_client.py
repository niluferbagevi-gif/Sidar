from __future__ import annotations

import asyncio
import json
import sys
import types
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


class _FakeResponse:
    def __init__(self, *, payload=None, lines=None, bytes_chunks=None, status_ok=True):
        self._payload = payload or {}
        self._lines = lines or []
        self._bytes_chunks = bytes_chunks or []
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            err = Exception("http")
            setattr(err, "status_code", 500)
            raise err

    def json(self):
        return self._payload

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aiter_bytes(self):
        for chunk in self._bytes_chunks:
            yield chunk


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *_exc):
        return False


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self._post_response = kwargs.pop("_post_response", None)
        self._get_response = kwargs.pop("_get_response", None)
        self._stream_response = kwargs.pop("_stream_response", None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **_kwargs):
        return self._post_response or _FakeResponse(payload={})

    async def get(self, *_args, **_kwargs):
        return self._get_response or _FakeResponse(payload={})

    def stream(self, *_args, **_kwargs):
        return _FakeStreamCM(self._stream_response or _FakeResponse())

    async def aclose(self):
        return None


def test_ollama_client_chat_non_stream_and_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(CODING_MODEL="m1", OLLAMA_URL="http://x/api", USE_GPU=True, OLLAMA_TIMEOUT=30, ENABLE_TRACING=False)
    client = llm_client.OllamaClient(cfg)

    class _AC(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            return _FakeResponse(payload={"message": {"content": '{"tool":"final_answer","argument":"ok","thought":"t"}'}})

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    out = _run(client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True))
    assert "final_answer" in out

    async def fake_stream(*_a, **_k):
        yield "a"

    monkeypatch.setattr(client, "_stream_response", fake_stream)
    streamed = _run(client.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False))
    assert _run(_collect(streamed)) == ["a"]


async def _collect(gen):
    return [x async for x in gen]


def test_ollama_stream_response_parses_and_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config()
    client = llm_client.OllamaClient(cfg)

    class _AC(_FakeAsyncClient):
        def stream(self, *_a, **_kw):
            lines = b'{"message":{"content":"A"}}\ninvalid\n{"message":{"content":"B"}}'
            return _FakeStreamCM(_FakeResponse(bytes_chunks=[lines]))

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    chunks = _run(_collect(client._stream_response("u", {}, llm_client.httpx.Timeout(10, connect=1))))
    assert chunks == ["A", "B"]

    async def broken(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", broken)
    fallback = _run(_collect(client._stream_response("u", {}, llm_client.httpx.Timeout(10, connect=1))))
    assert "HATA" in fallback[0]


def test_ollama_list_models_and_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    client = llm_client.OllamaClient(_make_config())

    class _AC(_FakeAsyncClient):
        async def get(self, *_a, **_kw):
            return _FakeResponse(payload={"models": [{"name": "m1"}]})

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    assert _run(client.list_models()) == ["m1"]
    assert _run(client.is_available()) is True


def test_openai_client_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    no_key_cfg = _make_config(OPENAI_API_KEY="")
    c1 = llm_client.OpenAIClient(no_key_cfg)
    assert "OPENAI_API_KEY" in _run(c1.chat([{"role": "user", "content": "x"}], stream=False))

    cfg = _make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-x", OPENAI_TIMEOUT=20, ENABLE_TRACING=False)
    c2 = llm_client.OpenAIClient(cfg)

    class _AC(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            return _FakeResponse(payload={"usage": {"prompt_tokens": 1, "completion_tokens": 2}, "choices": [{"message": {"content": "ok"}}]})

    metrics = []
    monkeypatch.setattr(llm_client, "_record_llm_metric", lambda **kw: metrics.append(kw))
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    out = _run(c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False))
    assert out == "ok"
    assert metrics[-1]["success"] is True


def test_openai_stream_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(OPENAI_API_KEY="k")
    c = llm_client.OpenAIClient(cfg)

    class _AC(_FakeAsyncClient):
        def stream(self, *_a, **_kw):
            lines = [
                "data: {\"choices\":[{\"delta\":{\"content\":\"A\"}}]}",
                "data: invalid",
                "data: [DONE]",
            ]
            return _FakeStreamCM(_FakeResponse(lines=lines))

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    chunks = _run(_collect(c._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=False)))
    assert chunks == ["A"]


def test_litellm_candidate_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(LITELLM_GATEWAY_URL="", LITELLM_MODEL="m", OPENAI_MODEL="o")
    c = llm_client.LiteLLMClient(cfg)
    assert c._candidate_models(None) == ["m"]
    assert "LITELLM_GATEWAY_URL" in _run(c.chat([{"role": "user", "content": "x"}], stream=False))

    cfg2 = _make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_API_KEY="k", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c2 = llm_client.LiteLLMClient(cfg2)

    class _AC(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            return _FakeResponse(payload={"usage": {}, "choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    out = _run(c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False))
    assert out == "ok"


def test_litellm_stream_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c = llm_client.LiteLLMClient(cfg)

    class _AC(_FakeAsyncClient):
        def stream(self, *_a, **_kw):
            return _FakeStreamCM(_FakeResponse(lines=["data: {\"choices\":[{\"delta\":{\"content\":\"A\"}}]}", "data: [DONE]"]))

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    got = _run(_collect(c._stream_openai_compatible("e", {}, {}, llm_client.httpx.Timeout(10, connect=1), False)))
    assert got == ["A"]

    async def broken(*_a, **_kw):
        raise Exception("x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", broken)
    got2 = _run(_collect(c._stream_openai_compatible("e", {}, {}, llm_client.httpx.Timeout(10, connect=1), True)))
    assert "LiteLLM" in got2[0]


def test_gemini_client_missing_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(GEMINI_API_KEY="", GEMINI_MODEL="g")
    c = llm_client.GeminiClient(cfg)
    msg = _run(c.chat([{"role": "user", "content": "x"}], stream=False))
    assert "Gemini istemcisi kurulu" in msg or "GEMINI_API_KEY" in msg

    class _Resp:
        text = "hello"

    class _Models:
        async def generate_content(self, **_kw):
            return _Resp()

        async def generate_content_stream(self, **_kw):
            async def gen():
                yield SimpleNamespace(text="A")
            return gen()

    class _Client:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = SimpleNamespace(models=_Models())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(genai=types.SimpleNamespace(Client=_Client)))
    monkeypatch.setitem(sys.modules, "google.genai", types.SimpleNamespace(types=fake_types))
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    cfg2 = _make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm")
    c2 = llm_client.GeminiClient(cfg2)
    assert _run(c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)) == "hello"
    stream = _run(c2.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False))
    assert _run(_collect(stream)) == ["A"]


def test_anthropic_helpers_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY=""))
    assert "ANTHROPIC_API_KEY" in _run(c.chat([{"role": "user", "content": "x"}], stream=False))
    system, convo = c._split_system_and_messages([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
    assert system == "s"
    assert convo[0]["role"] == "user"

    class _Usage:
        input_tokens = 1
        output_tokens = 2

    class _MsgResp:
        usage = _Usage()
        content = [SimpleNamespace(text="ok")]

    class _Messages:
        async def create(self, **_kw):
            return _MsgResp()

        def stream(self, **_kw):
            class _CM:
                async def __aenter__(self):
                    async def gen():
                        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="A"))
                    return gen()

                async def __aexit__(self, *_exc):
                    return False

            return _CM()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    mod = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    cfg = _make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude")
    c2 = llm_client.AnthropicClient(cfg)
    assert _run(c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)) == "ok"
    s = _run(c2.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False))
    assert _run(_collect(s)) == ["A"]


def test_llmclient_wrapper_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(OLLAMA_URL="http://localhost:11434/api")
    client = llm_client.LLMClient("ollama", cfg)
    assert "11434" in client._ollama_base_url
    assert client._build_ollama_timeout().connect == 10.0
    assert client._truncate_messages_for_local_model([]) == []

    msgs = [{"role": "system", "content": "s" * 400}, {"role": "user", "content": "u" * 1000}, {"role": "assistant", "content": "a" * 1000}]
    truncated = client._truncate_messages_for_local_model(msgs)
    assert sum(len(m["content"]) for m in truncated) <= getattr(cfg, "OLLAMA_CONTEXT_MAX_CHARS", 12000)

    async def fake_chat(**_kw):
        return "resp"

    monkeypatch.setattr(client._router, "select", lambda *_a: ("ollama", None))
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(client._semantic_cache, "get", lambda *_a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(client._semantic_cache, "set", lambda *_a: asyncio.sleep(0))
    monkeypatch.setattr(client._client, "chat", fake_chat)
    assert _run(client.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False)) == "resp"

    monkeypatch.setattr(client._semantic_cache, "get", lambda *_a: asyncio.sleep(0, result="cached"))
    assert _run(client.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False)) == "cached"

    async def fake_stream_chat(**_kw):
        async def g():
            yield "x"
        return g()

    monkeypatch.setattr(client._client, "chat", fake_stream_chat)
    chunks = _run(_collect(_run(client.chat([{"role": "user", "content": "hello"}], stream=True, json_mode=False))))
    assert chunks == ["x"]

    monkeypatch.setattr(client._client, "list_models", lambda: asyncio.sleep(0, result=["model-a"]))
    monkeypatch.setattr(client._client, "is_available", lambda: asyncio.sleep(0, result=True))
    assert _run(client.list_ollama_models()) == ["model-a"]
    assert _run(client.is_ollama_available()) is True


def test_semantic_cache_manager_edge_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(ENABLE_SEMANTIC_CACHE=False)
    manager = llm_client._SemanticCacheManager(cfg)
    assert _run(manager._get_redis()) is None

    cfg2 = _make_config(ENABLE_SEMANTIC_CACHE=True)
    manager2 = llm_client._SemanticCacheManager(cfg2)

    class _R:
        @staticmethod
        def from_url(*_a, **_kw):
            class _Inst:
                async def ping(self):
                    return True
            return _Inst()

    monkeypatch.setattr(llm_client, "Redis", _R)
    assert _run(manager2._get_redis()) is not None
    # ikinci çağrı cache'ten dönmeli
    assert _run(manager2._get_redis()) is manager2._redis

    class _RBoom:
        @staticmethod
        def from_url(*_a, **_kw):
            class _Inst:
                async def ping(self):
                    raise RuntimeError("redis down")
            return _Inst()

    manager3 = llm_client._SemanticCacheManager(cfg2)
    monkeypatch.setattr(llm_client, "Redis", _RBoom)
    assert _run(manager3._get_redis()) is None

    # embed import hatasında [] dönmeli
    real_import = __import__

    def _imp(name, *args, **kwargs):
        if name == "core.rag":
            raise ImportError("x")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _imp)
    assert manager3._embed_prompt("p") == []


def test_semantic_cache_get_set_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    fake = _FakeRedis()

    async def _redis():
        return fake

    monkeypatch.setattr(manager, "_get_redis", _redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])
    assert _run(manager.get("x")) is None

    class _BrokenRedis(_FakeRedis):
        async def lrange(self, *_a, **_kw):
            raise RuntimeError("boom")

    br = _BrokenRedis()

    async def _redis2():
        return br

    monkeypatch.setattr(manager, "_get_redis", _redis2)
    assert _run(manager.get("x")) is None

    # set: vector boş -> no-op
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [])
    assert _run(manager.set("p", "r")) is None


def test_ollama_and_openai_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(CODING_MODEL="m1", OLLAMA_URL="http://x")
    oc = llm_client.OllamaClient(cfg)

    class _ACBoom(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            raise RuntimeError("fail")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _ACBoom)
    with pytest.raises(llm_client.LLMAPIError):
        _run(oc.chat([{"role": "user", "content": "x"}], stream=False))

    class _ACFailGet(_FakeAsyncClient):
        async def get(self, *_a, **_kw):
            raise RuntimeError("x")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _ACFailGet)
    assert _run(oc.list_models()) == []
    assert _run(oc.is_available()) is False

    # openai stream hata yolu
    oa = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k"))

    async def _retry_boom(*_a, **_kw):
        raise RuntimeError("stream boom")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_boom)
    got = _run(_collect(oa._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=True)))
    assert "OpenAI" in got[0]


def test_litellm_fallback_raise_and_successive_model(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c = llm_client.LiteLLMClient(cfg)
    state = {"n": 0}

    class _AC(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("first failed")
            return _FakeResponse(payload={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _AC)
    assert _run(c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)) == "ok"

    class _ACAllFail(_FakeAsyncClient):
        async def post(self, *_a, **_kw):
            raise RuntimeError("all failed")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _ACAllFail)
    with pytest.raises(llm_client.LLMAPIError):
        _run(c.chat([{"role": "user", "content": "x"}], stream=False))


def test_gemini_stream_generator_error_and_key_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        text = "ok"

    class _Models:
        async def generate_content(self, **_kw):
            return _Resp()

    class _Client:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = SimpleNamespace(models=_Models())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(genai=types.SimpleNamespace(Client=_Client)))
    monkeypatch.setitem(sys.modules, "google.genai", types.SimpleNamespace(types=fake_types))
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="", GEMINI_MODEL="g"))
    assert "GEMINI_API_KEY" in _run(c.chat([{"role": "user", "content": "x"}], stream=False))

    async def broken_stream():
        raise RuntimeError("bad")
        yield "x"  # pragma: no cover

    chunks = _run(_collect(c._stream_gemini_generator(broken_stream())))
    assert "Gemini" in chunks[0] and "HATA" in chunks[0]


def test_anthropic_import_error_and_stream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k"))
    monkeypatch.setitem(sys.modules, "anthropic", None)
    msg = _run(c.chat([{"role": "user", "content": "x"}], stream=False))
    assert "anthropic paketi" in msg

    class _Messages:
        def stream(self, **_kw):
            class _CM:
                async def __aenter__(self):
                    raise RuntimeError("open fail")

                async def __aexit__(self, *_exc):
                    return False

            return _CM()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    c2 = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k"))
    out = _run(_collect(c2._stream_anthropic(_AsyncAnthropic(), "m", [{"role": "user", "content": "u"}], "", 0.1, True)))
    assert "Anthropic" in out[0]


def test_llmclient_routing_and_compat_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(OPENAI_API_KEY="k")
    c = llm_client.LLMClient("openai", cfg)

    # route başka provider'a gider ve hata verirse fallback provider'da devam eder
    monkeypatch.setattr(c._router, "select", lambda *_a: ("invalid-provider", "m"))
    async def _fallback(**_kw):
        return "ok"

    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(c._semantic_cache, "get", lambda *_a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(c._semantic_cache, "set", lambda *_a: asyncio.sleep(0))
    monkeypatch.setattr(c._client, "chat", _fallback)
    monkeypatch.setattr(llm_client, "record_routing_cost", lambda *_a, **_kw: None)
    assert _run(c.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False)) == "ok"

    # stream mode'da cache skip path
    called = {"n": 0}
    monkeypatch.setattr(llm_client, "record_cache_skip", lambda: called.__setitem__("n", called["n"] + 1))

    async def _stream(**_kw):
        async def g():
            yield "s"
        return g()

    monkeypatch.setattr(c._client, "chat", _stream)
    stream = _run(c.chat([{"role": "user", "content": "hello"}], stream=True, json_mode=False))
    assert _run(_collect(stream)) == ["s"]
    assert called["n"] == 1

    # compat gemini stream helper (provider gemini değilken de çalışmalı)
    async def _gen():
        yield SimpleNamespace(text="t1")
    assert _run(_collect(c._stream_gemini_generator(_gen()))) == ["t1"]
