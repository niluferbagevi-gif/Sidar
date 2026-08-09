"""Semantic cache adapter for LLM chat calls."""

from __future__ import annotations

from typing import Any

from core.cache.semantic_cache import SemanticCacheManager
from core.cache_metrics import record_cache_skip


class SemanticChatCache:
    """Small facade over semantic cache get/set and stream skip metrics."""

    def __init__(self, config: Any) -> None:
        self._cache = SemanticCacheManager(config)

    async def get(self, user_prompt: str) -> str | None:
        """Return a cached response for a non-empty user prompt, if present."""
        if not user_prompt:
            return None
        cached_response = await self._cache.get(user_prompt)
        return None if cached_response is None else str(cached_response)

    async def set(self, user_prompt: str, response: str) -> None:
        """Persist a non-streaming chat response in semantic cache."""
        if user_prompt:
            await self._cache.set(user_prompt, response)

    @staticmethod
    def record_stream_skip() -> None:
        """Record that semantic cache was skipped for a streaming response."""
        record_cache_skip()
