"""LiteLLM provider adapter module.

This adapter re-exports the :class:`LiteLLMClient` class from ``core.llm_client``.
The ``LiteLLMClient`` is a thin wrapper around the OpenAI Chat API that uses a
gateway server to route requests via the liteLLM library. Importing from
``core.llm.litellm`` provides a stable entry point for future separation of the
provider-specific logic.
"""

from ..llm_client import LiteLLMClient as LiteLLMClient

__all__ = ["LiteLLMClient"]
