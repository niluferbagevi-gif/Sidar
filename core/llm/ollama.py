"""Ollama provider adapter module.

This adapter re-exports the :class:`OllamaClient` class from ``core.llm_client``.
The Ollama chat client implementation lives in ``core.llm_client``. Importing
from ``core.llm.ollama`` offers a provider-specific facade for future
refactoring and simplifies imports across the codebase.
"""

from ..llm_client import OllamaClient as OllamaClient

__all__ = ["OllamaClient"]
