"""Unit tests for pure helper contracts in core.llm_client."""

from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from core.llm_client import (
    _ensure_json_text,
    _extract_usage_tokens,
    _is_retryable_exception,
    build_provider_json_mode_config,
)


def test_build_provider_json_mode_config_returns_expected_shapes() -> None:
    assert "format" in build_provider_json_mode_config("ollama")
    assert build_provider_json_mode_config("openai") == {"response_format": {"type": "json_object"}}
    assert build_provider_json_mode_config("gemini") == {
        "generation_config": {"response_mime_type": "application/json"}
    }
    assert build_provider_json_mode_config("anthropic") == {}
    assert build_provider_json_mode_config("unknown") == {}


def test_ensure_json_text_wraps_non_json_payload() -> None:
    raw = "plain text response"
    wrapped = _ensure_json_text(raw, "openai")
    parsed = json.loads(wrapped)

    assert parsed["tool"] == "final_answer"
    assert "JSON dışı" in parsed["thought"]
    assert parsed["argument"] == raw


def test_extract_usage_tokens_uses_prompt_and_completion_fields() -> None:
    payload = {"usage": {"prompt_tokens": 12, "completion_tokens": 34}}
    assert _extract_usage_tokens(payload) == (12, 34)

    payload_output_tokens = {"usage": {"prompt_tokens": 5, "output_tokens": 7}}
    assert _extract_usage_tokens(payload_output_tokens) == (5, 7)


def test_is_retryable_exception_identifies_network_and_rate_limits() -> None:
    retryable_timeout, _ = _is_retryable_exception(httpx.TimeoutException("timeout"))
    assert retryable_timeout is True

    transport_error = httpx.ConnectError("connect", request=httpx.Request("GET", "http://example.com"))
    retryable_connect, _ = _is_retryable_exception(transport_error)
    assert retryable_connect is True

    retryable_asyncio, _ = _is_retryable_exception(asyncio.TimeoutError())
    assert retryable_asyncio is True
