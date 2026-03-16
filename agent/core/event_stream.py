"""Ajan durum event stream'i: Redis Pub/Sub + process-içi fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import contextlib
import os
import time
import uuid
from dataclasses import dataclass
from typing import Dict

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    ts: float
    source: str
    message: str


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[int, asyncio.Queue[AgentEvent]] = {}
        self._instance_id = uuid.uuid4().hex
        self._channel = os.getenv("SIDAR_EVENT_BUS_CHANNEL", "sidar:agent_events")

        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client: Redis | None = None
        self._redis_pubsub = None
        self._redis_listener_task: asyncio.Task | None = None
        self._redis_bootstrap_task: asyncio.Task | None = None
        self._redis_available: bool | None = None

    def subscribe(self, maxsize: int = 200) -> tuple[int, asyncio.Queue[AgentEvent]]:
        sub_id = int(time.time() * 1000) ^ id(object())
        self._subscribers[sub_id] = asyncio.Queue(maxsize=max(10, maxsize))
        self._schedule_redis_bootstrap()
        return sub_id, self._subscribers[sub_id]

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)

    async def publish(self, source: str, message: str) -> None:
        evt = AgentEvent(ts=time.time(), source=source, message=message)
        self._fanout_local(evt)
        self._schedule_redis_bootstrap()
        await self._publish_via_redis(evt)

    def _schedule_redis_bootstrap(self) -> None:
        if self._redis_available is False:
            return
        if self._redis_bootstrap_task is not None and not self._redis_bootstrap_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._redis_bootstrap_task = loop.create_task(self._ensure_redis_listener())

    async def _ensure_redis_listener(self) -> None:
        if self._redis_available is False:
            return
        if self._redis_listener_task is not None and not self._redis_listener_task.done():
            return

        try:
            if self._redis_client is None:
                self._redis_client = Redis.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
                await self._redis_client.ping()

            if self._redis_pubsub is None:
                self._redis_pubsub = self._redis_client.pubsub()
                await self._redis_pubsub.subscribe(self._channel)

            self._redis_available = True
            self._redis_listener_task = asyncio.create_task(self._redis_listener_loop())
        except Exception as exc:
            self._redis_available = False
            logger.debug("AgentEventBus Redis bootstrap başarısız, local fallback kullanılacak: %s", exc)
            await self._cleanup_redis()

    async def _publish_via_redis(self, evt: AgentEvent) -> bool:
        if self._redis_available is False:
            return False

        await self._ensure_redis_listener()
        if not self._redis_client or self._redis_available is not True:
            return False

        payload = json.dumps({
            "sid": self._instance_id,
            "ts": evt.ts,
            "source": evt.source,
            "message": evt.message,
        }, ensure_ascii=False)
        try:
            await self._redis_client.publish(self._channel, payload)
            return True
        except Exception as exc:
            logger.debug("AgentEventBus Redis publish başarısız, local fallback: %s", exc)
            self._redis_available = False
            await self._cleanup_redis()
            return False

    async def _redis_listener_loop(self) -> None:
        assert self._redis_pubsub is not None
        while True:
            try:
                msg = await self._redis_pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("AgentEventBus Redis listener hatası: %s", exc)
                self._redis_available = False
                await self._cleanup_redis()
                return

            if not msg or msg.get("type") != "message":
                await asyncio.sleep(0.01)
                continue

            try:
                payload = json.loads(str(msg.get("data", "{}")))
                if payload.get("sid") == self._instance_id:
                    continue
                evt = AgentEvent(
                    ts=float(payload.get("ts", time.time())),
                    source=str(payload.get("source", "agent")),
                    message=str(payload.get("message", "")),
                )
            except Exception:
                continue

            self._fanout_local(evt)

    def _fanout_local(self, evt: AgentEvent) -> None:
        to_drop = []
        for sid, q in self._subscribers.items():
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                to_drop.append(sid)
        for sid in to_drop:
            self.unsubscribe(sid)

    async def _cleanup_redis(self) -> None:
        if self._redis_listener_task is not None and not self._redis_listener_task.done():
            self._redis_listener_task.cancel()
            with contextlib.suppress(Exception):
                await self._redis_listener_task
        self._redis_listener_task = None

        if self._redis_pubsub is not None:
            with contextlib.suppress(Exception):
                closer = getattr(self._redis_pubsub, "aclose", None) or self._redis_pubsub.close
                await closer()
        self._redis_pubsub = None

        if self._redis_client is not None:
            with contextlib.suppress(Exception):
                closer = getattr(self._redis_client, "aclose", None) or self._redis_client.close
                await closer()
        self._redis_client = None


_BUS = AgentEventBus()


def get_agent_event_bus() -> AgentEventBus:
    return _BUS
