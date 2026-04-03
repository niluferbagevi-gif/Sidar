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

import core.llm_client as llm_client


def test_litellm_candidate_models_deduplicates_and_trims() -> None:
    cfg = SimpleNamespace(
        LITELLM_MODEL="  gpt-primary  ",
        OPENAI_MODEL="gpt-openai-fallback",
        LITELLM_FALLBACK_MODELS=["gpt-secondary", " gpt-primary ", "", "gpt-tertiary"],
    )
    client = llm_client.LiteLLMClient(cfg)

    models = client._candidate_models(None)

    assert models == ["gpt-primary", "gpt-secondary", "gpt-tertiary"]


def test_litellm_chat_falls_back_to_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="https://litellm.local",
        LITELLM_API_KEY="",
        LITELLM_TIMEOUT=30,
        ENABLE_TRACING=False,
        LITELLM_MODEL="gpt-primary",
        LITELLM_FALLBACK_MODELS=["gpt-secondary"],
    )
    client = llm_client.LiteLLMClient(cfg)

    calls: list[str] = []

    class _FakeResponse:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def raise_for_status(self) -> None:
            if self.model_name == "gpt-primary":
                raise RuntimeError("primary provider failure")

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": json.dumps({"tool": "final_answer", "argument": "ok"})}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, _url: str, *, json: dict, headers: dict):
            model_name = json["model"]
            calls.append(model_name)
            return _FakeResponse(model_name)

    async def _retry_passthrough(_provider: str, operation, **_kwargs):
        return await operation()

    monkeypatch.setattr(llm_client.httpx, "Timeout", lambda *_args, **_kwargs: object(), raising=False)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(llm_client, "_retry_with_backoff", _retry_passthrough)
    monkeypatch.setattr(llm_client, "_record_llm_metric", lambda **_kwargs: None)

    result = asyncio.run(client.chat(messages=[{"role": "user", "content": "Merhaba"}], stream=False, json_mode=True))

    assert calls == ["gpt-primary", "gpt-secondary"]
    assert json.loads(result)["argument"] == "ok"
