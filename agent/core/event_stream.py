"""Ajan durum event stream'i: Redis Streams + process-içi fallback."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Dict

from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    ts: float
    source: str
    message: str


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[int, asyncio.Queue[AgentEvent]] = {}
        self._buffered_events: Dict[int, deque[AgentEvent]] = {}
        self._instance_id = uuid.uuid4().hex
        self._channel = os.getenv("SIDAR_EVENT_BUS_CHANNEL", "sidar:agent_events")
        self._consumer_group = os.getenv("SIDAR_EVENT_BUS_GROUP", "sidar:agent_events:cg")
        self._dlq_channel = os.getenv("SIDAR_EVENT_BUS_DLQ_CHANNEL", f"{self._channel}:dlq")
        self._dlq_buffer: deque[dict[str, object]] = deque(maxlen=max(10, int(os.getenv("SIDAR_EVENT_BUS_DLQ_MAXLEN", "1000") or "1000")))

        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_max_connections = max(1, int(os.getenv("REDIS_MAX_CONNECTIONS", "50") or "50"))
        self._redis_connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "0.5") or "0.5")
        self._redis_socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "0.5") or "0.5")
        self._redis_client: Redis | None = None
        self._redis_listener_task: asyncio.Task | None = None
        self._redis_bootstrap_task: asyncio.Task | None = None
        self._redis_available: bool | None = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, maxsize: int = 200) -> tuple[int, asyncio.Queue[AgentEvent]]:
        sub_id = int(time.time() * 1000) ^ id(object())
        self._subscribers[sub_id] = asyncio.Queue(maxsize=max(10, maxsize))
        self._schedule_redis_bootstrap()
        return sub_id, self._subscribers[sub_id]

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)
        self._buffered_events.pop(sub_id, None)

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
        await self._ensure_redis_loop_compatibility()
        if self._redis_listener_task is not None and not self._redis_listener_task.done():
            return

        try:
            loop = asyncio.get_running_loop()
            if self._redis_client is None:
                self._redis_client = Redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=self._redis_max_connections,
                    socket_connect_timeout=self._redis_connect_timeout,
                    socket_timeout=self._redis_socket_timeout,
                )
                await self._redis_client.ping()
                self._redis_loop = loop

            try:
                await self._redis_client.xgroup_create(
                    name=self._channel,
                    groupname=self._consumer_group,
                    id="0-0",
                    mkstream=True,
                )
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

            self._redis_available = True
            self._redis_listener_task = loop.create_task(self._redis_listener_loop())
        except Exception as exc:
            self._redis_available = False
            logger.debug("AgentEventBus Redis bootstrap başarısız, local fallback kullanılacak: %s", exc)
            await self._cleanup_redis()

    async def _publish_via_redis(self, evt: AgentEvent) -> bool:
        if self._redis_available is False:
            return False

        await self._ensure_redis_loop_compatibility()
        await self._ensure_redis_listener()
        if not self._redis_client or self._redis_available is not True:
            return False

        payload = json.dumps(
            {
                "sid": self._instance_id,
                "ts": evt.ts,
                "source": evt.source,
                "message": evt.message,
            },
            ensure_ascii=False,
        )
        try:
            await self._redis_client.xadd(self._channel, {"payload": payload})
            return True
        except Exception as exc:
            logger.debug("AgentEventBus Redis publish başarısız, local fallback: %s", exc)
            await self._write_dead_letter(
                reason="publish_failed",
                payload={"event": {"ts": evt.ts, "source": evt.source, "message": evt.message}},
                error=exc,
            )
            self._redis_available = False
            await self._cleanup_redis()
            return False

    async def _redis_listener_loop(self) -> None:
        assert self._redis_client is not None
        while True:
            try:
                response = await self._redis_client.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._instance_id,
                    streams={self._channel: ">"},
                    count=20,
                    block=1000,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("AgentEventBus Redis listener hatası: %s", exc)
                self._redis_available = False
                await self._cleanup_redis()
                return

            if not response:
                continue

            for _stream_name, entries in response:
                for msg_id, fields in entries:
                    payload_raw = fields.get("payload", "{}")
                    try:
                        payload = json.loads(str(payload_raw))
                        if payload.get("sid") != self._instance_id:
                            evt = AgentEvent(
                                ts=float(payload.get("ts", time.time())),
                                source=str(payload.get("source", "agent")),
                                message=str(payload.get("message", "")),
                            )
                            self._fanout_local(evt)
                    except Exception as exc:
                        await self._write_dead_letter(
                            reason="invalid_payload",
                            payload={"msg_id": msg_id, "payload": str(payload_raw)},
                            error=exc,
                        )
                    finally:
                        with contextlib.suppress(Exception):
                            try:
                                await self._redis_client.xack(self._channel, self._consumer_group, msg_id)
                            except Exception as exc:
                                await self._write_dead_letter(
                                    reason="ack_failed",
                                    payload={"msg_id": msg_id, "payload": str(payload_raw)},
                                    error=exc,
                                )

    async def _drain_buffered_events_once(self) -> bool:
        any_progress = False
        for sid, q in self._subscribers.items():
            buffer = self._buffered_events.get(sid)
            if not buffer:
                continue

            # Kuyruk doluysa event bir sonraki turda taşınmak üzere bekler.
            if q.full():
                any_progress = True
                continue

            evt = buffer.popleft()
            q.put_nowait(evt)
            any_progress = True

        return any_progress

    def _fanout_local(self, evt: AgentEvent) -> None:
        dropped_subscribers: list[int] = []
        for sid, q in list(self._subscribers.items()):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # Buffer varsa ve kapasitesi dolmadıysa event kaybolmadan sakla.
                buf = self._buffered_events.get(sid)
                if buf is not None and (buf.maxlen is None or len(buf) < buf.maxlen):
                    buf.append(evt)
                else:
                    # Buffer yoksa veya tam dolduysa subscriber düşürülür.
                    dropped_subscribers.append(sid)

        for sid in dropped_subscribers:
            self.unsubscribe(sid)

    async def _cleanup_redis(self) -> None:
        if self._redis_listener_task is not None and not self._redis_listener_task.done():
            cancel = getattr(self._redis_listener_task, "cancel", None)
            with contextlib.suppress(RuntimeError):
                if callable(cancel):
                    cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, Exception):
                await self._redis_listener_task
        self._redis_listener_task = None

        if self._redis_client is not None:
            with contextlib.suppress(Exception):
                closer = getattr(self._redis_client, "aclose", None) or self._redis_client.close
                await closer()
        self._redis_client = None
        self._redis_loop = None

    async def _ensure_redis_loop_compatibility(self) -> None:
        if self._redis_client is None and self._redis_listener_task is None:
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._redis_loop is current_loop:
            return
        self._redis_available = None
        await self._cleanup_redis()

    async def _write_dead_letter(self, *, reason: str, payload: dict[str, object], error: Exception | None = None) -> None:
        item = {
            "ts": time.time(),
            "reason": reason,
            "payload": payload,
        }
        if error is not None:
            item["error"] = str(error)
        self._dlq_buffer.append(item)

        if self._redis_client is None or self._redis_available is not True:
            return

        try:
            await self._redis_client.xadd(
                self._dlq_channel,
                {"payload": json.dumps(item, ensure_ascii=False)},
                maxlen=self._dlq_buffer.maxlen,
                approximate=True,
            )
        except Exception as exc:
            logger.debug("AgentEventBus DLQ yazımı başarısız: %s", exc)


_BUS = AgentEventBus()


def get_agent_event_bus() -> AgentEventBus:
    return _BUS
