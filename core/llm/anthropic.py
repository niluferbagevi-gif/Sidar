"""Anthropic provider adapter module.

This adapter re-exports the :class:`AnthropicClient` class from ``core.llm_client``.
The implementation of the Anthropic chat client remains in ``core.llm_client``.
Importing from ``core.llm.anthropic`` offers a stable provider-specific entry point
and enables separating provider logic into distinct modules later on.
"""

from ..llm_client import AnthropicClient as AnthropicClient

__all__ = ["AnthropicClient"]
