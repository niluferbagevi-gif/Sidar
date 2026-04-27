from __future__ import annotations

import ast
import asyncio
import builtins
import hashlib
import importlib
import json
import pathlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from redis import exceptions as redis_exceptions

import core.llm_client as llm_client
from tests.helpers import collect_async_chunks as _collect
from tests.helpers import make_test_config as _make_config


def test_llm_client_sets_redis_none_when_redis_asyncio_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = pathlib.Path(llm_client.__file__)
    module_name = "core.llm_client_no_redis"
    original_import = builtins.__import__

    def _failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis.asyncio":
            raise ImportError("redis unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    monkeypatch.delitem(sys.modules, module_name, raising=False)

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.Redis is None


def _patch_imports(monkeypatch: pytest.MonkeyPatch, module_map: dict[str, object]) -> None:
    for name, module in module_map.items():
        if isinstance(module, Exception):
            monkeypatch.setitem(sys.modules, name, None)
            continue
        monkeypatch.setitem(sys.modules, name, module)


class DummyGeminiResponse:
    def __init__(self, text: str = "ok") -> None:
        self.text = text


class DummyGeminiModels:
    def __init__(self, text: str = "ok", stream_texts: tuple[str, ...] = ("A",)) -> None:
        self._text = text
        self._stream_texts = stream_texts

    async def generate_content(self, **_kw):
        return DummyGeminiResponse(self._text)

    async def generate_content_stream(self, **_kw):
        async def gen():
            for text in self._stream_texts:
                yield SimpleNamespace(text=text)

        return gen()


class DummyGeminiClient:
    def __init__(self, api_key: str, text: str = "ok", stream_texts: tuple[str, ...] = ("A",)) -> None:
        self.api_key = api_key
        self.aio = SimpleNamespace(models=DummyGeminiModels(text=text, stream_texts=stream_texts))


def _mock_google_genai(monkeypatch: pytest.MonkeyPatch, client_cls: type, fake_types: object) -> None:
    try:
        google_genai_mod = importlib.import_module("google.genai")
        google_genai_types_mod = importlib.import_module("google.genai.types")
    except ImportError as exc:
        pytest.skip(f"google-genai import edilemedi: {exc}")
    monkeypatch.setattr(google_genai_mod, "Client", client_cls, raising=True)
    monkeypatch.setattr(
        google_genai_types_mod,
        "GenerateContentConfig",
        getattr(fake_types, "GenerateContentConfig"),
        raising=True,
    )


def _mock_anthropic(monkeypatch: pytest.MonkeyPatch, async_anthropic_cls: type) -> None:
    try:
        anthropic_mod = importlib.import_module("anthropic")
    except ImportError as exc:
        pytest.skip(f"anthropic import edilemedi: {exc}")
    monkeypatch.setattr(anthropic_mod, "AsyncAnthropic", async_anthropic_cls, raising=True)


async def _cache_put(redis, manager: llm_client._SemanticCacheManager, key: str, embedding: list[float], response: str) -> None:
    await redis.hset(key, mapping={"embedding": json.dumps(embedding), "response": response})
    await redis.lpush(manager.index_key, key)


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
@pytest.mark.asyncio
async def test_build_provider_json_mode_config(provider: str, key: str | None) -> None:
    data = llm_client.build_provider_json_mode_config(provider)
    if key is None:
        assert data == {}
    else:
        assert key in data


@pytest.mark.asyncio
async def test_ensure_json_text_returns_original_for_valid_json() -> None:
    text = '{"tool": "final_answer", "argument": "ok", "thought": "t"}'
    assert llm_client._ensure_json_text(text, "OpenAI") == text


@pytest.mark.asyncio
async def test_ensure_json_text_wraps_invalid_payload() -> None:
    wrapped = llm_client._ensure_json_text("plain-text", "Gemini")
    data = json.loads(wrapped)
    assert data["tool"] == "final_answer"
    assert data["argument"] == "plain-text"


@pytest.mark.asyncio
async def test_ensure_json_text_logs_warning_for_invalid_payload(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        llm_client._ensure_json_text("plain-text", "Gemini")
    assert any("JSON dışı yanıt alındı" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_extract_usage_tokens_supports_prompt_and_output_tokens() -> None:
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 12, "completion_tokens": 34}}) == (12, 34)
    assert llm_client._extract_usage_tokens({"usage": {"prompt_tokens": 1, "output_tokens": 3}}) == (1, 3)
    assert llm_client._extract_usage_tokens("invalid") == (0, 0)


@pytest.mark.asyncio
async def test_is_retryable_exception_for_timeout_and_status() -> None:
    retryable, status = llm_client._is_retryable_exception(httpx.TimeoutException("x"))
    assert retryable is True
    assert status is None

    exc = Exception("boom")
    setattr(exc, "status_code", 503)
    retryable, status = llm_client._is_retryable_exception(exc)
    assert retryable is True
    assert status == 503


@pytest.mark.asyncio
async def test_is_retryable_exception_for_network_errors() -> None:
    retryable, status = llm_client._is_retryable_exception(httpx.ConnectError("Connection refused"))
    assert retryable is True
    assert status is None

    retryable, status = llm_client._is_retryable_exception(httpx.ReadError("Read timeout"))
    assert retryable is True
    assert status is None


@pytest.mark.asyncio
async def test_is_retryable_exception_for_non_retryable_status() -> None:
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


@pytest.mark.asyncio
async def test_dummy_client_methods_are_callable() -> None:
    client = _DummyClient(_make_config())
    assert client.json_mode_config() == {}
    assert await client.chat([{"role": "user", "content": "u"}]) == "ok"


@pytest.mark.asyncio
async def test_inject_json_instruction_handles_existing_and_missing_system() -> None:
    with_system = [{"role": "system", "content": "base"}, {"role": "user", "content": "u"}]
    out = _DummyClient._inject_json_instruction(with_system)
    assert out[0]["content"].startswith("base")
    assert llm_client.SIDAR_TOOL_JSON_INSTRUCTION in out[0]["content"]

    without_system = [{"role": "user", "content": "u"}]
    out2 = _DummyClient._inject_json_instruction(without_system)
    assert out2[0]["role"] == "system"
    assert llm_client.SIDAR_TOOL_JSON_INSTRUCTION in out2[0]["content"]


@pytest.mark.asyncio
async def test_retry_with_backoff_succeeds_after_retry(monkeypatch: pytest.MonkeyPatch, mock_config) -> None:
    monkeypatch.setattr(llm_client.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(llm_client.random, "uniform", lambda *_args, **_kwargs: 0.0)
    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] == 1:
            err = Exception("temp")
            setattr(err, "status_code", 429)
            raise err
        return "done"

    result = await llm_client._retry_with_backoff("openai", op, config=mock_config(), retry_hint="retry")
    assert result == "done"
    assert state["n"] == 2


@pytest.mark.asyncio
async def test_retry_with_backoff_recovers_from_transient_external_api_outage(
    monkeypatch: pytest.MonkeyPatch,
    mock_config,
) -> None:
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(llm_client.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm_client.random, "uniform", lambda *_args, **_kwargs: 0.0)

    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("temporary upstream outage")
        return {"ok": True}

    result = await llm_client._retry_with_backoff("openai", op, config=mock_config(), retry_hint="retry")

    assert result == {"ok": True}
    assert state["n"] == 2
    assert sleep_calls == [pytest.approx(0.05)]


@pytest.mark.asyncio
async def test_retry_with_backoff_uses_base_delay_scaled_jitter(monkeypatch: pytest.MonkeyPatch, mock_config) -> None:
    jitter_args: list[tuple[float, float]] = []

    async def _fake_sleep(_delay: float) -> None:
        return None

    def _fake_uniform(low: float, high: float) -> float:
        jitter_args.append((low, high))
        return 0.0

    monkeypatch.setattr(llm_client.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm_client.random, "uniform", _fake_uniform)

    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("temporary upstream outage")
        return {"ok": True}

    await llm_client._retry_with_backoff("openai", op, config=mock_config(), retry_hint="retry")
    assert len(jitter_args) == 1
    assert jitter_args[0][0] == 0.0
    assert jitter_args[0][1] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_retry_with_backoff_raises_llm_api_error(mock_config) -> None:
    async def op():
        raise ValueError("fatal")

    with pytest.raises(llm_client.LLMAPIError, match="fatal") as exc:
        await llm_client._retry_with_backoff("openai", op, config=mock_config(), retry_hint="retry")

    assert exc.value.provider == "openai"
    assert exc.value.retryable is False
    assert "fatal" in str(exc.value)


@pytest.mark.asyncio
async def test_get_tracer_uses_trace_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    fake_trace = SimpleNamespace(get_tracer=lambda _name: token)
    monkeypatch.setattr(llm_client, "trace", fake_trace)
    assert llm_client._get_tracer(SimpleNamespace(ENABLE_TRACING=True)) is token


@pytest.mark.asyncio
async def test_fallback_stream_single_chunk() -> None:
    async def consume():
        return [c async for c in llm_client._fallback_stream("err")]

    assert await consume() == ["err"]


@pytest.mark.asyncio
async def test_record_llm_metric_forwards_metrics_user(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.asyncio
async def test_semantic_cache_cosine_similarity(mock_config) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    assert manager._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert manager._cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert manager._cosine_similarity([], [1.0]) == 0.0


@pytest.mark.asyncio
async def test_semantic_cache_default_threshold_is_less_strict(mock_config) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    assert manager.threshold == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_semantic_cache_get_hit(monkeypatch: pytest.MonkeyPatch, mock_config, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    await _cache_put(fake_redis, manager, "k1", [1.0, 0.0], "cached")

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])

    assert await manager.get("hello") == "cached"


@pytest.mark.asyncio
async def test_semantic_cache_get_returns_none_without_prompt(mock_config) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    assert await manager.get("") is None


@pytest.mark.asyncio
async def test_semantic_cache_get_records_miss(monkeypatch: pytest.MonkeyPatch, mock_config, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(mock_config(SEMANTIC_CACHE_THRESHOLD=0.99))
    await _cache_put(fake_redis, manager, "k1", [1.0, 0.0], "cached")
    misses = {"n": 0}

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [0.0, 1.0])
    monkeypatch.setattr(llm_client, "record_cache_miss", lambda: misses.__setitem__("n", misses["n"] + 1))
    assert await manager.get("hello") is None
    assert misses["n"] == 1


@pytest.mark.asyncio
async def test_semantic_cache_set_records_item(monkeypatch: pytest.MonkeyPatch, mock_config, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    await fake_redis.lpush(manager.index_key, "old2")
    await fake_redis.lpush(manager.index_key, "old1")
    await fake_redis.hset("old1", mapping={"embedding": json.dumps([0.9, 0.1]), "response": "old"})
    await fake_redis.hset("old2", mapping={"embedding": json.dumps([0.8, 0.2]), "response": "old"})

    async def _get_redis():
        return fake_redis

    counters = {"eviction": 0}
    pipeline = fake_redis.pipeline(transaction=True)
    expire_spy = MagicMock(wraps=pipeline.expire)
    monkeypatch.setattr(manager, "_get_redis", _get_redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [0.1, 0.2])
    monkeypatch.setattr(llm_client, "record_cache_eviction", lambda: counters.__setitem__("eviction", counters["eviction"] + 1))
    monkeypatch.setattr(pipeline, "expire", expire_spy)
    monkeypatch.setattr(fake_redis, "pipeline", lambda transaction=True: pipeline)

    await manager.set("prompt", "resp")

    item_key = "sidar:semantic_cache:item:" + hashlib.sha256("prompt".encode("utf-8")).hexdigest()
    expire_spy.assert_called_once_with(item_key, manager.ttl)
    assert await fake_redis.llen(manager.index_key) == 2
    keys = await fake_redis.lrange(manager.index_key, 0, -1)

    async def _scan_response(entries: list[str], needle: str) -> bool:
        for key in entries:
            if (await fake_redis.hgetall(key)).get("response") == needle:
                return True
        return False

    assert await _scan_response(keys, "resp") is True
    assert await _scan_response(keys, "not-found") is False

    await fake_redis.hset("manual-not-found", mapping={"embedding": json.dumps([0.2, 0.8]), "response": "not-found"})
    await fake_redis.lpush(manager.index_key, "manual-not-found")
    keys_with_manual = await fake_redis.lrange(manager.index_key, 0, -1)
    assert await _scan_response(keys_with_manual, "not-found") is True
    assert counters["eviction"] == 1


@pytest.mark.asyncio
async def test_semantic_cache_set_skips_without_response(mock_config) -> None:
    manager = llm_client._SemanticCacheManager(mock_config())
    assert await manager.set("prompt", "") is None


@pytest.mark.asyncio
async def test_track_stream_completion_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
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

    chunks = await consume()
    assert chunks == ["a"]
    assert events[-1]["success"] is False


@pytest.mark.asyncio
async def test_trace_stream_metrics_sets_ttft_and_total() -> None:
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

    chunks = await consume()
    assert chunks == ["first", "second"]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" in span.attrs
    assert span.ended is True


@pytest.mark.asyncio
async def test_trace_stream_metrics_without_nonempty_chunk_skips_ttft() -> None:
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

    chunks = await consume()
    assert chunks == [""]
    assert "sidar.llm.total_ms" in span.attrs
    assert "sidar.llm.ttft_ms" not in span.attrs
    assert span.ended is True


@pytest.mark.asyncio
async def test_ollama_client_chat_non_stream_and_stream(
    monkeypatch: pytest.MonkeyPatch, mock_config, respx_mock_router
) -> None:
    cfg = mock_config(CODING_MODEL="m1", OLLAMA_URL="http://x/api", USE_GPU=True, OLLAMA_TIMEOUT=30, ENABLE_TRACING=False)
    client = llm_client.OllamaClient(cfg)
    respx_mock_router.post("http://x/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": '{"tool":"final_answer","argument":"ok","thought":"t"}'}})
    )
    out = await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True)
    assert "final_answer" in out

    async def fake_stream(*_a, **_k):
        yield "a"

    monkeypatch.setattr(client, "_stream_response", fake_stream)
    streamed = await client.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False)
    assert await _collect(streamed) == ["a"]


@pytest.mark.asyncio
async def test_ollama_client_chat_sends_num_gpu_when_use_gpu_enabled(mock_config, respx_mock_router) -> None:
    cfg = mock_config(CODING_MODEL="m1", OLLAMA_URL="http://x/api", USE_GPU=True, OLLAMA_TIMEOUT=30, ENABLE_TRACING=False)
    client = llm_client.OllamaClient(cfg)
    route = respx_mock_router.post("http://x/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "ok"}})
    )

    _ = await client.chat([{"role": "user", "content": "Merhaba"}], stream=False, json_mode=False)

    payload = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert "options" in payload
    assert payload["options"].get("num_gpu") == -1


@pytest.mark.asyncio
async def test_ollama_stream_response_parses_and_handles_error(
    mock_config, respx_mock_router
) -> None:
    cfg = mock_config()
    client = llm_client.OllamaClient(cfg)
    stream_payload = "{\"message\":{\"content\":\"A\"}}\ninvalid\n{\"message\":{\"content\":\"B\"}}"
    stream_endpoint = "http://localhost:11434/api/chat"
    respx_mock_router.post(stream_endpoint).mock(
        return_value=httpx.Response(200, text=stream_payload)
    )
    chunks = await _collect(client._stream_response(stream_endpoint, {}, llm_client.httpx.Timeout(10, connect=1)))
    assert chunks == ["A", "B"]

    respx_mock_router.post(stream_endpoint).mock(side_effect=httpx.ConnectTimeout("connect timeout"))
    fallback = await _collect(client._stream_response(stream_endpoint, {}, llm_client.httpx.Timeout(10, connect=1)))
    assert "HATA" in fallback[0]


@pytest.mark.asyncio
async def test_ollama_list_models_and_availability(mock_config, respx_mock_router) -> None:
    client = llm_client.OllamaClient(mock_config())
    respx_mock_router.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "m1"}]})
    )
    assert await client.list_models() == ["m1"]
    assert await client.is_available() is True


@pytest.mark.asyncio
async def test_openai_client_paths(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    no_key_cfg = _make_config(OPENAI_API_KEY="")
    c1 = llm_client.OpenAIClient(no_key_cfg)
    assert "OPENAI_API_KEY" in await c1.chat([{"role": "user", "content": "x"}], stream=False)

    cfg = _make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-x", OPENAI_TIMEOUT=20, ENABLE_TRACING=False)
    c2 = llm_client.OpenAIClient(cfg)
    metrics = []
    monkeypatch.setattr(llm_client, "_record_llm_metric", lambda **kw: metrics.append(kw))
    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                "choices": [{"message": {"content": "ok"}}],
            },
        )
    )
    out = await c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert out == "ok"
    assert metrics[-1]["success"] is True


@pytest.mark.asyncio
async def test_openai_context_limit_error_is_non_retryable(respx_mock_router) -> None:
    cfg = _make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-x", ENABLE_TRACING=False)
    client = llm_client.OpenAIClient(cfg)
    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": "maximum context length reached",
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded",
                }
            },
        )
    )
    with pytest.raises(llm_client.LLMAPIError, match="maximum context length reached") as exc:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)

    assert exc.value.provider == "openai"
    assert exc.value.status_code == 400
    assert exc.value.retryable is False
    assert "maximum context length reached" in str(exc.value)


@pytest.mark.asyncio
async def test_ollama_context_limit_error_is_non_retryable(respx_mock_router) -> None:
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434"))
    respx_mock_router.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(400, json={"error": "context length exceeded"})
    )

    with pytest.raises(llm_client.LLMAPIError, match="Ollama isteği başarısız") as exc:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)

    assert exc.value.provider == "ollama"
    assert exc.value.status_code == 400
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_ollama_missing_model_error_suggests_pull_command(respx_mock_router) -> None:
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434", CODING_MODEL="qwen2.5-coder:7b"))
    respx_mock_router.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(404, json={"error": "model 'qwen2.5-coder:7b' not found"})
    )

    with pytest.raises(llm_client.LLMAPIError, match="ollama pull qwen2.5-coder:7b") as exc:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)

    assert exc.value.provider == "ollama"
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_ollama_stream_missing_model_emits_runtime_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434", CODING_MODEL="qwen2.5-coder:7b"))

    class _DummyResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"error":"model \\"qwen2.5-coder:7b\\" not found"}\n'

    class _DummyCM:
        async def __aenter__(self):
            return _DummyResp()

        async def __aexit__(self, *_args):
            return None

    class _DummyClient:
        def stream(self, *_args, **_kwargs):
            return _DummyCM()

        async def aclose(self):
            return None

    async def _fake_retry(_provider, operation, *, config, retry_hint):  # noqa: ARG001
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _fake_retry)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda timeout: _DummyClient())  # noqa: ARG005

    chunks = await _collect(
        client._stream_response(
            "http://localhost:11434/api/chat",
            {"model": "qwen2.5-coder:7b", "messages": [], "stream": True},
            llm_client.httpx.Timeout(10, connect=1),
        )
    )
    assert chunks
    assert "ollama pull qwen2.5-coder:7b" in chunks[0]


@pytest.mark.asyncio
async def test_openai_stream_parser(respx_mock_router) -> None:
    cfg = _make_config(OPENAI_API_KEY="k")
    c = llm_client.OpenAIClient(cfg)
    stream_text = "\n".join([
        'data: {"choices":[{"delta":{"content":"A"}}]}',
        'data: invalid',
        'data: [DONE]',
    ])
    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=stream_text)
    )
    chunks = await _collect(c._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=False))
    assert chunks == ["A"]


@pytest.mark.asyncio
async def test_litellm_candidate_and_chat(mock_config, respx_mock_router) -> None:
    cfg = mock_config(LITELLM_GATEWAY_URL="", LITELLM_MODEL="m", OPENAI_MODEL="o")
    c = llm_client.LiteLLMClient(cfg)
    assert c._candidate_models(None) == ["m"]
    assert "LITELLM_GATEWAY_URL" in await c.chat([{"role": "user", "content": "x"}], stream=False)

    cfg2 = mock_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_API_KEY="k", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c2 = llm_client.LiteLLMClient(cfg2)
    respx_mock_router.post("http://gw/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {}, "choices": [{"message": {"content": "ok"}}]})
    )
    out = await c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert out == "ok"


@pytest.mark.asyncio
async def test_litellm_stream_and_fail(monkeypatch: pytest.MonkeyPatch, mock_config, respx_mock_router) -> None:
    cfg = mock_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c = llm_client.LiteLLMClient(cfg)
    stream_text = "\n".join(["data: {\"choices\":[{\"delta\":{\"content\":\"A\"}}]}", "data: [DONE]"])
    stream_endpoint = "http://gw/chat/completions"
    respx_mock_router.post(stream_endpoint).mock(return_value=httpx.Response(200, text=stream_text))
    got = await _collect(
        c._stream_openai_compatible(stream_endpoint, {}, {}, llm_client.httpx.Timeout(10, connect=1), False)
    )
    assert got == ["A"]

    async def broken(*_a, **_kw):
        raise Exception("x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", broken)
    got2 = await _collect(
        c._stream_openai_compatible(stream_endpoint, {}, {}, llm_client.httpx.Timeout(10, connect=1), True)
    )
    assert "LiteLLM" in got2[0]


@pytest.mark.asyncio
async def test_gemini_client_missing_and_success(monkeypatch: pytest.MonkeyPatch, mock_config) -> None:
    cfg = mock_config(GEMINI_API_KEY="", GEMINI_MODEL="g")
    c = llm_client.GeminiClient(cfg)
    msg = await c.chat([{"role": "user", "content": "x"}], stream=False)
    assert "Gemini istemcisi kurulu" in msg or "GEMINI_API_KEY" in msg

    class _Client(DummyGeminiClient):
        def __init__(self, api_key):
            super().__init__(api_key, text="hello", stream_texts=("A",))

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)
    cfg2 = mock_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm")
    c2 = llm_client.GeminiClient(cfg2)
    assert await c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False) == "hello"
    stream = await c2.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False)
    assert await _collect(stream) == ["A"]


@pytest.mark.asyncio
async def test_anthropic_helpers_and_chat(monkeypatch: pytest.MonkeyPatch, mock_config) -> None:
    c = llm_client.AnthropicClient(mock_config(ANTHROPIC_API_KEY=""))
    assert "ANTHROPIC_API_KEY" in await c.chat([{"role": "user", "content": "x"}], stream=False)
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

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    cfg = mock_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude")
    c2 = llm_client.AnthropicClient(cfg)
    assert await c2.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False) == "ok"
    s = await c2.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False)
    assert await _collect(s) == ["A"]


@pytest.mark.asyncio
async def test_anthropic_context_limit_error_is_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ContextLimitError(Exception):
        def __init__(self):
            super().__init__("context length exceeded")
            self.status_code = 413

    class _Messages:
        async def create(self, **_kw):
            raise _ContextLimitError()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    client = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude"))
    with pytest.raises(llm_client.LLMAPIError, match="context length exceeded") as exc:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)

    assert exc.value.provider == "anthropic"
    assert exc.value.status_code == 413
    assert exc.value.retryable is False
    assert "context length exceeded" in str(exc.value)


@pytest.mark.asyncio
async def test_gemini_context_limit_error_is_non_retryable(mock_config) -> None:
    class _GeminiContextError(Exception):
        def __init__(self):
            super().__init__("context length exceeded")
            self.status_code = 400

    async def _operation():
        raise _GeminiContextError()

    with pytest.raises(llm_client.LLMAPIError, match="context length exceeded") as exc:
        await llm_client._retry_with_backoff(
            "gemini",
            _operation,
            config=mock_config(LLM_MAX_RETRIES=0),
            retry_hint="Gemini yanıtı alınamadı",
        )

    assert exc.value.provider == "gemini"
    assert exc.value.status_code == 400
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_llmclient_wrapper_paths(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(client._semantic_cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(client._semantic_cache, "set", AsyncMock(return_value=None))
    monkeypatch.setattr(client._client, "chat", fake_chat)
    assert await client.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False) == "resp"

    monkeypatch.setattr(client._semantic_cache, "get", AsyncMock(return_value="cached"))
    assert await client.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False) == "cached"

    async def fake_stream_chat(**_kw):
        async def g():
            yield "x"
        return g()

    monkeypatch.setattr(client._client, "chat", fake_stream_chat)
    stream = await client.chat([{"role": "user", "content": "hello"}], stream=True, json_mode=False)
    chunks = await _collect(stream)
    assert chunks == ["x"]

    monkeypatch.setattr(client._client, "list_models", AsyncMock(return_value=["model-a"]))
    monkeypatch.setattr(client._client, "is_available", AsyncMock(return_value=True))
    assert await client.list_ollama_models() == ["model-a"]
    assert await client.is_ollama_available() is True


@pytest.mark.asyncio
async def test_semantic_cache_manager_edge_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(ENABLE_SEMANTIC_CACHE=False)
    manager = llm_client._SemanticCacheManager(cfg)
    assert await manager._get_redis() is None

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
    assert await manager2._get_redis() is not None
    # ikinci çağrı cache'ten dönmeli
    assert await manager2._get_redis() is manager2._redis

    class _RBoom:
        @staticmethod
        def from_url(*_a, **_kw):
            class _Inst:
                async def ping(self):
                    raise RuntimeError("redis down")
            return _Inst()

    manager3 = llm_client._SemanticCacheManager(cfg2)
    monkeypatch.setattr(llm_client, "Redis", _RBoom)
    assert await manager3._get_redis() is None

    # embed import hatasında [] dönmeli
    _patch_imports(monkeypatch, {"core.rag": ImportError("x")})
    assert manager3._embed_prompt("p") == []


@pytest.mark.asyncio
async def test_semantic_cache_circuit_breaker_opens_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_REDIS_CB_FAIL_THRESHOLD=2,
        SEMANTIC_CACHE_REDIS_CB_COOLDOWN_SECONDS=30,
    )
    manager = llm_client._SemanticCacheManager(cfg)

    attempts = {"n": 0}
    skipped = {"n": 0}

    class _RBoom:
        @staticmethod
        def from_url(*_a, **_kw):
            attempts["n"] += 1

            class _Inst:
                async def ping(self):
                    raise RuntimeError("redis down")

            return _Inst()

    monkeypatch.setattr(llm_client, "Redis", _RBoom)
    monkeypatch.setattr(llm_client, "record_cache_skip", lambda: skipped.__setitem__("n", skipped["n"] + 1))

    assert await manager._get_redis() is None
    assert await manager._get_redis() is None
    assert attempts["n"] == 2

    # Devre kesici açıkken yeni bağlantı denemesi yapılmamalı.
    assert await manager._get_redis() is None
    assert attempts["n"] == 2
    assert skipped["n"] >= 1


@pytest.mark.asyncio
async def test_semantic_cache_get_set_error_paths(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())

    async def _redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])
    assert await manager.get("x") is None

    async def _redis2():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _redis2)
    monkeypatch.setattr(fake_redis, "lrange", AsyncMock(side_effect=redis_exceptions.ConnectionError("boom")))
    assert await manager.get("x") is None

    # set: vector boş -> no-op
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [])
    assert await manager.set("p", "r") is None


@pytest.mark.asyncio
async def test_ollama_and_openai_error_paths(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    cfg = _make_config(CODING_MODEL="m1", OLLAMA_URL="http://x")
    oc = llm_client.OllamaClient(cfg)

    respx_mock_router.post("http://x/api/chat").mock(side_effect=RuntimeError("fail"))
    with pytest.raises(llm_client.LLMAPIError, match="fail") as exc:
        await oc.chat([{"role": "user", "content": "x"}], stream=False)
    assert exc.value.provider == "ollama"

    respx_mock_router.get("http://x/api/tags").mock(side_effect=RuntimeError("x"))
    assert await oc.list_models() == []
    assert await oc.is_available() is False

    # openai stream hata yolu
    oa = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k"))

    async def _retry_boom(*_a, **_kw):
        raise RuntimeError("stream boom")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_boom)
    got = await _collect(oa._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=True))
    assert "OpenAI" in got[0]


@pytest.mark.asyncio
async def test_litellm_fallback_raise_and_successive_model(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    cfg = _make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", LITELLM_FALLBACK_MODELS=["m2"])
    c = llm_client.LiteLLMClient(cfg)
    respx_mock_router.post("http://gw/chat/completions").mock(
        side_effect=[RuntimeError("first failed"), httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})]
    )
    assert await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False) == "ok"

    respx_mock_router.post("http://gw/chat/completions").mock(side_effect=RuntimeError("all failed"))
    with pytest.raises(llm_client.LLMAPIError, match="all failed") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False)
    assert exc.value.provider == "litellm"


@pytest.mark.asyncio
async def test_gemini_stream_generator_error_and_key_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client(DummyGeminiClient):
        def __init__(self, api_key):
            super().__init__(api_key, text="ok", stream_texts=())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)

    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="", GEMINI_MODEL="g"))
    assert "GEMINI_API_KEY" in await c.chat([{"role": "user", "content": "x"}], stream=False)

    async def broken_stream():
        raise RuntimeError("bad")
        yield "x"  # pragma: no cover

    chunks = await _collect(c._stream_gemini_generator(broken_stream()))
    assert "Gemini" in chunks[0] and "HATA" in chunks[0]


@pytest.mark.asyncio
async def test_anthropic_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k"))
    monkeypatch.setattr(llm_client, "anthropic", ImportError("anthropic not installed"), raising=False)
    _patch_imports(monkeypatch, {"anthropic": ImportError("anthropic not installed")})
    msg = await c.chat([{"role": "user", "content": "x"}], stream=False)
    assert "anthropic paketi" in msg


@pytest.mark.asyncio
async def test_anthropic_stream_error(monkeypatch: pytest.MonkeyPatch) -> None:
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

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    c2 = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k"))
    out = await _collect(c2._stream_anthropic(_AsyncAnthropic(), "m", [{"role": "user", "content": "u"}], "", 0.1, True))
    assert "Anthropic" in out[0]


@pytest.mark.asyncio
async def test_llmclient_routing_and_compat_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert await c.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=False) == "ok"

    # stream mode'da cache skip path
    called = {"n": 0}
    monkeypatch.setattr(llm_client, "record_cache_skip", lambda: called.__setitem__("n", called["n"] + 1))

    async def _stream(**_kw):
        async def g():
            yield "s"
        return g()

    monkeypatch.setattr(c._client, "chat", _stream)
    stream = await c.chat([{"role": "user", "content": "hello"}], stream=True, json_mode=False)
    assert await _collect(stream) == ["s"]
    assert called["n"] == 1

    # compat gemini stream helper (provider gemini değilken de çalışmalı)
    async def _gen():
        yield SimpleNamespace(text="t1")
    assert await _collect(c._stream_gemini_generator(_gen())) == ["t1"]


@pytest.mark.asyncio
async def test_retryable_exception_http_status_error_branch() -> None:
    req = httpx.Request("GET", "https://example.test")
    resp = httpx.Response(502, request=req)
    exc = httpx.HTTPStatusError("bad gateway", request=req, response=resp)
    retryable, status = llm_client._is_retryable_exception(exc)
    assert retryable is True
    assert status == 502


@pytest.mark.asyncio
async def test_semantic_cache_cosine_similarity_zero_norm() -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    assert manager._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


@pytest.mark.asyncio
async def test_semantic_cache_embed_prompt_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    fake_mod = types.SimpleNamespace(embed_texts_for_semantic_cache=lambda _texts, cfg=None: [[1, 2, 3]])
    _patch_imports(monkeypatch, {"core.rag": fake_mod})
    assert manager._embed_prompt("hello") == [1.0, 2.0, 3.0]


@pytest.mark.asyncio
async def test_semantic_cache_get_handles_invalid_records(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(_make_config(SEMANTIC_CACHE_THRESHOLD=0.99))
    await fake_redis.lpush(manager.index_key, "k3")
    await fake_redis.lpush(manager.index_key, "k2")
    await fake_redis.lpush(manager.index_key, "k1")
    await fake_redis.hset("k2", mapping={"embedding": "not-json", "response": "r2"})
    await fake_redis.hset("k3", mapping={"embedding": json.dumps([1.0, 0.0]), "response": "r3"})
    misses = {"n": 0}

    async def _redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [0.0, 1.0])
    monkeypatch.setattr(llm_client, "record_cache_miss", lambda: misses.__setitem__("n", misses["n"] + 1))
    assert await manager.get("hello") is None
    assert misses["n"] == 1


@pytest.mark.asyncio
async def test_semantic_cache_set_handles_write_exception(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    errors = {"n": 0}

    async def _redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])
    monkeypatch.setattr(llm_client, "record_cache_redis_error", lambda: errors.__setitem__("n", errors["n"] + 1))
    pipeline = fake_redis.pipeline(transaction=True)
    monkeypatch.setattr(
        pipeline,
        "execute",
        AsyncMock(side_effect=redis_exceptions.ConnectionError("write failed")),
    )
    monkeypatch.setattr(fake_redis, "pipeline", lambda transaction=True: pipeline)

    await manager.set("prompt", "resp")

    assert errors["n"] == 1


class _Span:
    def __init__(self):
        self.attrs = {}
        self.ended = 0

    def set_attribute(self, key, value):
        self.attrs[key] = value

    def end(self):
        self.ended += 1


class _SpanCM:
    def __init__(self, span):
        self.span = span
        self.exit_calls = 0

    def __enter__(self):
        return self.span

    def __exit__(self, *_exc):
        self.exit_calls += 1
        return False


@pytest.mark.asyncio
async def test_ollama_chat_with_tracing_sets_span_attrs(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    cfg = _make_config(CODING_MODEL="m1", OLLAMA_URL="http://x/api", ENABLE_TRACING=True)
    client = llm_client.OllamaClient(cfg)
    span = _Span()
    span_cm = _SpanCM(span)
    tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm)

    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)
    respx_mock_router.post("http://x/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": '{"tool":"final_answer","argument":"ok","thought":"t"}'}})
    )
    out = await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True)
    assert "final_answer" in out
    assert span.attrs["sidar.llm.provider"] == "ollama"
    assert "sidar.llm.total_ms" in span.attrs
    assert span_cm.exit_calls == 1


@pytest.mark.asyncio
async def test_openai_chat_stream_with_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", ENABLE_TRACING=True))
    span = _Span()
    tracer = SimpleNamespace(start_span=lambda _n: span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)

    def _stream(*_a, **_kw):
        async def gen():
            yield "tok"
        return gen()

    monkeypatch.setattr(c, "_stream_openai", _stream)
    stream = await c.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False)
    assert await _collect(stream) == ["tok"]
    assert span.attrs["sidar.llm.provider"] == "openai"


@pytest.mark.asyncio
async def test_litellm_stream_and_nonstream_tracing_attrs(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    cfg = _make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", ENABLE_TRACING=True)
    c = llm_client.LiteLLMClient(cfg)
    span = _Span()
    span_cm = _SpanCM(span)
    tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm, start_span=lambda _n: span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)

    respx_mock_router.post("http://gw/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {}, "choices": [{"message": {"content": "ok"}}]})
    )
    assert await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False) == "ok"
    assert span.attrs["sidar.llm.provider"] == "litellm"
    assert span.attrs["sidar.llm.model"] == "m1"

    def _stream(*_a, **_kw):
        async def gen():
            yield "A"
        return gen()

    monkeypatch.setattr(c, "_stream_openai_compatible", _stream)
    got = await c.chat([{"role": "user", "content": "x"}], stream=True, json_mode=False)
    assert await _collect(got) == ["A"]


@pytest.mark.asyncio
async def test_gemini_chat_json_injection_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _Models(DummyGeminiModels):
        async def generate_content(self, **kwargs):
            captured.update(kwargs)
            return DummyGeminiResponse('{"tool":"final_answer","argument":"ok","thought":"t"}')

    class _Client(DummyGeminiClient):
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=_Models())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)
    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm"))
    out = await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True)
    assert "final_answer" in out
    assert captured["contents"] == [{"role": "user", "parts": ["x"]}]
    assert captured["config"].response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_openai_and_litellm_stream_skip_non_data_lines(respx_mock_router) -> None:
    oa = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k"))
    llm = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1"))
    stream_body = "\n".join(["", "event: ping", 'data: {"choices":[{"delta":{"content":"X"}}]}', "data: [DONE]"])
    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, text=stream_body))
    respx_mock_router.post("http://gw/chat/completions").mock(return_value=httpx.Response(200, text=stream_body))

    assert await _collect(oa._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=False)) == ["X"]
    assert await _collect(llm._stream_openai_compatible("http://gw/chat/completions", {}, {}, llm_client.httpx.Timeout(10, connect=1), False)) == ["X"]


@pytest.mark.asyncio
async def test_anthropic_json_mode_and_fallback_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _Usage:
        input_tokens = 2
        output_tokens = 3

    class _MsgResp:
        usage = _Usage()
        content = [SimpleNamespace(text='{"tool":"final_answer","argument":"ok","thought":"t"}')]

    class _Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _MsgResp()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude"))
    out = await c.chat([{"role": "system", "content": "s"}], stream=False, json_mode=True)
    assert "final_answer" in out
    assert captured["messages"][0]["role"] == "user"
    assert llm_client.SIDAR_TOOL_JSON_INSTRUCTION in captured["system"]


@pytest.mark.asyncio
async def test_llmclient_provider_helpers_and_cache_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(OPENAI_API_KEY="k")
    c = llm_client.LLMClient("openai", cfg)
    assert c._build_ollama_timeout().connect == 10.0
    assert c._ollama_base_url.endswith("11434")
    assert await c.list_ollama_models() == []
    assert await c.is_ollama_available() is False

    # no user prompt -> skip cache get/set but cloud cost path çalışır
    events = {"cost": 0.0}
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(c._router, "select", lambda *_a: ("openai", None))
    monkeypatch.setattr(c._client, "chat", lambda **_kw: asyncio.sleep(0, result="ok"))
    monkeypatch.setattr(c._semantic_cache, "get", lambda *_a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(c._semantic_cache, "set", lambda *_a: asyncio.sleep(0))
    monkeypatch.setattr(llm_client, "record_routing_cost", lambda v: events.__setitem__("cost", v))
    result = await c.chat([{"role": "assistant", "content": "a" * 40}], stream=False, json_mode=False)
    assert result == "ok"
    assert events["cost"] > 0


@pytest.mark.asyncio
async def test_openai_json_mode_config_and_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", ENABLE_TRACING=True))
    assert c.json_mode_config()["response_format"]["type"] == "json_schema"
    span = _Span()
    span_cm = _SpanCM(span)
    tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)

    async def raise_llm(*_a, **_kw):
        raise llm_client.LLMAPIError("openai", "x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", raise_llm)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True)
    assert exc.value.provider == "openai"

    async def raise_other(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", raise_other)
    with pytest.raises(llm_client.LLMAPIError, match="boom") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=True)
    assert exc.value.provider == "openai"
    assert "boom" in str(exc.value)
    assert span.attrs["sidar.llm.provider"] == "openai"


@pytest.mark.asyncio
async def test_ollama_generic_error_wrap(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.OllamaClient(_make_config(CODING_MODEL="m"))

    async def broken(*_a, **_kw):
        raise RuntimeError("down")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", broken)
    with pytest.raises(llm_client.LLMAPIError, match="down") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False)
    assert exc.value.provider == "ollama"


@pytest.mark.asyncio
async def test_gemini_stream_error_fallback_and_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Models:
        async def generate_content_stream(self, **_kw):
            raise RuntimeError("stream-open-fail")

    class _Client:
        def __init__(self, api_key):
            self.aio = SimpleNamespace(models=_Models())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)
    span = _Span()
    tracer = SimpleNamespace(start_span=lambda _n: span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)
    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=True))
    stream = await c.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], stream=True, json_mode=True)
    chunks = await _collect(stream)
    assert "Gemini" in chunks[0]
    assert span.attrs["sidar.llm.provider"] == "gemini"


@pytest.mark.asyncio
async def test_litellm_failure_with_tracing(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", ENABLE_TRACING=True))
    span = _Span()
    span_cm = _SpanCM(span)
    tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)

    respx_mock_router.post("http://gw/chat/completions").mock(side_effect=RuntimeError("fail"))
    with pytest.raises(llm_client.LLMAPIError, match="fail") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert exc.value.provider == "litellm"


@pytest.mark.asyncio
async def test_anthropic_error_branches_and_split_system() -> None:
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ENABLE_TRACING=True))
    system, convo = c._split_system_and_messages([{"role": "system", "content": ""}, {"role": "user", "content": "u"}])
    assert system == ""
    assert convo == [{"role": "user", "content": "u"}]


@pytest.mark.parametrize(
    ("enable_tracing", "json_mode"),
    [
        (True, True),
        (False, False),
    ],
)
@pytest.mark.asyncio
async def test_anthropic_nonstream_error_paths(
    monkeypatch: pytest.MonkeyPatch, enable_tracing: bool, json_mode: bool
) -> None:
    class _Messages:
        async def create(self, **_kw):
            return SimpleNamespace(usage=None, content=[])

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    assert isinstance(await _Messages().create(), SimpleNamespace)
    c = llm_client.AnthropicClient(
        _make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ENABLE_TRACING=enable_tracing)
    )
    if enable_tracing:
        span = _Span()
        span_cm = _SpanCM(span)
        tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm)
        monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)

    async def llm_err(*_a, **_kw):
        raise llm_client.LLMAPIError("anthropic", "x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", llm_err)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=json_mode)
    assert exc.value.provider == "anthropic"

    async def oth_err(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", oth_err)
    with pytest.raises(llm_client.LLMAPIError, match="boom") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=json_mode)
    assert exc.value.provider == "anthropic"
    assert "boom" in str(exc.value)


@pytest.mark.asyncio
async def test_llmclient_init_branches_and_truncation_and_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(llm_client.LLMClient("gemini", _make_config())._client, llm_client.GeminiClient)
    assert isinstance(llm_client.LLMClient("anthropic", _make_config())._client, llm_client.AnthropicClient)
    assert isinstance(llm_client.LLMClient("litellm", _make_config())._client, llm_client.LiteLLMClient)
    with pytest.raises(ValueError):
        llm_client.LLMClient("unknown-provider", _make_config())

    c = llm_client.LLMClient("ollama", _make_config(OLLAMA_CONTEXT_MAX_CHARS=600))
    msgs = [
        {"role": "system", "content": "s" * 400},
        {"role": "user", "content": "u" * 500},
        {"role": "assistant", "content": "a" * 500},
    ]
    out = c._truncate_messages_for_local_model(msgs)
    assert sum(len(m["content"]) for m in out) <= 1200

    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)

    class _Routed:
        def __init__(self, *_a, **_kw):
            pass

        async def chat(self, **_kw):
            return "routed-ok"

    monkeypatch.setattr(c._router, "select", lambda *_a: ("openai", "m2"))
    monkeypatch.setattr(llm_client, "LLMClient", _Routed)
    assert await c.chat([{"role": "user", "content": "u"}], system_prompt="sys", stream=False, json_mode=False) == "routed-ok"


@pytest.mark.asyncio
async def test_llmclient_routing_failure_falls_back_to_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.LLMClient("ollama", _make_config())

    seen: dict[str, Any] = {"truncated": False}

    def _truncate(msgs: list[dict[str, str]]) -> list[dict[str, str]]:
        seen["truncated"] = True
        return msgs

    monkeypatch.setattr(c._router, "select", lambda *_a: ("openai", "gpt-4o-mini"))
    monkeypatch.setattr(llm_client, "LLMClient", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("route boom")))
    monkeypatch.setattr(c, "_truncate_messages_for_local_model", _truncate)
    monkeypatch.setattr(llm_client, "_dlp_mask_messages", lambda m: m)
    monkeypatch.setattr(c._semantic_cache, "get", lambda *_a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(c._semantic_cache, "set", lambda *_a: asyncio.sleep(0))
    monkeypatch.setattr(c._client, "chat", lambda **_kw: asyncio.sleep(0, result="fallback-ok"))

    out = await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert out == "fallback-ok"
    assert seen["truncated"] is True


@pytest.mark.asyncio
async def test_llmclient_stream_gemini_generator_client_branch() -> None:
    c = llm_client.LLMClient("gemini", _make_config())

    async def _gen():
        yield SimpleNamespace(text="gg")

    assert await _collect(c._stream_gemini_generator(_gen())) == ["gg"]


@pytest.mark.asyncio
async def test_llmclient_stream_gemini_generator_fallback_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.LLMClient("openai", _make_config())

    async def _fallback(_self, _response_stream):
        yield "fallback-g"

    monkeypatch.setattr(llm_client.GeminiClient, "_stream_gemini_generator", _fallback)

    assert await _collect(c._stream_gemini_generator(object())) == ["fallback-g"]


@pytest.mark.asyncio
async def test_semantic_cache_additional_branches(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    await _cache_put(fake_redis, manager, "k2", [1.0, 0.0], "r2")
    await _cache_put(fake_redis, manager, "k1", [1.0, 0.0], "r1")

    async def _redis():
        return fake_redis

    monkeypatch.setattr(manager, "_get_redis", _redis)
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [])
    assert await manager.get("hello") is None

    # ikinci kayıtta similarity eşit olduğunda best güncellenmeden devam etmeli
    monkeypatch.setattr(manager, "_embed_prompt", lambda _p: [1.0, 0.0])
    assert await manager.get("hello") == "r1"

    # mevcut anahtar yeniden yazıldığında eviction artmamalı
    manager2 = llm_client._SemanticCacheManager(_make_config())
    key = "sidar:semantic_cache:item:" + hashlib.sha256("p".encode("utf-8")).hexdigest()
    await fake_redis.flushall()
    await fake_redis.lpush(manager2.index_key, key)

    async def _redis2():
        return fake_redis

    evictions = {"n": 0}
    monkeypatch.setattr(manager2, "_get_redis", _redis2)
    monkeypatch.setattr(manager2, "_embed_prompt", lambda _p: [1.0, 0.0])
    monkeypatch.setattr(llm_client, "record_cache_eviction", lambda: evictions.__setitem__("n", evictions["n"] + 1))
    await manager2.set("p", "r")
    assert evictions["n"] == 0


@pytest.mark.asyncio
async def test_ollama_stream_trailing_decoder_branch(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.OllamaClient(_make_config())

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '\n{"message":{"content":"TAIL"}}\n'
            return " \n"

    monkeypatch.setattr(llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder()))

    respx_mock_router.post("http://u").mock(return_value=httpx.Response(200, content=b"x"))
    out = await _collect(c._stream_response("http://u", {}, llm_client.httpx.Timeout(10, connect=1)))
    assert out == ["TAIL"]


@pytest.mark.asyncio
async def test_openai_and_litellm_stream_empty_delta_and_cleanup(respx_mock_router) -> None:
    oa = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k"))
    llm = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1"))
    stream_body = "\n".join(
        [
            'data: {"choices":[{"delta":{}}]}',
            'data: {"choices":[{"delta":{"content":"Z"}}]}',
            "data: [DONE]",
        ]
    )
    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, text=stream_body))
    respx_mock_router.post("http://gw/chat/completions").mock(return_value=httpx.Response(200, text=stream_body))

    openai_chunks = await _collect(oa._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=False))
    litellm_chunks = await _collect(
        llm._stream_openai_compatible("http://gw/chat/completions", {}, {}, llm_client.httpx.Timeout(10, connect=1), False)
    )

    assert openai_chunks == ["Z"]
    assert litellm_chunks == ["Z"]
    assert "" not in openai_chunks
    assert "" not in litellm_chunks


@pytest.mark.asyncio
async def test_litellm_empty_models_and_candidate_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="", OPENAI_MODEL=""))
    assert c._candidate_models("  ") == []
    assert c.json_mode_config() == {"response_format": {"type": "json_object"}}

    monkeypatch.setattr(c, "_candidate_models", lambda _m: [])
    with pytest.raises(llm_client.LLMAPIError, match="LiteLLM hata") as exc:
        await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert exc.value.provider == "litellm"


@pytest.mark.asyncio
async def test_anthropic_remaining_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k")).json_mode_config() == {}

    class _Messages:
        async def create(self, **_kw):
            raise RuntimeError("boom")

        def stream(self, **_kw):
            class _CM:
                async def __aenter__(self):
                    async def _gen():
                        yield SimpleNamespace(type="x", delta=SimpleNamespace(type="text_delta", text="A"))
                        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="x", text="B"))
                        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=""))
                        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="C"))
                    return _gen()

                async def __aexit__(self, *_exc):
                    return False

            return _CM()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    span = _Span()
    span_cm = _SpanCM(span)
    tracer = SimpleNamespace(start_as_current_span=lambda _n: span_cm)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: tracer)
    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m", ENABLE_TRACING=True))
    with pytest.raises(llm_client.LLMAPIError, match="boom") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "anthropic"
    chunks = await _collect(c._stream_anthropic(_AsyncAnthropic(), "m", [{"role": "user", "content": "u"}], "", 0.1, False))
    assert chunks == ["C"]


@pytest.mark.asyncio
async def test_anthropic_stream_handles_open_failure_without_context_manager_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"))

    async def _raise_open_error(*_args, **_kwargs):
        raise RuntimeError("open fail before cm assignment")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _raise_open_error)

    chunks = await _collect(
        c._stream_anthropic(
            client=SimpleNamespace(messages=SimpleNamespace(stream=lambda **_kw: None)),
            model_name="m",
            messages=[{"role": "user", "content": "u"}],
            system_prompt="",
            temperature=0.1,
            json_mode=False,
        )
    )

    assert len(chunks) == 1
    assert "Anthropic akış hatası" in chunks[0]
    assert "open fail before cm assignment" in chunks[0]


@pytest.mark.asyncio
async def test_openai_tracing_nonstream_success_and_error(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini", ENABLE_TRACING=True))
    span = _Span()
    span_cm = _SpanCM(span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: SimpleNamespace(start_as_current_span=lambda _n: span_cm))

    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {}, "choices": [{"message": {"content": "ok"}}]})
    )
    assert await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False) == "ok"
    assert "sidar.llm.total_ms" in span.attrs


@pytest.mark.asyncio
async def test_openai_invalid_model_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", OPENAI_MODEL="invalid-model"))

    async def _raise_invalid_model(_provider, _operation, **_kw):
        raise llm_client.LLMAPIError("openai", "model_not_found", status_code=404, retryable=False)

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _raise_invalid_model)
    with pytest.raises(llm_client.LLMAPIError, match="model_not_found") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "openai"
    assert exc.value.status_code == 404
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_llmclient_truncation_remaining_branches() -> None:
    c = llm_client.LLMClient("ollama", _make_config(OLLAMA_CONTEXT_MAX_CHARS=1200))
    msgs = [
        {"role": "user", "content": "u" * 500},
        {"role": "system", "content": "s" * 300},  # sonda system -> system insert branch atlanır
        {"role": "assistant", "content": "a" * 900},
    ]
    out = c._truncate_messages_for_local_model(msgs)
    assert sum(len(m["content"]) for m in out) <= 1200


@pytest.mark.asyncio
async def test_semantic_embed_empty_vectors_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())
    _patch_imports(monkeypatch, {"core.rag": types.SimpleNamespace(embed_texts_for_semantic_cache=lambda *_a, **_kw: [])})
    assert manager._embed_prompt("hello") == []


@pytest.mark.asyncio
async def test_ollama_stream_additional_json_branches(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.OllamaClient(_make_config())

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '{"message":{"content":""}}\ninvalid-json\n{"message":{"content":"ok"}}'
            return '{"message":{"content":""}}\n'

    monkeypatch.setattr(llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder()))

    respx_mock_router.post("http://u").mock(return_value=httpx.Response(200, content=b"x"))
    assert await _collect(c._stream_response("http://u", {}, llm_client.httpx.Timeout(10, connect=1))) == ["ok"]


@pytest.mark.asyncio
async def test_gemini_tracing_nonstream_and_empty_stream_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client(DummyGeminiClient):
        def __init__(self, api_key):
            super().__init__(api_key, text="ok", stream_texts=())

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)
    span = _Span()
    span_cm = _SpanCM(span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: SimpleNamespace(start_as_current_span=lambda _n: span_cm))
    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=True))
    assert await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False) == "ok"
    assert "sidar.llm.total_ms" in span.attrs
    assert span_cm.exit_calls == 1

    async def _gen():
        yield SimpleNamespace(text="")
        yield SimpleNamespace(text="T")

    assert await _collect(c._stream_gemini_generator(_gen())) == ["T"]


@pytest.mark.parametrize("enable_tracing", [True, False])
@pytest.mark.asyncio
async def test_openai_stream_empty_and_error_branches(
    monkeypatch: pytest.MonkeyPatch, respx_mock_router, enable_tracing: bool
) -> None:
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", ENABLE_TRACING=enable_tracing))
    if enable_tracing:
        span = _Span()
        span_cm = _SpanCM(span)
        monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: SimpleNamespace(start_as_current_span=lambda _n: span_cm))

    async def _raise_llm(*_a, **_kw):
        raise llm_client.LLMAPIError("openai", "x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _raise_llm)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "openai"

    async def _raise_other(*_a, **_kw):
        raise RuntimeError("x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _raise_other)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "openai"

    respx_mock_router.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, text=""))

    async def _retry_ok(_provider, operation, **_kw):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_ok)
    assert await _collect(c._stream_openai({}, {}, llm_client.httpx.Timeout(10, connect=1), json_mode=False)) == []


@pytest.mark.asyncio
async def test_litellm_stream_empty_and_invalid_line(respx_mock_router) -> None:
    c = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m"))
    respx_mock_router.post("http://gw/chat/completions").mock(return_value=httpx.Response(200, text="data: invalid\ndata: [DONE]"))
    assert await _collect(c._stream_openai_compatible("http://gw/chat/completions", {}, {}, llm_client.httpx.Timeout(10, connect=1), False)) == []


@pytest.mark.asyncio
async def test_anthropic_success_and_error_span_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Usage:
        input_tokens = 1
        output_tokens = 1

    class _Resp:
        usage = _Usage()
        content = [SimpleNamespace(text="ok")]

    class _Messages:
        async def create(self, **_kw):
            return _Resp()

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    span = _Span()
    span_cm = _SpanCM(span)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: SimpleNamespace(start_as_current_span=lambda _n: span_cm))
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m", ENABLE_TRACING=True))
    assert await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False) == "ok"
    assert "sidar.llm.total_ms" in span.attrs
    assert span.ended >= 1

    async def _llm(*_a, **_kw):
        raise llm_client.LLMAPIError("anthropic", "x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _llm)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "anthropic"

    async def _oth(*_a, **_kw):
        raise RuntimeError("x")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _oth)
    with pytest.raises(llm_client.LLMAPIError, match="x") as exc:
        await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False)
    assert exc.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_anthropic_empty_prompt_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {"messages": None}

    class _Messages:
        async def create(self, **kwargs):
            captured["messages"] = kwargs.get("messages")
            raise llm_client.LLMAPIError("anthropic", "model_not_found", status_code=404, retryable=False)

    class _AsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="invalid-model"))

    async def _retry_passthrough(_provider, operation, **_kw):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_passthrough)
    with pytest.raises(llm_client.LLMAPIError, match="model_not_found") as exc:
        await c.chat([], stream=False, json_mode=False)
    assert exc.value.provider == "anthropic"
    assert exc.value.status_code == 404
    assert exc.value.retryable is False
    assert captured["messages"] == [{"role": "user", "content": "Merhaba"}]


@pytest.mark.asyncio
async def test_truncation_branch_without_system_insert_and_small_message() -> None:
    c = llm_client.LLMClient("ollama", _make_config(OLLAMA_CONTEXT_MAX_CHARS=1200))
    msgs = [
        {"role": "system", "content": "s" * 1500},
        {"role": "user", "content": "u" * 120},
        {"role": "assistant", "content": "a" * 1000},
    ]
    out = c._truncate_messages_for_local_model(msgs)
    assert out[0]["role"] != "system" or len(out[0]["content"]) <= 400


@pytest.mark.asyncio
async def test_ollama_stream_buffer_tail_invalid_and_empty_content(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.OllamaClient(_make_config())

    class _DecoderA:
        def decode(self, _raw, final=False):
            return "" if final else '{"message":{"content":""}}'

    monkeypatch.setattr(llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _DecoderA()))

    respx_mock_router.post("http://u").mock(return_value=httpx.Response(200, content=b"x"))
    assert await _collect(c._stream_response("http://u", {}, llm_client.httpx.Timeout(10, connect=1))) == []

    class _DecoderB:
        def decode(self, _raw, final=False):
            return "" if final else "{not-json"

    monkeypatch.setattr(llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _DecoderB()))
    assert await _collect(c._stream_response("http://u", {}, llm_client.httpx.Timeout(10, connect=1))) == []


@pytest.mark.asyncio
async def test_litellm_stream_no_lines_branch(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m"))

    async def _retry_ok(_provider, operation, **_kw):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_ok)

    respx_mock_router.post("http://gw/chat/completions").mock(return_value=httpx.Response(200, text=""))
    assert await _collect(c._stream_openai_compatible("http://gw/chat/completions", {}, {}, llm_client.httpx.Timeout(10, connect=1), False)) == []


@pytest.mark.asyncio
async def test_truncation_no_system_and_empty_message_branch() -> None:
    c = llm_client.LLMClient("ollama", _make_config(OLLAMA_CONTEXT_MAX_CHARS=1200))
    msgs = [
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u" * 800},
        {"role": "assistant", "content": "a" * 900},
    ]
    out = c._truncate_messages_for_local_model(msgs)
    assert all("content" in m for m in out)


@pytest.mark.asyncio
async def test_truncation_system_empty_and_empty_history_content() -> None:
    c = llm_client.LLMClient("ollama", _make_config(OLLAMA_CONTEXT_MAX_CHARS=1200))
    msgs = [
        {"role": "system", "content": ""},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u" * 100},
        {"role": "assistant", "content": "a" * 1300},
    ]
    out = c._truncate_messages_for_local_model(msgs)
    assert any(m["role"] == "assistant" for m in out)


@pytest.mark.asyncio
async def test_semantic_cache_get_set_return_none_when_redis_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = llm_client._SemanticCacheManager(_make_config())

    async def no_redis():
        return None

    monkeypatch.setattr(manager, "_get_redis", no_redis)
    assert await manager.get("prompt") is None
    assert await manager.set("prompt", "response") is None


@pytest.mark.asyncio
async def test_llmclient_openai_handles_empty_and_long_prompt_with_fake_fixture(
    mock_config,
    fake_llm_response,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = mock_config(AI_PROVIDER="openai")
    client = llm_client.LLMClient("openai", cfg)

    monkeypatch.setattr(client._router, "select", lambda *_args: ("openai", None))
    client._semantic_cache.get = AsyncMock(return_value=None)
    client._semantic_cache.set = AsyncMock(return_value=None)

    async def _chat_adapter(*, messages, **_kwargs):
        prompt = str(messages[-1].get("content") or "")
        payload = await fake_llm_response(prompt)
        return str(payload["content"])

    client._client.chat = AsyncMock(side_effect=_chat_adapter)

    empty_out = await client.chat(messages=[{"role": "user", "content": ""}], stream=False)
    long_prompt = "x" * 6000
    long_out = await client.chat(messages=[{"role": "user", "content": long_prompt}], stream=False)

    assert isinstance(empty_out, str) and empty_out.startswith("mock-response:")
    assert isinstance(long_out, str) and long_out.startswith("mock-response:")
    client._semantic_cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_llmclient_openai_surfaces_rate_limit_error_with_fake_fixture(
    mock_config,
    fake_llm_error,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = mock_config(AI_PROVIDER="openai")
    client = llm_client.LLMClient("openai", cfg)

    monkeypatch.setattr(client._router, "select", lambda *_args: ("openai", None))
    client._semantic_cache.get = AsyncMock(return_value=None)
    client._client.chat = AsyncMock(side_effect=fake_llm_error)

    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        await client.chat(messages=[{"role": "user", "content": "fiyatlandırma nedir?"}], stream=False)


def test_cfg_helpers_cover_all_type_fallbacks() -> None:
    cfg = SimpleNamespace(
        STR_NONE=None,
        INT_BOOL=True,
        INT_BAD="oops",
        INT_OTHER=object(),
        FLOAT_BOOL=False,
        FLOAT_BAD="oops",
        FLOAT_OTHER=object(),
        BOOL_INT=2,
        BOOL_STR="on",
        BOOL_OTHER=object(),
    )
    assert llm_client._cfg_str(cfg, "STR_NONE", "d") == "d"
    assert llm_client._cfg_int(cfg, "INT_BOOL", 0) == 1
    assert llm_client._cfg_int(cfg, "INT_BAD", 7) == 7
    assert llm_client._cfg_int(cfg, "INT_OTHER", 5) == 5
    assert llm_client._cfg_float(cfg, "FLOAT_BOOL", 0.5) == 0.0
    assert llm_client._cfg_float(cfg, "FLOAT_BAD", 1.5) == 1.5
    assert llm_client._cfg_float(cfg, "FLOAT_OTHER", 2.5) == 2.5
    assert llm_client._cfg_bool(cfg, "BOOL_INT", False) is True
    assert llm_client._cfg_bool(cfg, "BOOL_STR", False) is True
    assert llm_client._cfg_bool(cfg, "BOOL_OTHER", True) is True
    assert llm_client._cfg_float(SimpleNamespace(FLOAT_OBJ=object()), "FLOAT_OBJ", 3.25) == 3.25


@pytest.mark.asyncio
async def test_gemini_nonstream_without_tracing_hits_no_span_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client(DummyGeminiClient):
        def __init__(self, api_key):
            super().__init__(api_key, text="ok")

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: SimpleNamespace(**kw))
    _mock_google_genai(monkeypatch, _Client, fake_types)
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: None)

    c = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=False))
    assert await c.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False) == "ok"


@pytest.mark.asyncio
async def test_litellm_nonstream_without_tracing_success(monkeypatch: pytest.MonkeyPatch, respx_mock_router) -> None:
    c = llm_client.LiteLLMClient(_make_config(LITELLM_GATEWAY_URL="http://gw", LITELLM_MODEL="m1", ENABLE_TRACING=False))
    monkeypatch.setattr(llm_client, "_get_tracer", lambda _cfg: None)
    respx_mock_router.post("http://gw/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {}, "choices": [{"message": {"content": "ok"}}]})
    )
    assert await c.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False) == "ok"


@pytest.mark.asyncio
async def test_openai_chat_error_detail_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        is_error = True
        status_code = 500
        text = ""

        def json(self):
            raise ValueError("bad json")

        def raise_for_status(self):
            raise RuntimeError("status boom")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _Client)
    c = llm_client.OpenAIClient(_make_config(OPENAI_API_KEY="k", OPENAI_MODEL="gpt", ENABLE_TRACING=False))
    with pytest.raises(llm_client.LLMAPIError, match="OpenAI isteği başarısız: status boom"):
        await c.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True)


@pytest.mark.asyncio
async def test_litellm_failure_without_tracing_hits_final_error_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("gateway down")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _Client)
    c = llm_client.LiteLLMClient(
        _make_config(
            LITELLM_GATEWAY_URL="http://localhost:4000",
            LITELLM_MODEL="m1",
            ENABLE_TRACING=False,
        )
    )
    with pytest.raises(llm_client.LLMAPIError, match="LiteLLM hata"):
        await c.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False)


@pytest.mark.asyncio
async def test_anthropic_success_without_tracing_span(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Messages:
        async def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
                content=[SimpleNamespace(text='{"tool":"final_answer","argument":"ok"}')],
            )

    class _AsyncAnthropic:
        def __init__(self, api_key, timeout=None):
            _ = api_key
            _ = timeout
            self.messages = _Messages()

    _mock_anthropic(monkeypatch, _AsyncAnthropic)
    c = llm_client.AnthropicClient(_make_config(ANTHROPIC_API_KEY="k", ENABLE_TRACING=False))
    out = await c.chat([{"role": "user", "content": "hello"}], stream=False, json_mode=True)
    assert "final_answer" in out


@pytest.mark.asyncio
async def test_ollama_do_request_json_parse_error_with_text(respx_mock_router) -> None:
    """Lines 524-525: resp.json() raises but resp.text is non-empty → detail taken from text."""
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434", CODING_MODEL="m"))
    respx_mock_router.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(400, content=b"raw error text")
    )
    with pytest.raises(llm_client.LLMAPIError) as exc_info:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert exc_info.value.provider == "ollama"


@pytest.mark.asyncio
async def test_ollama_do_request_json_parse_error_empty_text_fallthrough(respx_mock_router) -> None:
    """Branch 527->536: resp.json() raises, resp.text is empty → detail="" → raise_for_status() called."""
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434", CODING_MODEL="m"))
    respx_mock_router.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(400, content=b"")
    )
    with pytest.raises(llm_client.LLMAPIError) as exc_info:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert exc_info.value.provider == "ollama"


@pytest.mark.asyncio
async def test_ollama_chat_generic_exception_model_not_found_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lines 561-562: non-LLMAPIError with model-not-found text → warning logged + LLMAPIError with guidance."""
    client = llm_client.OllamaClient(_make_config(CODING_MODEL="xyz"))

    async def _raise_model_not_found(*_a, **_kw):
        raise RuntimeError("model 'xyz' not found")

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _raise_model_not_found)
    with pytest.raises(llm_client.LLMAPIError) as exc_info:
        await client.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False)
    assert exc_info.value.provider == "ollama"
    assert "ollama pull xyz" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_stream_inline_error_guidance_none_branch(respx_mock_router) -> None:
    """Branch 609->618: stream line has error but guidance is None → falls through to chunk parsing."""
    client = llm_client.OllamaClient(_make_config(OLLAMA_URL="http://localhost:11434", CODING_MODEL="m"))
    respx_mock_router.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, text='{"error":"connection refused"}\n')
    )
    chunks = await _collect(
        client._stream_response(
            "http://localhost:11434/api/chat",
            {"model": "m"},
            llm_client.httpx.Timeout(10, connect=1),
        )
    )
    assert chunks == []


@pytest.mark.asyncio
async def test_ollama_stream_trailing_newline_error_with_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lines 636-645: trailing decoded bytes contain a newline-terminated model-not-found error → guidance yielded."""

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '{"error":"model x not found"}\n'
            return ""

    monkeypatch.setattr(
        llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder())
    )

    class _DummyResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b""

    class _DummyCM:
        async def __aenter__(self):
            return _DummyResp()

        async def __aexit__(self, *_args):
            return None

    class _DummyClient:
        def stream(self, *_args, **_kwargs):
            return _DummyCM()

        async def aclose(self):
            return None

    async def _fake_retry(_provider, operation, *, config, retry_hint):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _fake_retry)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda timeout: _DummyClient())

    client = llm_client.OllamaClient(_make_config())
    chunks = await _collect(
        client._stream_response("http://u", {"model": "x"}, llm_client.httpx.Timeout(10, connect=1))
    )
    assert chunks
    assert "ollama pull x" in chunks[0]


@pytest.mark.asyncio
async def test_ollama_stream_remaining_buffer_error_with_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lines 657-666: remaining buffer without newline has model-not-found error → guidance yielded."""

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '{"error":"model x not found"}'  # no trailing newline
            return ""

    monkeypatch.setattr(
        llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder())
    )

    class _DummyResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b""

    class _DummyCM:
        async def __aenter__(self):
            return _DummyResp()

        async def __aexit__(self, *_args):
            return None

    class _DummyClient:
        def stream(self, *_args, **_kwargs):
            return _DummyCM()

        async def aclose(self):
            return None

    async def _fake_retry(_provider, operation, *, config, retry_hint):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _fake_retry)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda timeout: _DummyClient())

    client = llm_client.OllamaClient(_make_config())
    chunks = await _collect(
        client._stream_response("http://u", {"model": "x"}, llm_client.httpx.Timeout(10, connect=1))
    )
    assert chunks
    assert "ollama pull x" in chunks[0]


@pytest.mark.asyncio
async def test_ollama_stream_trailing_newline_error_no_guidance_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branch 637->646: trailing line has error but guidance is None → falls through to chunk parsing."""

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '{"error":"timed out"}\n'
            return ""

    monkeypatch.setattr(
        llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder())
    )

    class _DummyResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b""

    class _DummyCM:
        async def __aenter__(self):
            return _DummyResp()

        async def __aexit__(self, *_args):
            return None

    class _DummyClient:
        def stream(self, *_args, **_kwargs):
            return _DummyCM()

        async def aclose(self):
            return None

    async def _fake_retry(_provider, operation, *, config, retry_hint):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _fake_retry)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda timeout: _DummyClient())

    client = llm_client.OllamaClient(_make_config())
    chunks = await _collect(
        client._stream_response("http://u", {"model": "x"}, llm_client.httpx.Timeout(10, connect=1))
    )
    assert chunks == []


@pytest.mark.asyncio
async def test_ollama_stream_remaining_buffer_error_no_guidance_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Branch 658->667: remaining buffer has error but guidance is None → falls through to chunk parsing."""

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '{"error":"timed out"}'  # no trailing newline
            return ""

    monkeypatch.setattr(
        llm_client.codecs, "getincrementaldecoder", lambda *_a, **_kw: (lambda **_kw2: _Decoder())
    )

    class _DummyResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b""

    class _DummyCM:
        async def __aenter__(self):
            return _DummyResp()

        async def __aexit__(self, *_args):
            return None

    class _DummyClient:
        def stream(self, *_args, **_kwargs):
            return _DummyCM()

        async def aclose(self):
            return None

    async def _fake_retry(_provider, operation, *, config, retry_hint):
        return await operation()

    monkeypatch.setattr(llm_client, "_retry_with_backoff", _fake_retry)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda timeout: _DummyClient())

    client = llm_client.OllamaClient(_make_config())
    chunks = await _collect(
        client._stream_response("http://u", {"model": "x"}, llm_client.httpx.Timeout(10, connect=1))
    )
    assert chunks == []


def _list_duplicate_test_function_names_in_file(file_path: pathlib.Path) -> list[str]:
    module = ast.parse(file_path.read_text())
    names = [
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]
    seen = set()
    duplicates = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        else:
            seen.add(name)
    return sorted(duplicates)


def test_test_module_has_no_duplicate_test_function_names() -> None:
    duplicates = _list_duplicate_test_function_names_in_file(pathlib.Path(__file__))
    assert duplicates == []
