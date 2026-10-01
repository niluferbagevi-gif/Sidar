"""Contract tests for ``core.llm.gemini`` against the real google-genai SDK.

The other Gemini tests replace ``google.genai.Client`` with a double, so they
cannot notice when the request shape Sidar builds is rejected by the SDK's own
pydantic validation. These tests keep the real ``Client`` and only swap its
HTTP transport for ``httpx.MockTransport``: content/config conversion, request
building and response parsing all run through the installed google-genai.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import httpx
import pytest

import core.llm_client as llm_client
from tests.helpers import collect_async_chunks as _collect
from tests.helpers import make_test_config as _make_config

google_genai = pytest.importorskip("google.genai")

_MESSAGES = [
    {"role": "system", "content": "Sen bir asistansın."},
    {"role": "user", "content": "Selam"},
    {"role": "assistant", "content": "Merhaba"},
    {"role": "user", "content": "Nasılsın?"},
]


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Route the real google-genai client through an in-memory HTTP transport.

    Returns the list that collects each outgoing request's URL and JSON body.
    """
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"url": str(request.url), "body": json.loads(request.content or b"{}")})
        if "streamGenerateContent" in str(request.url):
            chunks = [
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "Mer"}]}}]},
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "haba"}]}}]},
            ]
            sse = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=sse.encode()
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": '{"tool":"final_answer","argument":"ok","thought":"t"}'}
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
            },
        )

    real_client = google_genai.Client

    def client_with_mock_transport(**kwargs: Any) -> Any:
        kwargs["http_options"] = {"async_client_args": {"transport": httpx.MockTransport(handler)}}
        return real_client(**kwargs)

    monkeypatch.setattr(
        importlib.import_module("google.genai"), "Client", client_with_mock_transport
    )
    return captured


@pytest.mark.asyncio
async def test_gemini_chat_request_passes_real_sdk_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat history, system prompt and JSON config reach the API in SDK-valid form."""
    captured = _install_mock_transport(monkeypatch)
    client = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm"))

    out = await client.chat(_MESSAGES, stream=False, json_mode=True)

    assert json.loads(out)["argument"] == "ok"
    assert len(captured) == 1
    request = captured[0]
    assert request["url"].endswith("/models/gm:generateContent")
    body = request["body"]
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "Selam"}]},
        {"role": "model", "parts": [{"text": "Merhaba"}]},
        {"role": "user", "parts": [{"text": "Nasılsın?"}]},
    ]
    assert body["systemInstruction"]["parts"][0]["text"].startswith("Sen bir asistansın.")
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_gemini_stream_request_passes_real_sdk_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming chat parses SSE chunks from the real SDK without JSON mode."""
    captured = _install_mock_transport(monkeypatch)
    client = llm_client.GeminiClient(_make_config(GEMINI_API_KEY="k", GEMINI_MODEL="gm"))

    stream = await client.chat(_MESSAGES, stream=True, json_mode=False, temperature=0.7)

    assert "".join(await _collect(stream)) == "Merhaba"
    assert len(captured) == 1
    request = captured[0]
    assert "streamGenerateContent" in request["url"]
    assert request["body"]["generationConfig"]["temperature"] == 0.7
    assert "responseMimeType" not in request["body"]["generationConfig"]
