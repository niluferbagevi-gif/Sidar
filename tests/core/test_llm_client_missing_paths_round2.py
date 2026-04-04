from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from types import SimpleNamespace
import types

import pytest

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.Timeout = object
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

import core.llm_client as llm


class _FakeStreamResponse:
    def __init__(self, lines: list[str] | None = None, *, fail_iter: bool = False) -> None:
        self._lines = lines or []
        self._fail_iter = fail_iter

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        if self._fail_iter:
            raise RuntimeError("stream-boom")
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return None


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse, *args, **kwargs) -> None:
        self._response = response
        self.closed = False

    def stream(self, *_args, **_kwargs):
        return _FakeStreamCM(self._response)

    async def aclose(self) -> None:
        self.closed = True



def test_openai_stream_parses_lines_and_stops_on_done(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(OPENAI_API_KEY="k")
    client = llm.OpenAIClient(cfg)

    response = _FakeStreamResponse(
        lines=[
            "bad-line",
            "data: not-json",
            'data: {"choices":[{"delta":{"content":"mer"}}]}',
            'data: {"choices":[{"delta":{"content":"haba"}}]}',
            "data: [DONE]",
        ]
    )

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(response, *a, **k))

    async def _collect() -> list[str]:
        stream = client._stream_openai({}, {}, timeout=object(), json_mode=True)
        return [chunk async for chunk in stream]

    assert asyncio.run(_collect()) == ["mer", "haba"]



def test_openai_stream_emits_error_payload_when_iteration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(OPENAI_API_KEY="k")
    client = llm.OpenAIClient(cfg)

    response = _FakeStreamResponse(fail_iter=True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(response, *a, **k))

    async def _collect() -> list[str]:
        stream = client._stream_openai({}, {}, timeout=object(), json_mode=False)
        return [chunk async for chunk in stream]

    chunks = asyncio.run(_collect())
    assert len(chunks) == 1
    assert "OpenAI akış hatası" in json.loads(chunks[0])["argument"]



def test_anthropic_split_system_and_stream_error_path() -> None:
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k")
    client = llm.AnthropicClient(cfg)

    system_text, convo = client._split_system_and_messages(
        [
            {"role": "system", "content": "S1"},
            {"role": "user", "content": "U1"},
            {"role": "system", "content": "S2"},
        ]
    )
    assert system_text == "S1\n\nS2"
    assert convo == [{"role": "user", "content": "U1"}]

    class _BrokenMessages:
        def stream(self, **_kwargs):
            raise RuntimeError("anthropic stream init failed")

    class _BrokenClient:
        messages = _BrokenMessages()

    async def _collect() -> list[str]:
        stream = client._stream_anthropic(
            client=_BrokenClient(),
            model_name="m",
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="",
            temperature=0.1,
            json_mode=True,
        )
        return [c async for c in stream]

    chunks = asyncio.run(_collect())
    payload = json.loads(chunks[0])
    assert payload["tool"] == "final_answer"
    assert "Anthropic akış hatası" in payload["argument"]



def test_llm_client_chat_routing_fallbacks_to_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(COST_ROUTING_TOKEN_COST_USD=2e-6, OPENAI_API_KEY="x")
    client = llm.LLMClient("openai", cfg)

    class _DefaultClient:
        async def chat(self, **_kwargs):
            return '{"tool":"final_answer","argument":"default"}'

    class _NoCache:
        async def get(self, _prompt):
            return None

        async def set(self, _prompt, _response):
            return None

    client._client = _DefaultClient()
    client._semantic_cache = _NoCache()
    client._router.select = lambda _messages, _provider, _model: ("gemini", "gemini-2.0")

    class _BrokenRoutedClient:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("route fail")

    monkeypatch.setattr(llm, "LLMClient", _BrokenRoutedClient)
    monkeypatch.setattr(llm, "_dlp_mask_messages", lambda messages: messages)
    monkeypatch.setattr(llm, "record_routing_cost", lambda _cost: None)

    # Fallback: routed client hata verdiğinde mevcut provider ile devam etmeli.
    result = asyncio.run(client.chat(messages=[{"role": "user", "content": "selam"}], stream=False))
    assert json.loads(result)["argument"] == "default"



def test_llm_client_stream_gemini_generator_uses_fallback_client() -> None:
    cfg = SimpleNamespace()
    client = llm.LLMClient("openai", cfg)

    async def _response_stream():
        yield SimpleNamespace(text="a")
        yield SimpleNamespace(text="")
        yield SimpleNamespace(text="b")

    async def _collect() -> list[str]:
        return [c async for c in client._stream_gemini_generator(_response_stream())]

    assert asyncio.run(_collect()) == ["a", "b"]
