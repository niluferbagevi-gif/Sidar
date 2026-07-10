"""Provider adapters for :mod:`core.llm_client`, exposed via lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_PROVIDER_EXPORTS: dict[str, tuple[str, str]] = {
    "AnthropicClient": ("core.llm.anthropic", "AnthropicClient"),
    "GeminiClient": ("core.llm.gemini", "GeminiClient"),
    "LiteLLMClient": ("core.llm.litellm", "LiteLLMClient"),
    "OllamaClient": ("core.llm.ollama", "OllamaClient"),
    "OpenAIClient": ("core.llm.openai", "OpenAIClient"),
}


def __getattr__(name: str) -> Any:
    """Lazy-load provider classes to avoid eager provider/facade cycles."""

    if name not in _PROVIDER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _PROVIDER_EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(_PROVIDER_EXPORTS)
