from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from core.llm_client import AnthropicClient, LLMAPIError, OpenAIClient


@pytest.mark.asyncio
async def test_openai_missing_api_key_returns_error_json():
    cfg = SimpleNamespace(OPENAI_API_KEY="", OPENAI_MODEL="gpt-4o-mini", OPENAI_TIMEOUT=10)
    client = OpenAIClient(cfg)

    result = await client.chat(messages=[{"role": "user", "content": "test"}], stream=False, json_mode=True)

    assert "OPENAI_API_KEY" in result


@pytest.mark.asyncio
@respx.mock
async def test_openai_rate_limit_raises_retryable_error():
    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=10,
        LLM_MAX_RETRIES=0,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.02,
        ENABLE_TRACING=False,
    )
    client = OpenAIClient(cfg)
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate_limited"}})
    )

    with pytest.raises(LLMAPIError) as exc_info:
        await client.chat(messages=[{"role": "user", "content": "hello"}], stream=False, json_mode=True)

    err = exc_info.value
    assert err.provider == "openai"
    assert err.retryable is True
    assert err.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_openai_timeout_raises_retryable_error():
    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=10,
        LLM_MAX_RETRIES=0,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.02,
        ENABLE_TRACING=False,
    )
    client = OpenAIClient(cfg)
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(LLMAPIError) as exc_info:
        await client.chat(messages=[{"role": "user", "content": "hello"}], stream=False, json_mode=True)

    err = exc_info.value
    assert err.provider == "openai"
    assert err.retryable is True


@pytest.mark.asyncio
async def test_anthropic_missing_key_returns_error_json():
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_TIMEOUT=10, ANTHROPIC_MODEL="claude")
    client = AnthropicClient(cfg)

    result = await client.chat(messages=[{"role": "user", "content": "test"}], stream=False, json_mode=True)

    assert "ANTHROPIC_API_KEY" in result
