from __future__ import annotations

import importlib
from typing import Any

import pytest

PROVIDER_MODULES = [
    "core.llm.anthropic",
    "core.llm.gemini",
    "core.llm.litellm",
    "core.llm.openai",
    "core.llm.ollama",
]

COMMON_WRAPPER_CASES: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
    ("_setting", ("config", "NAME", "default"), {}),
    ("_extract_usage_tokens", ({"usage": {"prompt_tokens": 1}},), {}),
    ("_extract_gemini_usage_tokens", (object(),), {}),
    ("_fallback_stream", ("message",), {}),
    ("_prepare_span_scope", ("config", "span.name", False), {}),
    ("_record_llm_metric", (), {"provider": "test", "model": "model", "success": True}),
    ("_retry_with_backoff", ("provider", lambda: "ok"), {"config": object()}),
    (
        "_track_stream_completion",
        ("stream",),
        {"provider": "test", "model": "model", "started_at": 1.25},
    ),
    ("_trace_stream_metrics", ("stream", "span", 1.25), {}),
]

OLLAMA_ONLY_WRAPPER_CASES: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
    ("_ollama_gpu_limiter", ("http://localhost:11434", 1), {}),
    ("_ollama_gpu_pool_size", ("config",), {}),
    ("_release_limiter_after_stream", ("stream", "limiter"), {}),
]

SYNC_WRAPPER_CASES = [
    pytest.param(module_name, attr_name, args, kwargs, id=f"{module_name}.{attr_name}")
    for module_name in PROVIDER_MODULES
    for attr_name, args, kwargs in COMMON_WRAPPER_CASES
] + [
    pytest.param("core.llm.ollama", attr_name, args, kwargs, id=f"core.llm.ollama.{attr_name}")
    for attr_name, args, kwargs in OLLAMA_ONLY_WRAPPER_CASES
]


@pytest.mark.parametrize("module_name,attr_name,args,kwargs", SYNC_WRAPPER_CASES)
def test_wrapper_delegates_to_facade(
    module_name: str,
    attr_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(module_name)
    sentinel = object()
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_facade_wrapper(*call_args: Any, **call_kwargs: Any) -> object:
        calls.append((call_args, call_kwargs))
        return sentinel

    monkeypatch.setattr(module.llm_facade, attr_name, fake_facade_wrapper)

    assert getattr(module, attr_name)(*args, **kwargs) is sentinel
    assert calls == [(args, kwargs)]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name", PROVIDER_MODULES)
async def test_ensure_json_text_async_wrapper_delegates_to_facade(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(module_name)
    calls: list[tuple[str, str]] = []

    async def fake_ensure_json_text_async(text: str, provider: str) -> str:
        calls.append((text, provider))
        return "facade-result"

    monkeypatch.setattr(module.llm_facade, "_ensure_json_text_async", fake_ensure_json_text_async)

    assert await module._ensure_json_text_async("payload", "Provider") == "facade-result"
    assert calls == [("payload", "Provider")]


@pytest.mark.asyncio
async def test_anthropic_close_client_accepts_sync_close() -> None:
    module = importlib.import_module("core.llm.anthropic")

    class _Client:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = _Client()

    await module._close_anthropic_client(client)

    assert client.closed is True


def test_llm_package_getattr_raises_for_unknown_provider() -> None:
    llm_package = importlib.import_module("core.llm")

    with pytest.raises(AttributeError, match="unknown_attribute"):
        _ = llm_package.unknown_attribute


def test_llm_package_getattr_lazily_imports_and_caches_known_provider() -> None:
    llm_package = importlib.import_module("core.llm")
    llm_package.__dict__.pop("OllamaClient", None)
    ollama_module = importlib.import_module("core.llm.ollama")

    result = llm_package.OllamaClient

    assert result is ollama_module.OllamaClient
    # `__getattr__` yalnız modül `globals()`'ında eksikse çağrılır; cache sonrası
    # doğrudan öznitelik erişimi ikinci kez `import_module` tetiklemeden döner.
    assert llm_package.__dict__["OllamaClient"] is ollama_module.OllamaClient
    assert llm_package.OllamaClient is ollama_module.OllamaClient


def test_llm_package_all_lists_every_provider_export() -> None:
    llm_package = importlib.import_module("core.llm")

    assert set(llm_package.__all__) == {
        "AnthropicClient",
        "GeminiClient",
        "LiteLLMClient",
        "OllamaClient",
        "OpenAIClient",
    }
