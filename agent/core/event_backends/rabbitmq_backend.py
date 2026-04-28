from __future__ import annotations

from typing import Any

from .base import BaseEventBusBackend


class RabbitMQBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_rabbit_bootstrap()

    async def publish(self, evt: Any) -> bool:
        return await self.bus._publish_via_rabbit(evt)
