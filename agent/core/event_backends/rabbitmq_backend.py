"""RabbitMQ transport backend that delegates bootstrap and publish to ``AgentEventBus``."""

from __future__ import annotations

from typing import Any

from .base import BaseEventBusBackend


class RabbitMQBackend(BaseEventBusBackend):
    """RabbitMQ strategy for ``AgentEventBus`` remote publishing."""

    def schedule_bootstrap(self) -> None:
        """Schedule the bus's RabbitMQ consumer bootstrap."""
        self.bus._schedule_rabbit_bootstrap()

    async def publish(self, evt: Any) -> bool:
        """Publish ``evt`` to RabbitMQ; returns whether it was delivered."""
        return await self.bus._publish_via_rabbit(evt)
