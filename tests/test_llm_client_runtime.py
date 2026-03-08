import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _StubTimeout:
    def __init__(self, timeout, connect=None):
        self.timeout = timeout
        self.connect = connect


class _StubConnectError(Exception):
    pass


def _load_llm_client_module():
    httpx_stub = types.SimpleNamespace(
        Timeout=_StubTimeout,
        ConnectError=_StubConnectError,
        AsyncClient=None,
    )
    sys.modules["httpx"] = httpx_stub

    path = Path("core/llm_client.py")
    spec = importlib.util.spec_from_file_location("llm_client_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _collect(aiter):
    return [item async for item in aiter]


@pytest.fixture
def llm_mod():
    return _load_llm_client_module()


class _FakeSpan:
    def __init__(self):
        self.attributes = {}
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def end(self):
        self.ended = True


class _RaisesAsyncIter:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise RuntimeError("stream boom")


def test_helpers_json_fallback_and_stream_fallback(llm_mod):
    assert llm_mod._ensure_json_text('{"ok": true}', "X") == '{"ok": true}'

    wrapped = llm_mod._ensure_json_text("raw", "OpenAI")
    data = json.loads(wrapped)
    assert data["tool"] == "final_answer"
    assert data["argument"] == "raw"

    items = asyncio.run(_collect(llm_mod._fallback_stream("err")))
    assert items == ["err"]


def test_trace_stream_metrics_sets_span_attributes(llm_mod):
    async def _gen():
        yield "a"
        yield "b"

    span = _FakeSpan()
    got = asyncio.run(_collect(llm_mod._trace_stream_metrics(_gen(), span, started_at=0.0)))

    assert got == ["a", "b"]
    assert "sidar.llm.total_ms" in span.attributes
    assert "sidar.llm.ttft_ms" in span.attributes
    assert span.ended is True


def test_ollama_chat_nonstream_json_mode_wraps_text(llm_mod, monkeypatch):
    config = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(config)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "plain text"}}

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            assert url.endswith("/api/chat")
            assert json["options"]["temperature"] == 0.3
            return _Resp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    payload = json.loads(result)
    assert payload["tool"] == "final_answer"
    assert payload["argument"] == "plain text"


def test_ollama_chat_connect_error_returns_final_answer(llm_mod, monkeypatch):
    config = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(config)

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            raise llm_mod.httpx.ConnectError("boom")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)

    result = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False))
    data = json.loads(result)
    assert data["tool"] == "final_answer"
    assert "Ollama" in data["argument"]


def test_ollama_stream_response_parses_chunks_and_trailing(llm_mod, monkeypatch):
    config = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(config)

    chunks = [
        b'{"message":{"content":"mer"}}\n',
        b'not-json\n{"message":{"content":"ha"}}',
    ]

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            for c in chunks:
                yield c

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, json):
            return _StreamCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)

    out = asyncio.run(
        _collect(client._stream_response("http://localhost/api/chat", {"x": 1}, timeout=llm_mod.httpx.Timeout(10)))
    )
    assert out == ["mer", "ha"]


def test_gemini_stream_generator_handles_exception(llm_mod):
    config = SimpleNamespace()
    client = llm_mod.GeminiClient(config)

    out = asyncio.run(_collect(client._stream_gemini_generator(_RaisesAsyncIter())))
    assert len(out) == 1
    err = json.loads(out[0])
    assert err["tool"] == "final_answer"
    assert "Gemini akış hatası" in err["argument"]


def test_openai_chat_without_key_and_stream_parse(llm_mod, monkeypatch):
    config = SimpleNamespace(OPENAI_API_KEY="", OPENAI_TIMEOUT=60)
    client = llm_mod.OpenAIClient(config)

    no_key = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False))
    assert "OPENAI_API_KEY" in json.loads(no_key)["argument"]

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield "data: {\"choices\": [{\"delta\": {\"content\": \"A\"}}]}"
            yield "data: [DONE]"

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class _HttpxClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, json, headers):
            return _StreamCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _HttpxClient)

    config2 = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=60)
    client2 = llm_mod.OpenAIClient(config2)
    got = asyncio.run(
        _collect(
            client2._stream_openai(
                payload={"stream": True},
                headers={"Authorization": "Bearer k"},
                timeout=llm_mod.httpx.Timeout(10),
                json_mode=True,
            )
        )
    )
    assert got == ["A"]


def test_llm_client_factory_and_compat_methods(llm_mod):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=1)

    client = llm_mod.LLMClient("ollama", cfg)
    assert client._ollama_base_url == "http://localhost:11434"
    assert isinstance(client._build_ollama_timeout(), llm_mod.httpx.Timeout)

    with pytest.raises(ValueError):
        llm_mod.LLMClient("unknown", cfg)
