"""Gemini provider adapter module.

This adapter re-exports the :class:`GeminiClient` class from ``core.llm_client``.
The Gemini chat client is implemented in ``core.llm_client``. Importing from
``core.llm.gemini`` provides a provider-specific entry point and lays the
groundwork for moving provider logic into separate modules.
"""

from ..llm_client import GeminiClient as GeminiClient

__all__ = ["GeminiClient"]
