import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_llm_module_for_retry_tests():
    class _HTTPStatusError(Exception):
        pass

    class _ConnectError(Exception):
        pass

    class _TimeoutException(Exception):
        pass

    httpx_stub = types.SimpleNamespace(
        Timeout=object,
        ConnectError=_ConnectError,
        TimeoutException=_TimeoutException,
        HTTPStatusError=_HTTPStatusError,
        AsyncClient=None,
    )
    sys.modules["httpx"] = httpx_stub

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

    spec = importlib.util.spec_from_file_location("llm_retry_under_test", Path("core/llm_client.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


llm = _load_llm_module_for_retry_tests()


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


def test_retry_with_backoff_applies_exponential_backoff_for_429(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] <= 2:
            raise llm.LLMAPIError("openai", "rate limit", status_code=429)
        return "ok"

    cfg = SimpleNamespace(LLM_MAX_RETRIES=3, LLM_RETRY_BASE_DELAY=0.1, LLM_RETRY_MAX_DELAY=1.0)
    out = asyncio.run(llm._retry_with_backoff("openai", op, config=cfg, retry_hint="chat failed"))
    assert out == "ok"
    assert sleeps == [0.1, 0.2]


def test_retry_with_backoff_caps_delay_for_5xx(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] <= 3:
            raise llm.LLMAPIError("openai", "server error", status_code=503)
        return "ok"

    cfg = SimpleNamespace(LLM_MAX_RETRIES=4, LLM_RETRY_BASE_DELAY=0.3, LLM_RETRY_MAX_DELAY=0.5)
    out = asyncio.run(llm._retry_with_backoff("openai", op, config=cfg, retry_hint="chat failed"))
    assert out == "ok"
    assert sleeps == [0.3, 0.5, 0.5]


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

def test_is_retryable_exception_http_status_error_429_and_network_classes(monkeypatch):
    class _HTTPStatusError(Exception):
        def __init__(self, code):
            self.response = SimpleNamespace(status_code=code)

    class _TimeoutException(Exception):
        pass

    class _ConnectError(Exception):
        pass

    monkeypatch.setattr(llm.httpx, "HTTPStatusError", _HTTPStatusError, raising=False)
    monkeypatch.setattr(llm.httpx, "TimeoutException", _TimeoutException, raising=False)
    monkeypatch.setattr(llm.httpx, "ConnectError", _ConnectError, raising=False)

    assert llm._is_retryable_exception(_HTTPStatusError(429)) == (True, 429)
    assert llm._is_retryable_exception(_HTTPStatusError(502)) == (True, 502)
    assert llm._is_retryable_exception(_TimeoutException("timeout")) == (True, None)
    assert llm._is_retryable_exception(_ConnectError("conn")) == (True, None)


def test_ensure_json_text_wraps_plain_and_empty_outputs_for_final_answer():
    wrapped = llm._ensure_json_text("düz metin", "Anthropic")
    payload = __import__("json").loads(wrapped)
    assert payload["tool"] == "final_answer"
    assert payload["argument"] == "düz metin"
    assert "JSON dışı" in payload["thought"]

    wrapped_empty = llm._ensure_json_text("", "Anthropic")
    payload_empty = __import__("json").loads(wrapped_empty)
    assert payload_empty["tool"] == "final_answer"
    assert "boş içerik" in payload_empty["argument"]

def test_retry_with_backoff_raises_after_retry_limit_for_timeout(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    async def op():
        raise asyncio.TimeoutError()

    cfg = SimpleNamespace(LLM_MAX_RETRIES=1, LLM_RETRY_BASE_DELAY=0.05, LLM_RETRY_MAX_DELAY=0.1)
    with pytest.raises(llm.LLMAPIError) as exc:
        asyncio.run(llm._retry_with_backoff("openai", op, config=cfg, retry_hint="chat failed"))

    assert exc.value.provider == "openai"
    assert exc.value.retryable is True
    assert sleeps == [0.05]