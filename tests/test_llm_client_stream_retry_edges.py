import asyncio
import json
from types import SimpleNamespace

import core.llm_client as llm


async def _collect(aiter):
    return [x async for x in aiter]


def _cfg(**kwargs):
    base = {
        "OPENAI_API_KEY": "k",
        "OPENAI_TIMEOUT": 10,
        "ANTHROPIC_API_KEY": "k",
        "LLM_MAX_RETRIES": 1,
        "LLM_RETRY_BASE_DELAY": 0.01,
        "LLM_RETRY_MAX_DELAY": 0.02,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_openai_chat_wraps_non_json_content_in_json_mode(monkeypatch):
    client = llm.OpenAIClient(_cfg())

    async def _fake_retry(*_args, **_kwargs):
        return {"choices": [{"message": {"content": "plain-text-response"}}]}

    monkeypatch.setattr(llm, "_retry_with_backoff", _fake_retry)
    out = asyncio.run(client.chat(messages=[{"role": "user", "content": "hi"}], stream=False, json_mode=True))

    parsed = json.loads(out)
    assert parsed["tool"] == "final_answer"
    assert "JSON dışı" in parsed["thought"]


def test_openai_stream_emits_error_chunk_when_stream_breaks(monkeypatch):
    client = llm.OpenAIClient(_cfg())

    class _Resp:
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            raise RuntimeError("stream-broken")

    class _CM:
        async def __aexit__(self, *_args):
            return False

    class _Client:
        async def aclose(self):
            return None

    async def _fake_retry(*_args, **_kwargs):
        return _Client(), _CM(), _Resp()

    monkeypatch.setattr(llm, "_retry_with_backoff", _fake_retry)

    chunks = asyncio.run(
        _collect(
            client._stream_openai(
                payload={"stream": True},
                headers={"Authorization": "Bearer k"},
                timeout=llm.httpx.Timeout(10),
                json_mode=True,
            )
        )
    )

    assert chunks[0] == "ok"
    assert "OpenAI akış hatası" in json.loads(chunks[-1])["argument"]


def test_anthropic_stream_emits_error_when_stream_opening_retry_fails(monkeypatch):
    client = llm.AnthropicClient(_cfg())

    async def _fail_retry(*_args, **_kwargs):
        raise llm.LLMAPIError("anthropic", "retry exhausted", retryable=True)

    monkeypatch.setattr(llm, "_retry_with_backoff", _fail_retry)

    stream = client._stream_anthropic(
        client=SimpleNamespace(messages=SimpleNamespace(stream=lambda **_kwargs: None)),
        model_name="claude-test",
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="",
        temperature=0.1,
        json_mode=True,
    )

    chunks = asyncio.run(_collect(stream))
    assert len(chunks) == 1
    assert "Anthropic akış hatası" in json.loads(chunks[0])["argument"]
