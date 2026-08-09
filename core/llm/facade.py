"""LLM facade support types shared outside the monolithic client module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class LLMProvider(Protocol):
    """Strategy contract implemented by provider adapters behind the LLM facade."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Generate streaming text chunks for the given chat messages."""
        ...

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        stream: bool = False,
        json_mode: bool = True,
    ) -> str | AsyncIterator[str]:
        """Provider-specific chat call used by the compatibility facade."""
        ...
