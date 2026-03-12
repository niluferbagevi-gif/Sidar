import asyncio
from types import SimpleNamespace

import pytest

import core.llm_client as llm


class _Collector:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


def test_is_retryable_exception_status_and_network_cases():
    err_429 = llm.LLMAPIError("x", "msg", status_code=429)
    assert llm._is_retryable_exception(err_429) == (True, 429)

    err_500 = llm.LLMAPIError("x", "msg", status_code=500)
    assert llm._is_retryable_exception(err_500) == (True, 500)

    assert llm._is_retryable_exception(asyncio.TimeoutError()) == (True, None)
    assert llm._is_retryable_exception(RuntimeError("hard fail")) == (False, None)


def test_retry_with_backoff_retries_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] < 2:
            raise asyncio.TimeoutError()
        return "ok"

    cfg = SimpleNamespace(LLM_MAX_RETRIES=2, LLM_RETRY_BASE_DELAY=0.05, LLM_RETRY_MAX_DELAY=0.1)
    out = asyncio.run(llm._retry_with_backoff("openai", op, config=cfg, retry_hint="chat failed"))
    assert out == "ok"
    assert sleeps == [0.05]


def test_track_stream_completion_records_success_and_error(monkeypatch):
    collector = _Collector()
    monkeypatch.setattr(llm, "get_llm_metrics_collector", lambda: collector)
    monkeypatch.setattr(llm, "get_current_metrics_user_id", lambda: "u-1")

    async def gen_ok():
        yield "a"

    got = asyncio.run(_collect(llm._track_stream_completion(gen_ok(), provider="p", model="m", started_at=0.0)))
    assert got == ["a"]
    assert collector.calls[-1]["success"] is True

    async def gen_fail():
        yield "x"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(_collect(llm._track_stream_completion(gen_fail(), provider="p", model="m", started_at=0.0)))
    assert collector.calls[-1]["success"] is False


async def _collect(aiter):
    return [x async for x in aiter]

def test_retry_with_backoff_raises_on_non_retryable_error(monkeypatch):
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    async def op():
        raise RuntimeError("hard fail")

    cfg = SimpleNamespace(LLM_MAX_RETRIES=3, LLM_RETRY_BASE_DELAY=0.05, LLM_RETRY_MAX_DELAY=0.1)
    try:
        asyncio.run(llm._retry_with_backoff("openai", op, config=cfg, retry_hint="chat failed"))
        assert False, "expected LLMAPIError"
    except llm.LLMAPIError as exc:
        assert exc.provider == "openai"
        assert exc.retryable is False
        assert "chat failed" in str(exc)
