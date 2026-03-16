import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from tests.test_llm_client_runtime import _load_llm_client_module


def test_anthropic_chat_without_key_returns_error_json():
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_TIMEOUT=60, ANTHROPIC_MODEL="claude-3-5-sonnet-latest")

    client = llm_mod.AnthropicClient(cfg)
    out = asyncio.run(client.chat(messages=[{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))
    payload = json.loads(out)

    assert payload["tool"] == "final_answer"
    assert "ANTHROPIC_API_KEY" in payload["argument"]


def test_llm_client_factory_supports_anthropic():
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(
        ANTHROPIC_API_KEY="x",
        ANTHROPIC_TIMEOUT=60,
        ANTHROPIC_MODEL="claude-3-5-sonnet-latest",
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=30,
    )

    fac = llm_mod.LLMClient("anthropic", cfg)
    assert fac.provider == "anthropic"
    assert fac._client.__class__.__name__ == "AnthropicClient"


def test_llm_client_stream_gemini_generator_uses_existing_gemini_client(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=False)
    fac = llm_mod.LLMClient("gemini", cfg)

    called = {"count": 0}

    async def _fake_stream(self, response_stream):
        called["count"] += 1
        assert self is fac._client
        assert response_stream == "source"
        yield "chunk-1"

    monkeypatch.setattr(llm_mod.GeminiClient, "_stream_gemini_generator", _fake_stream)

    async def _collect(aiter):
        return [item async for item in aiter]

    out = asyncio.run(_collect(fac._stream_gemini_generator("source")))
    assert out == ["chunk-1"]
    assert called["count"] == 1


def test_anthropic_chat_span_and_error_paths(monkeypatch):
    llm_mod = _load_llm_client_module()

    class _Span:
        def __init__(self):
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def end(self):
            self.ended = True

    class _CM:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, *_args):
            return False

    class _Tracer:
        def __init__(self):
            self.span = _Span()

        def start_as_current_span(self, _name):
            return _CM(self.span)

        def start_span(self, _name):
            return self.span

    tracer = _Tracer()
    monkeypatch.setattr(llm_mod, "_get_tracer", lambda _cfg: tracer)

    class _AnthropicResponse:
        usage = SimpleNamespace(input_tokens=3, output_tokens=2)
        content = [SimpleNamespace(text='{"tool":"final_answer","argument":"ok","thought":"t"}')]

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = SimpleNamespace(create=self._create)

        async def _create(self, **_kwargs):  # pragma: no cover - patched via retry helper
            return _AnthropicResponse()

    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.AsyncAnthropic = _AsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", anthropic_mod)
    async def _ok_retry(*_args, **_kwargs):
        return _AnthropicResponse()

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _ok_retry)

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="x", ANTHROPIC_TIMEOUT=10, ANTHROPIC_MODEL="claude", ENABLE_TRACING=True)
    client = llm_mod.AnthropicClient(cfg)

    ok = asyncio.run(client.chat(messages=[{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))
    assert json.loads(ok)["argument"] == "ok"
    assert tracer.span.attrs["sidar.llm.provider"] == "anthropic"
    assert tracer.span.attrs["sidar.llm.model"] == "claude"
    assert tracer.span.attrs["sidar.llm.stream"] is False
    assert "sidar.llm.total_ms" in tracer.span.attrs
    assert tracer.span.ended is True

    async def _raise_llm_error(*_args, **_kwargs):
        raise llm_mod.LLMAPIError("anthropic", "retry")

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise_llm_error)
    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(client.chat(messages=[{"role": "user", "content": "x"}], stream=False, json_mode=False))

    async def _raise_runtime(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise_runtime)
    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(client.chat(messages=[{"role": "user", "content": "x"}], stream=False, json_mode=False))
    assert exc.value.provider == "anthropic"


def test_anthropic_stream_and_tracing_paths(monkeypatch):
    llm_mod = _load_llm_client_module()

    class _Span:
        def __init__(self):
            self.attrs = {}
            self.ended = False

        def set_attribute(self, key, value):
            self.attrs[key] = value

        def end(self):
            self.ended = True

    class _Tracer:
        def __init__(self):
            self.span = _Span()

        def start_span(self, _name):
            return self.span

        def start_as_current_span(self, _name):
            raise AssertionError("stream modunda start_as_current_span kullanılmamalı")

    tracer = _Tracer()
    monkeypatch.setattr(llm_mod, "_get_tracer", lambda _cfg: tracer)

    class _Evt:
        def __init__(self, ev_type, delta_type=None, text=""):
            self.type = ev_type
            self.delta = SimpleNamespace(type=delta_type, text=text) if delta_type else None

    class _Stream:
        def __aiter__(self):
            self._items = iter([
                _Evt("ignored"),
                _Evt("content_block_delta", "other", "x"),
                _Evt("content_block_delta", "text_delta", "A"),
                _Evt("content_block_delta", "text_delta", "B"),
            ])
            return self

        async def __anext__(self):
            try:
                return next(self._items)
            except StopIteration:
                raise StopAsyncIteration

    class _StreamCM:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return _Stream()

        async def __aexit__(self, *args):
            self.exited = True
            return False

    class _Messages:
        def __init__(self):
            self.cm = _StreamCM()

        def stream(self, **_kwargs):
            return self.cm

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _Messages()

    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.AsyncAnthropic = _AsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", anthropic_mod)

    async def _passthrough_retry(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _passthrough_retry)

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="x", ANTHROPIC_TIMEOUT=10, ANTHROPIC_MODEL="claude", ENABLE_TRACING=True)
    client = llm_mod.AnthropicClient(cfg)

    async def _collect(aiter):
        return [item async for item in aiter]

    stream_iter = asyncio.run(client.chat(messages=[{"role": "user", "content": "selam"}], stream=True, json_mode=True))
    chunks = asyncio.run(_collect(stream_iter))
    assert chunks == ["A", "B"]
    assert tracer.span.attrs["sidar.llm.provider"] == "anthropic"
    assert tracer.span.attrs["sidar.llm.stream"] is True
    assert "sidar.llm.ttft_ms" in tracer.span.attrs
    assert "sidar.llm.total_ms" in tracer.span.attrs
    assert tracer.span.ended is True


def test_stream_anthropic_error_yields_safe_json(monkeypatch):
    llm_mod = _load_llm_client_module()
    client = llm_mod.AnthropicClient(SimpleNamespace(ANTHROPIC_API_KEY="x", ANTHROPIC_TIMEOUT=10, ANTHROPIC_MODEL="claude", ENABLE_TRACING=False))

    class _BrokenMessages:
        def stream(self, **_kwargs):
            class _CM:
                async def __aenter__(self):
                    raise RuntimeError("stream open boom")

                async def __aexit__(self, *args):
                    return False

            return _CM()

    broken_client = SimpleNamespace(messages=_BrokenMessages())

    async def _retry_passthrough(_provider, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _retry_passthrough)

    async def _collect(aiter):
        return [item async for item in aiter]

    out = asyncio.run(
        _collect(
            client._stream_anthropic(
                client=broken_client,
                model_name="claude",
                messages=[{"role": "user", "content": "x"}],
                system_prompt="",
                temperature=0.3,
                json_mode=True,
            )
        )
    )
    payload = json.loads(out[0])
    assert payload["tool"] == "final_answer"
    assert "Anthropic akış hatası" in payload["argument"]