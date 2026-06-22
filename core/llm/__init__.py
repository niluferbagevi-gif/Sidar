"""Provider adapter package for LLM providers.

This package exposes provider-specific client adapters used by the LLMClient facade.
Each adapter re-exports the corresponding provider class from ``core.llm_client``.
By importing adapters from this package rather than directly from ``core.llm_client``,
future refactors can move provider-specific logic into separate modules without
changing import sites.
"""

from .openai import OpenAIClient  # noqa: F401
from .anthropic import AnthropicClient  # noqa: F401
from .gemini import GeminiClient  # noqa: F401
from .ollama import OllamaClient  # noqa: F401
from .litellm import LiteLLMClient  # noqa: F401

__all__ = [
    "OpenAIClient",
    "AnthropicClient",
    "GeminiClient",
    "OllamaClient",
    "LiteLLMClient",
]
