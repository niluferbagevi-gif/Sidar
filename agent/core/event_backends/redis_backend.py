from __future__ import annotations

from .base import BaseEventBusBackend


class RedisBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_redis_bootstrap()

    async def publish(self, evt) -> bool:
        return await self.bus._publish_via_redis(evt)
