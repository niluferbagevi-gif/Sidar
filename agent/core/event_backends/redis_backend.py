"""Redis Streams transport backend that delegates bootstrap and publish to ``AgentEventBus``."""

from __future__ import annotations

from typing import Any

from .base import BaseEventBusBackend


class RedisBackend(BaseEventBusBackend):
    """Redis Streams strategy for ``AgentEventBus`` remote publishing."""

    def schedule_bootstrap(self) -> None:
        """Schedule the bus's Redis Streams consumer bootstrap."""
        self.bus._schedule_redis_bootstrap()

    async def publish(self, evt: Any) -> bool:
        """Publish ``evt`` to Redis Streams; returns whether it was delivered."""
        return await self.bus._publish_via_redis(evt)
