from __future__ import annotations

from .base import BaseEventBusBackend


class KafkaBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_kafka_bootstrap()

    async def publish(self, evt) -> bool:
        return await self.bus._publish_via_kafka(evt)
