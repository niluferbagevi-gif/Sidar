"""OpenAI provider adapter module.

This adapter re-exports the :class:`OpenAIClient` class from ``core.llm_client``. The
actual implementation of the OpenAI chat client resides in ``core.llm_client``.
Importing from ``core.llm.openai`` provides a stable entry point for
provider-specific logic and simplifies future refactoring.
"""

from ..llm_client import OpenAIClient as OpenAIClient

__all__ = ["OpenAIClient"]
