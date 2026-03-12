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

    # Bazı web server testleri core.llm_metrics'i minimal stub ile kirletebilir;
    # llm_client testlerinde gerçek modülün yeniden yüklenmesini zorlarız.
    sys.modules.pop("core.llm_metrics", None)

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

    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False))
    assert exc.value.provider == "ollama"


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


def test_ollama_helpers_gpu_and_stream_error_paths(llm_mod, monkeypatch):
    config = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=3, USE_GPU=True, CODING_MODEL="m")
    client = llm_mod.OllamaClient(config)

    assert client.base_url == "http://localhost:11434"
    timeout = client._build_timeout()
    assert isinstance(timeout, llm_mod.httpx.Timeout)
    assert timeout.timeout == 10

    captured = {}

    async def fake_stream(url, payload, timeout):
        captured["payload"] = payload
        yield "parca"

    original_stream = client._stream_response
    monkeypatch.setattr(client, "_stream_response", fake_stream)
    stream_iter = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=False))
    got = asyncio.run(_collect(stream_iter))
    monkeypatch.setattr(client, "_stream_response", original_stream)
    assert got == ["parca"]
    assert captured["payload"]["options"]["num_gpu"] == -1
    assert "format" not in captured["payload"]

    class _BadClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, json):
            raise RuntimeError("stream failed")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _BadClient)
    errs = asyncio.run(
        _collect(client._stream_response("http://localhost/api/chat", {"x": 1}, timeout=llm_mod.httpx.Timeout(10)))
    )
    assert "Akış kesildi" in json.loads(errs[0])["argument"]


def test_ollama_list_models_and_is_available_fallbacks(llm_mod, monkeypatch):
    config = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    client = llm_mod.OllamaClient(config)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "a"}, {"name": "b"}]}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    assert asyncio.run(client.list_models()) == ["a", "b"]
    assert asyncio.run(client.is_available()) is True

    class _ClientErr(_Client):
        async def get(self, url):
            raise RuntimeError("down")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _ClientErr)
    assert asyncio.run(client.list_models()) == []
    assert asyncio.run(client.is_available()) is False


def test_gemini_chat_import_key_and_nonstream_paths(llm_mod, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "google.generativeai":
            raise ImportError("forced missing gemini sdk")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    cfg = SimpleNamespace(GEMINI_API_KEY="", GEMINI_MODEL="gemini-model", ENABLE_TRACING=False)
    client = llm_mod.GeminiClient(cfg)

    no_pkg = asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))
    assert "google-generativeai" in json.loads(no_pkg)["argument"]

    no_pkg_stream = asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=True))
    got = asyncio.run(_collect(no_pkg_stream))
    assert "google-generativeai" in json.loads(got[0])["argument"]


def test_gemini_chat_with_stubbed_module_and_streaming(llm_mod, monkeypatch):
    calls = {}

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Session:
        def __init__(self, history):
            calls["history"] = history

        async def send_message_async(self, prompt, stream=False):
            calls.setdefault("prompts", []).append((prompt, stream))
            if stream:
                async def _gen():
                    yield SimpleNamespace(text="s1")
                    yield SimpleNamespace(text="")
                    yield SimpleNamespace(text="s2")
                return _gen()
            return _Resp("plain")

    class _Model:
        def __init__(self, **kwargs):
            calls["model_kwargs"] = kwargs

        def start_chat(self, history):
            return _Session(history)

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key: calls.setdefault("api_key", api_key)
    fake_genai.GenerativeModel = _Model

    google_pkg = types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    # force fallback safety_settings branch
    monkeypatch.delitem(sys.modules, "google.generativeai.types", raising=False)

    cfg = SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=False)
    client = llm_mod.GeminiClient(cfg)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]

    nonstream = asyncio.run(client.chat(messages, stream=False, json_mode=False))
    assert nonstream == "plain"
    assert calls["api_key"] == "k"
    assert calls["model_kwargs"]["system_instruction"] == "sys"
    assert calls["prompts"][0] == ("u2", False)

    stream_iter = asyncio.run(client.chat(messages, stream=True, json_mode=False))
    stream_chunks = asyncio.run(_collect(stream_iter))
    assert stream_chunks == ["s1", "s2"]

    class _SessionErr(_Session):
        async def send_message_async(self, prompt, stream=False):
            raise RuntimeError("gemini fail")

    class _ModelErr(_Model):
        def start_chat(self, history):
            return _SessionErr(history)

    fake_genai.GenerativeModel = _ModelErr
    err_msg = asyncio.run(client.chat(messages, stream=False, json_mode=True))
    assert "Gemini" in json.loads(err_msg)["argument"]


def test_openai_chat_nonstream_error_stream_and_json_mode(llm_mod, monkeypatch):
    config = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=60, OPENAI_MODEL="gpt-x")
    client = llm_mod.OpenAIClient(config)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "raw-text"}}]}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers):
            return _Resp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    wrapped = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    assert json.loads(wrapped)["argument"] == "raw-text"

    plain = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=False))
    assert plain == "raw-text"

    class _ClientErr(_Client):
        async def post(self, url, json, headers):
            raise RuntimeError("openai down")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _ClientErr)
    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False))
    assert exc.value.provider == "openai"

    stream_err_iter = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True))
    stream_err = asyncio.run(_collect(stream_err_iter))
    assert "OpenAI" in json.loads(stream_err[0])["argument"]


def test_openai_stream_error_and_llmclient_non_ollama_helpers(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=60)
    client = llm_mod.OpenAIClient(cfg)

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, json, headers):
            raise RuntimeError("stream down")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(
        _collect(client._stream_openai(payload={"stream": True}, headers={"a": "b"}, timeout=llm_mod.httpx.Timeout(10), json_mode=False))
    )
    assert "OpenAI akış hatası" in json.loads(out[0])["argument"]

    gem_cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=7, GEMINI_API_KEY="")
    fac = llm_mod.LLMClient("gemini", gem_cfg)
    assert fac._ollama_base_url == "http://localhost:11434"
    assert asyncio.run(fac.list_ollama_models()) == []
    assert asyncio.run(fac.is_ollama_available()) is False

    async def fake_chat(**kwargs):
        msgs = kwargs["messages"]
        assert msgs[0]["role"] == "system"
        return "ok"

    fac._client.chat = fake_chat
    assert asyncio.run(fac.chat([{"role": "user", "content": "u"}], system_prompt="s")) == "ok"

    class _WrapperResponse:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    chunks = asyncio.run(_collect(fac._stream_gemini_generator(_WrapperResponse())))
    assert chunks == []

def test_module_load_without_opentelemetry_sets_trace_none(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "opentelemetry":
            raise ImportError("otel yok")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    mod = _load_llm_client_module()
    assert mod.trace is None


def test_get_tracer_and_ollama_generic_error_paths(llm_mod, monkeypatch):
    class _Span:
        def __init__(self):
            self.attrs = {}
            self.exited = False

        def set_attribute(self, k, v):
            self.attrs[k] = v

        def end(self):
            self.exited = True

    class _CM:
        def __init__(self, span):
            self.span = span
            self.closed = False

        def __enter__(self):
            return self.span

        def __exit__(self, *args):
            self.closed = True
            return False

    class _Tracer:
        def __init__(self):
            self.span = _Span()
            self.cm = _CM(self.span)

        def start_as_current_span(self, _name):
            return self.cm

        def start_span(self, _name):
            return self.span

    tr = _Tracer()

    class _TraceMod:
        @staticmethod
        def get_tracer(_name):
            return tr

    monkeypatch.setattr(llm_mod, "trace", _TraceMod)
    assert llm_mod._get_tracer(SimpleNamespace(ENABLE_TRACING=True)) is tr

    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False, CODING_MODEL="m", ENABLE_TRACING=True)
    c = llm_mod.OllamaClient(cfg)

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            raise RuntimeError("ollama boom")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(c.chat([{"role": "user", "content": "u"}], stream=False))
    assert tr.span.attrs["sidar.llm.provider"] == "ollama"
    assert tr.cm.closed is True

    s_iter = asyncio.run(c.chat([{"role": "user", "content": "u"}], stream=True))
    s_out = asyncio.run(_collect(s_iter))
    assert "Akış kesildi" in json.loads(s_out[0])["argument"]


def test_ollama_stream_trailing_decoder_and_jsondecode_continue(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=60, USE_GPU=False)
    c = llm_mod.OllamaClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'\n'
            yield b'{"message":{"content":"A"}}\n{bad}\n'
            yield b'{"message":{"content":"B"}}'

    class _SCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, json):
            return _SCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(c._stream_response("u", {"x": 1}, timeout=llm_mod.httpx.Timeout(10))))
    assert out == ["A", "B"]


def test_gemini_missing_key_try_safety_and_trace_paths(llm_mod, monkeypatch):
    calls = {}

    class _Resp:
        text = "ok"

    class _Sess:
        async def send_message_async(self, prompt, stream=False):
            calls.setdefault("prompts", []).append((prompt, stream))
            return _Resp()

    class _Model:
        def __init__(self, **kwargs):
            calls["model_kwargs"] = kwargs

        def start_chat(self, history):
            calls["history"] = history
            return _Sess()

    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda api_key: calls.setdefault("api_key", api_key)
    fake_genai.GenerativeModel = _Model

    types_mod = types.ModuleType("google.generativeai.types")
    types_mod.HarmBlockThreshold = types.SimpleNamespace(BLOCK_NONE="NONE")
    types_mod.HarmCategory = types.SimpleNamespace(
        HARM_CATEGORY_HARASSMENT="H",
        HARM_CATEGORY_HATE_SPEECH="HS",
        HARM_CATEGORY_SEXUALLY_EXPLICIT="S",
        HARM_CATEGORY_DANGEROUS_CONTENT="D",
    )

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.generativeai.types", types_mod)

    # missing key path
    c1 = llm_mod.GeminiClient(SimpleNamespace(GEMINI_API_KEY="", GEMINI_MODEL="gm", ENABLE_TRACING=False))
    msg = asyncio.run(c1.chat([{"role": "user", "content": "u"}], stream=False))
    assert "GEMINI_API_KEY" in json.loads(msg)["argument"]

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, k, v):
            self.attrs[k] = v

    class _CM:
        def __init__(self, span):
            self.span = span
            self.closed = False

        def __enter__(self):
            return self.span

        def __exit__(self, *args):
            self.closed = True
            return False

    class _Tracer:
        def __init__(self):
            self.span = _Span()
            self.cm = _CM(self.span)

        def start_as_current_span(self, _):
            return self.cm

        def start_span(self, _):
            return self.span

    tr = _Tracer()

    class _TraceMod:
        @staticmethod
        def get_tracer(_):
            return tr

    monkeypatch.setattr(llm_mod, "trace", _TraceMod)

    c2 = llm_mod.GeminiClient(SimpleNamespace(GEMINI_API_KEY="k", GEMINI_MODEL="gm", ENABLE_TRACING=True))
    # no user role -> last message fallback line 343
    out = asyncio.run(c2.chat([{"role": "assistant", "content": "cevap"}], stream=False, json_mode=False))
    assert out == "ok"
    assert tr.span.attrs["sidar.llm.provider"] == "gemini"
    assert tr.cm.closed is True


def test_openai_stream_skips_non_data_and_invalid_json_and_factory_openai(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=60, OPENAI_MODEL="m", OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=11)
    c = llm_mod.OpenAIClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield "event: ping"
            yield "data: {bad}"
            yield 'data: {"choices":[{"delta":{"content":"X"}}]}'
            yield "data: [DONE]"

    class _SCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, json, headers):
            return _SCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(c._stream_openai(payload={"stream": True}, headers={"a": "b"}, timeout=llm_mod.httpx.Timeout(10), json_mode=True)))
    assert out == ["X"]

    fac = llm_mod.LLMClient("openai", cfg)
    assert isinstance(fac._client, llm_mod.OpenAIClient)
    t = fac._build_ollama_timeout()
    assert isinstance(t, llm_mod.httpx.Timeout)


def test_llmclient_ollama_helpers_and_stream_wrapper_fallback_branch(llm_mod, monkeypatch):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=12)
    fac = llm_mod.LLMClient("ollama", cfg)

    async def _lm():
        return ["m1"]

    async def _ok():
        return True

    monkeypatch.setattr(fac._client, "list_models", _lm)
    monkeypatch.setattr(fac._client, "is_available", _ok)
    assert asyncio.run(fac.list_ollama_models()) == ["m1"]
    assert asyncio.run(fac.is_ollama_available()) is True

    # non-gemini fallback branch in wrapper
    class _S:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    openai_fac = llm_mod.LLMClient("openai", SimpleNamespace(OPENAI_API_KEY="k", OPENAI_TIMEOUT=10, OLLAMA_URL="http://x/api", OLLAMA_TIMEOUT=10))
    chunks = asyncio.run(_collect(openai_fac._stream_gemini_generator(_S())))
    assert chunks == []

def test_llmclient_invalid_provider_raises_value_error(llm_mod):
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=12)
    try:
        llm_mod.LLMClient("gecersiz_saglayici", cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Bilinmeyen AI sağlayıcısı" in str(exc)


def test_llmclient_stream_gemini_generator_uses_temp_client_for_non_gemini(llm_mod, monkeypatch):
    cfg = SimpleNamespace(
        OPENAI_API_KEY="k",
        OPENAI_TIMEOUT=10,
        OLLAMA_URL="http://x/api",
        OLLAMA_TIMEOUT=10,
        GEMINI_API_KEY="g",
        GEMINI_MODEL="gemini-2.0-flash",
        GEMINI_TIMEOUT=10,
    )
    fac = llm_mod.LLMClient("openai", cfg)

    called = {"v": False}

    async def _fake_stream(self, response_stream):
        called["v"] = True
        async for _item in response_stream:
            yield "proxy-chunk"

    monkeypatch.setattr(llm_mod.GeminiClient, "_stream_gemini_generator", _fake_stream)

    class _S:
        def __init__(self):
            self._done = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return object()

    chunks = asyncio.run(_collect(fac._stream_gemini_generator(_S())))
    assert called["v"] is True
    assert chunks == ["proxy-chunk"]
