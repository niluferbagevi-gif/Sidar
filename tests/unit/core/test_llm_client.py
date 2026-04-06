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


def test_is_retryable_exception_for_timeout_and_status() -> None:
    retryable, status = llm_client._is_retryable_exception(httpx.TimeoutException("x"))
    assert retryable is True
    assert status is None

    exc = Exception("boom")
    setattr(exc, "status_code", 503)
    retryable, status = llm_client._is_retryable_exception(exc)
    assert retryable is True
    assert status == 503


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
