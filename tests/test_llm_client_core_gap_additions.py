import asyncio
from types import SimpleNamespace

import pytest

from tests.test_llm_client_runtime import _collect, _load_llm_client_module


@pytest.fixture
def llm_mod():
    return _load_llm_client_module()


def test_build_provider_json_mode_config_supported_and_unknown(llm_mod):
    assert llm_mod.build_provider_json_mode_config("ollama") == {"format": llm_mod.SIDAR_TOOL_JSON_SCHEMA}
    assert llm_mod.build_provider_json_mode_config("openai") == {"response_format": {"type": "json_object"}}
    assert llm_mod.build_provider_json_mode_config("gemini") == {
        "generation_config": {"response_mime_type": "application/json"}
    }
    assert llm_mod.build_provider_json_mode_config("anthropic") == {}
    assert llm_mod.build_provider_json_mode_config("bilinmeyen") == {}


def test_ollama_chat_reraises_llm_api_error(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    async def _raise(*args, **kwargs):
        raise llm_mod.LLMAPIError("ollama", "retry failed", retryable=True)

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise)

    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False))
    assert exc.value.provider == "ollama"


def test_ollama_chat_sets_total_ms_when_span_exists(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False, ENABLE_TRACING=True)
    client = llm_mod.OllamaClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "{\"ok\": true}"}}

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return _Resp()

    class _Span:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, key, value):
            self.attributes[key] = value

    class _SpanCM:
        def __init__(self, span):
            self._span = span

        def __enter__(self):
            return self._span

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Tracer:
        def __init__(self):
            self.span = _Span()

        def start_as_current_span(self, _name):
            return _SpanCM(self.span)

    tracer = _Tracer()
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)
    monkeypatch.setattr(llm_mod, "_get_tracer", lambda _cfg: tracer)

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    assert result == '{"ok": true}'
    assert "sidar.llm.total_ms" in tracer.span.attributes


def test_ollama_stream_response_trailing_decoder_and_aclose(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)
    closed = {"client": False}

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":"ilk"}}\n{"message":{"content":"iki"}}\nnot-json\n'

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def stream(self, method, url, json):
            return _StreamCtx()

        async def aclose(self):
            closed["client"] = True

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)

    out = asyncio.run(
        _collect(client._stream_response("http://localhost/api/chat", {"x": 1}, timeout=llm_mod.httpx.Timeout(10)))
    )
    assert out == ["ilk", "iki"]
    assert closed["client"] is True


def test_anthropic_json_mode_config_and_stream_skips_non_content_delta(llm_mod):
    cfg = SimpleNamespace()
    client = llm_mod.AnthropicClient(cfg)
    assert client.json_mode_config() == {}

    class _Event:
        def __init__(self, typ, delta_type=None, text=""):
            self.type = typ
            self.delta = SimpleNamespace(type=delta_type, text=text)

    class _OpenedStream:
        def __aiter__(self):
            async def _gen():
                yield _Event("message_start")
                yield _Event("content_block_delta", "not_text")
                yield _Event("content_block_delta", "text_delta", "merhaba")
            return _gen()

    class _CM:
        async def __aenter__(self):
            return _OpenedStream()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _Messages:
        def stream(self, **kwargs):
            return _CM()

    fake_client = SimpleNamespace(messages=_Messages())

    out = asyncio.run(
        _collect(
            client._stream_anthropic(
                client=fake_client,
                model_name="claude",
                messages=[{"role": "user", "content": "x"}],
                system_prompt="",
                temperature=0.1,
                json_mode=True,
            )
        )
    )
    assert out == ["merhaba"]


def test_anthropic_chat_stream_returns_traced_iterator(llm_mod, monkeypatch):
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ANTHROPIC_TIMEOUT=20, ENABLE_TRACING=False)
    client = llm_mod.AnthropicClient(cfg)

    class _AsyncAnthropic:
        def __init__(self, api_key, timeout):
            self.api_key = api_key
            self.timeout = timeout

    import types
    import sys

    sys.modules["anthropic"] = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)

    async def _fake_stream(**kwargs):
        yield "x"
        yield "y"

    monkeypatch.setattr(client, "_stream_anthropic", _fake_stream)

    stream_iter = asyncio.run(
        client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=True)
    )
    out = asyncio.run(_collect(stream_iter))
    assert out == ["x", "y"]