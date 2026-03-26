import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.test_llm_client_critical_gap_closers import _collect, _load_llm_module


llm = _load_llm_module()


@pytest.mark.parametrize("status_code", [401, 403])
def test_openai_chat_raises_non_retryable_auth_errors_without_retry(monkeypatch, status_code):
    sleeps = []
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)

    async def _fake_sleep(delay):
        sleeps.append(delay)

    class _HTTPStatusError(Exception):
        def __init__(self, code):
            super().__init__(f"auth {code}")
            self.response = SimpleNamespace(status_code=code)

    class _Response:
        def raise_for_status(self):
            raise _HTTPStatusError(status_code)

        def json(self):
            return {}

    class _AsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr(llm.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _AsyncClient, raising=False)
    monkeypatch.setattr(llm.httpx, "HTTPStatusError", _HTTPStatusError, raising=False)

    cfg = SimpleNamespace(
        OPENAI_API_KEY="secret",
        OPENAI_MODEL="gpt-test",
        OPENAI_TIMEOUT=10,
        LLM_MAX_RETRIES=3,
        LLM_RETRY_BASE_DELAY=0.05,
        LLM_RETRY_MAX_DELAY=0.1,
        ENABLE_TRACING=False,
    )
    client = llm.OpenAIClient(cfg)

    with pytest.raises(llm.LLMAPIError) as excinfo:
        asyncio.run(client.chat([{"role": "user", "content": "kimlik dene"}], stream=False, json_mode=False))

    assert excinfo.value.provider == "openai"
    assert excinfo.value.status_code == status_code
    assert excinfo.value.retryable is False
    assert sleeps == []


def test_openai_chat_timeout_stops_after_retry_limit(monkeypatch):
    sleeps = []
    warnings = []
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)
    monkeypatch.setattr(llm.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(llm.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    async def _fake_sleep(delay):
        sleeps.append(delay)

    class _AsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            raise asyncio.TimeoutError("provider timeout")

    monkeypatch.setattr(llm.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _AsyncClient, raising=False)

    cfg = SimpleNamespace(
        OPENAI_API_KEY="secret",
        OPENAI_MODEL="gpt-test",
        OPENAI_TIMEOUT=10,
        LLM_MAX_RETRIES=1,
        LLM_RETRY_BASE_DELAY=0.05,
        LLM_RETRY_MAX_DELAY=0.1,
        ENABLE_TRACING=False,
    )
    client = llm.OpenAIClient(cfg)

    with pytest.raises(llm.LLMAPIError) as excinfo:
        asyncio.run(client.chat([{"role": "user", "content": "zaman aşımı"}], stream=False, json_mode=False))

    assert excinfo.value.provider == "openai"
    assert excinfo.value.retryable is True
    assert "provider timeout" in str(excinfo.value)
    assert sleeps == [0.05]
    assert len(warnings) == 1


def test_openai_chat_wraps_empty_nonstream_response_in_json_mode(monkeypatch):
    monkeypatch.setattr(llm, "_record_llm_metric", lambda **_kwargs: None)

    async def _ok_request(*_args, **_kwargs):
        return {
            "choices": [{"message": {"content": ""}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    monkeypatch.setattr(llm, "_retry_with_backoff", _ok_request)

    cfg = SimpleNamespace(
        OPENAI_API_KEY="secret",
        OPENAI_MODEL="gpt-test",
        OPENAI_TIMEOUT=10,
        ENABLE_TRACING=False,
    )
    client = llm.OpenAIClient(cfg)

    result = asyncio.run(client.chat([{"role": "user", "content": "boş yanıt"}], stream=False, json_mode=True))
    payload = json.loads(result)

    assert payload["tool"] == "final_answer"
    assert "boş içerik" in payload["argument"]
    assert "JSON dışı" in payload["thought"]


def test_openai_stream_connection_drop_returns_fallback_payload_after_partial_output(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ilk parça"}}]}'
            raise RuntimeError("socket closed")

    class _StreamCM:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return _Response()

        async def __aexit__(self, *_args):
            self.closed = True
            return False

    class _AsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout
            self.closed = False

        def stream(self, *_args, **_kwargs):
            return _StreamCM()

        async def aclose(self):
            self.closed = True

    async def _call_operation(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _AsyncClient, raising=False)
    monkeypatch.setattr(llm, "_retry_with_backoff", _call_operation)

    cfg = SimpleNamespace(OPENAI_API_KEY="secret", OPENAI_MODEL="gpt-test", OPENAI_TIMEOUT=10, ENABLE_TRACING=False)
    client = llm.OpenAIClient(cfg)

    out = asyncio.run(
        _collect(
            client._stream_openai(
                payload={"stream": True},
                headers={"Authorization": "Bearer secret"},
                timeout=llm.httpx.Timeout(10),
                json_mode=True,
            )
        )
    )

    assert out[0] == "ilk parça"
    fallback = json.loads(out[1])
    assert "OpenAI akış hatası" in fallback["argument"]
    assert "socket closed" in fallback["argument"]