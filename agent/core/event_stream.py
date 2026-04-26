"""Ajan durum event stream'i: Redis Streams + process-içi fallback."""

from __future__ import annotations

import asyncio
import abc
import contextlib
import importlib
import inspect
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


class BaseEventBusBackend(abc.ABC):
    """Backend strategy interface for remote transport operations."""

    def __init__(self, bus: "AgentEventBus") -> None:
        self.bus = bus

    @abc.abstractmethod
    def schedule_bootstrap(self) -> None:
        """Schedule backend listener bootstrap if needed."""

    @abc.abstractmethod
    async def publish(self, evt: AgentEvent) -> bool:
        """Publish an event via backend transport."""


class RedisBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_redis_bootstrap()

    async def publish(self, evt: AgentEvent) -> bool:
        return await self.bus._publish_via_redis(evt)


class RabbitMQBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_rabbit_bootstrap()

    async def publish(self, evt: AgentEvent) -> bool:
        return await self.bus._publish_via_rabbit(evt)


class KafkaBackend(BaseEventBusBackend):
    def schedule_bootstrap(self) -> None:
        self.bus._schedule_kafka_bootstrap()

    async def publish(self, evt: AgentEvent) -> bool:
        return await self.bus._publish_via_kafka(evt)


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[int, asyncio.Queue[AgentEvent]] = {}
        self._buffered_events: Dict[int, deque[AgentEvent]] = {}
        self._instance_id = uuid.uuid4().hex
        self._backend = str(os.getenv("SIDAR_EVENT_BUS_BACKEND", "redis") or "redis").strip().lower()
        self._channel = os.getenv("SIDAR_EVENT_BUS_CHANNEL", "sidar:agent_events")
        self._consumer_group = os.getenv("SIDAR_EVENT_BUS_GROUP", "sidar:agent_events:cg")
        self._dlq_channel = os.getenv("SIDAR_EVENT_BUS_DLQ_CHANNEL", f"{self._channel}:dlq")
        self._dlq_buffer: deque[dict[str, object]] = deque(maxlen=max(10, int(os.getenv("SIDAR_EVENT_BUS_DLQ_MAXLEN", "1000") or "1000")))
        self._dlq_persist_path = str(os.getenv("SIDAR_EVENT_BUS_DLQ_PERSIST_PATH", "") or "").strip()
        self._dlq_persist_batch_size = max(1, int(os.getenv("SIDAR_EVENT_BUS_DLQ_PERSIST_BATCH_SIZE", "100") or "100"))
        self._dlq_persist_flush_interval = max(0.05, float(os.getenv("SIDAR_EVENT_BUS_DLQ_PERSIST_FLUSH_INTERVAL", "1.0") or "1.0"))
        self._dlq_persist_pending: list[dict[str, object]] = []
        self._dlq_persist_lock: asyncio.Lock | None = None
        self._dlq_persist_flush_task: asyncio.Task | None = None

        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_max_connections = max(1, int(os.getenv("REDIS_MAX_CONNECTIONS", "50") or "50"))
        self._redis_connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "0.5") or "0.5")
        self._redis_socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "0.5") or "0.5")
        self._redis_client: Redis | None = None
        self._redis_listener_task: asyncio.Task | None = None
        self._redis_bootstrap_task: asyncio.Task | None = None
        self._redis_available: bool | None = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None
        self._rabbit_bootstrap_task: asyncio.Task | None = None
        self._rabbit_listener_task: asyncio.Task | None = None
        self._rabbit_available: bool | None = None
        self._rabbit_connection = None
        self._rabbit_channel = None
        self._rabbit_queue = None
        self._rabbit_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
        self._kafka_bootstrap_task: asyncio.Task | None = None
        self._kafka_listener_task: asyncio.Task | None = None
        self._kafka_available: bool | None = None
        self._kafka_producer = None
        self._kafka_consumer = None
        self._kafka_topic = os.getenv("SIDAR_EVENT_BUS_KAFKA_TOPIC", "sidar.agent_events")
        self._kafka_group = os.getenv("SIDAR_EVENT_BUS_KAFKA_GROUP", f"sidar-agent-events-{self._instance_id[:8]}")
        self._kafka_bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self._remote_circuit_failure_threshold = max(1, int(os.getenv("SIDAR_EVENT_BUS_CB_FAILURE_THRESHOLD", "5") or "5"))
        self._remote_circuit_open_seconds = max(1.0, float(os.getenv("SIDAR_EVENT_BUS_CB_OPEN_SECONDS", "15") or "15"))
        self._remote_circuit_consecutive_failures = 0
        self._remote_circuit_open_until = 0.0
        self._backends: dict[str, BaseEventBusBackend] = {
            "redis": RedisBackend(self),
            "rabbitmq": RabbitMQBackend(self),
            "kafka": KafkaBackend(self),
        }

    def subscribe(self, maxsize: int = 200) -> tuple[int, asyncio.Queue[AgentEvent]]:
        sub_id = int(time.time() * 1000) ^ id(object())
        self._subscribers[sub_id] = asyncio.Queue(maxsize=max(10, maxsize))
        self._schedule_remote_bootstrap()
        return sub_id, self._subscribers[sub_id]

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)
        self._buffered_events.pop(sub_id, None)

    async def publish(self, source: str, message: str) -> None:
        evt = AgentEvent(ts=time.time(), source=source, message=message)
        self._fanout_local(evt)
        if not self._is_remote_circuit_open():
            self._schedule_remote_bootstrap()
        await self._publish_via_remote(evt)

    def _schedule_remote_bootstrap(self) -> None:
        backend = self._backends.get(self._backend, self._backends["redis"])
        backend.schedule_bootstrap()

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

    def _schedule_rabbit_bootstrap(self) -> None:
        if self._rabbit_available is False:
            return
        if self._rabbit_bootstrap_task is not None and not self._rabbit_bootstrap_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._rabbit_bootstrap_task = loop.create_task(self._ensure_rabbit_listener())

    def _schedule_kafka_bootstrap(self) -> None:
        if self._kafka_available is False:
            return
        if self._kafka_bootstrap_task is not None and not self._kafka_bootstrap_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._kafka_bootstrap_task = loop.create_task(self._ensure_kafka_listener())

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

    async def _ensure_rabbit_listener(self) -> None:
        if self._rabbit_available is False:
            return
        if self._rabbit_listener_task is not None and not self._rabbit_listener_task.done():
            return
        try:
            aio_pika = importlib.import_module("aio_pika")
            if self._rabbit_connection is None:
                self._rabbit_connection = await aio_pika.connect_robust(self._rabbit_url)
                self._rabbit_channel = await self._rabbit_connection.channel()
                self._rabbit_queue = await self._rabbit_channel.declare_queue(self._channel, durable=True)
            self._rabbit_available = True
            self._rabbit_listener_task = asyncio.create_task(self._rabbit_listener_loop())
        except Exception as exc:
            self._rabbit_available = False
            logger.debug("AgentEventBus RabbitMQ bootstrap başarısız, local fallback kullanılacak: %s", exc)
            await self._cleanup_rabbit()

    async def _ensure_kafka_listener(self) -> None:
        if self._kafka_available is False:
            return
        if self._kafka_listener_task is not None and not self._kafka_listener_task.done():
            return
        try:
            aiokafka = importlib.import_module("aiokafka")
            if self._kafka_producer is None:
                self._kafka_producer = aiokafka.AIOKafkaProducer(bootstrap_servers=self._kafka_bootstrap_servers)
                await self._kafka_producer.start()
            if self._kafka_consumer is None:
                self._kafka_consumer = aiokafka.AIOKafkaConsumer(
                    self._kafka_topic,
                    bootstrap_servers=self._kafka_bootstrap_servers,
                    group_id=self._kafka_group,
                    enable_auto_commit=True,
                    auto_offset_reset="latest",
                )
                await self._kafka_consumer.start()
            self._kafka_available = True
            self._kafka_listener_task = asyncio.create_task(self._kafka_listener_loop())
        except Exception as exc:
            self._kafka_available = False
            logger.debug("AgentEventBus Kafka bootstrap başarısız, local fallback kullanılacak: %s", exc)
            await self._cleanup_kafka()

    async def _publish_via_remote(self, evt: AgentEvent) -> bool:
        if self._is_remote_circuit_open():
            return False
        backend = self._backends.get(self._backend, self._backends["redis"])
        ok = await backend.publish(evt)
        self._record_remote_publish_result(ok)
        return ok

    def _is_remote_circuit_backend(self) -> bool:
        return self._backend in {"redis", "kafka"}

    def _is_remote_circuit_open(self) -> bool:
        if not self._is_remote_circuit_backend():
            return False
        now = time.time()
        return self._remote_circuit_open_until > now

    def _record_remote_publish_result(self, ok: bool) -> None:
        if not self._is_remote_circuit_backend():
            return
        if ok:
            self._remote_circuit_consecutive_failures = 0
            self._remote_circuit_open_until = 0.0
            return
        self._remote_circuit_consecutive_failures += 1
        if self._remote_circuit_consecutive_failures >= self._remote_circuit_failure_threshold:
            self._remote_circuit_open_until = time.time() + self._remote_circuit_open_seconds
            logger.debug(
                "AgentEventBus remote circuit opened for backend=%s failures=%s open_for=%.1fs",
                self._backend,
                self._remote_circuit_consecutive_failures,
                self._remote_circuit_open_seconds,
            )

    def _serialize_event_payload(self, evt: AgentEvent) -> str:
        return json.dumps(
            {
                "sid": self._instance_id,
                "ts": evt.ts,
                "source": evt.source,
                "message": evt.message,
            },
            ensure_ascii=False,
        )

    def _deserialize_event_payload(self, payload_raw: object) -> AgentEvent | None:
        payload = json.loads(str(payload_raw))
        if payload.get("sid") == self._instance_id:
            return None
        return AgentEvent(
            ts=float(payload.get("ts", time.time())),
            source=str(payload.get("source", "agent")),
            message=str(payload.get("message", "")),
        )

    async def _publish_via_redis(self, evt: AgentEvent) -> bool:
        if self._redis_available is False:
            return False

        await self._ensure_redis_loop_compatibility()
        await self._ensure_redis_listener()
        if not self._redis_client or self._redis_available is not True:
            return False

        payload = self._serialize_event_payload(evt)
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

    async def _publish_via_rabbit(self, evt: AgentEvent) -> bool:
        if self._rabbit_available is False:
            return False
        await self._ensure_rabbit_listener()
        if self._rabbit_channel is None or self._rabbit_available is not True:
            return False
        payload = self._serialize_event_payload(evt)
        try:
            aio_pika = importlib.import_module("aio_pika")
            message = aio_pika.Message(body=payload.encode("utf-8"), content_type="application/json")
            await self._rabbit_channel.default_exchange.publish(message, routing_key=self._channel)
            return True
        except Exception as exc:
            logger.debug("AgentEventBus RabbitMQ publish başarısız, local fallback: %s", exc)
            await self._write_dead_letter(
                reason="publish_failed",
                payload={"event": {"ts": evt.ts, "source": evt.source, "message": evt.message}},
                error=exc,
            )
            self._rabbit_available = False
            await self._cleanup_rabbit()
            return False

    async def _publish_via_kafka(self, evt: AgentEvent) -> bool:
        if self._kafka_available is False:
            return False
        await self._ensure_kafka_listener()
        if self._kafka_producer is None or self._kafka_available is not True:
            return False
        payload = self._serialize_event_payload(evt)
        try:
            await self._kafka_producer.send_and_wait(self._kafka_topic, payload.encode("utf-8"))
            return True
        except Exception as exc:
            logger.debug("AgentEventBus Kafka publish başarısız, local fallback: %s", exc)
            await self._write_dead_letter(
                reason="publish_failed",
                payload={"event": {"ts": evt.ts, "source": evt.source, "message": evt.message}},
                error=exc,
            )
            self._kafka_available = False
            await self._cleanup_kafka()
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
                        evt = self._deserialize_event_payload(payload_raw)
                        if evt is not None:
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

    async def _rabbit_listener_loop(self) -> None:
        if self._rabbit_queue is None:
            return
        async with self._rabbit_queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                try:
                    evt = self._deserialize_event_payload(incoming.body.decode("utf-8"))
                    if evt is not None:
                        self._fanout_local(evt)
                except Exception as exc:
                    await self._write_dead_letter(
                        reason="invalid_payload",
                        payload={"payload": str(getattr(incoming, "body", b""))},
                        error=exc,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await incoming.ack()

    async def _kafka_listener_loop(self) -> None:
        if self._kafka_consumer is None:
            return
        while True:
            try:
                message = await self._kafka_consumer.getone()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("AgentEventBus Kafka listener hatası: %s", exc)
                self._kafka_available = False
                await self._cleanup_kafka()
                return

            try:
                evt = self._deserialize_event_payload(message.value.decode("utf-8"))
                if evt is not None:
                    self._fanout_local(evt)
            except Exception as exc:
                await self._write_dead_letter(
                    reason="invalid_payload",
                    payload={"payload": str(getattr(message, "value", b""))},
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
                close_async = getattr(self._redis_client, "aclose", None)
                if callable(close_async):
                    await close_async()
                else:
                    close_sync = getattr(self._redis_client, "close", None)
                    if callable(close_sync):
                        maybe_awaitable = close_sync()
                        if inspect.isawaitable(maybe_awaitable):
                            await maybe_awaitable

            with contextlib.suppress(Exception):
                connection_pool = getattr(self._redis_client, "connection_pool", None)
                disconnect = getattr(connection_pool, "disconnect", None)
                if callable(disconnect):
                    maybe_awaitable = disconnect()
                    if inspect.isawaitable(maybe_awaitable):
                        await maybe_awaitable
        self._redis_client = None
        self._redis_loop = None

    async def _cleanup_rabbit(self) -> None:
        if self._rabbit_listener_task is not None and not self._rabbit_listener_task.done():
            self._rabbit_listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, Exception):
                await self._rabbit_listener_task
        self._rabbit_listener_task = None

        if self._rabbit_channel is not None:
            with contextlib.suppress(Exception):
                close_async = getattr(self._rabbit_channel, "close", None)
                if callable(close_async):
                    maybe_awaitable = close_async()
                    if inspect.isawaitable(maybe_awaitable):
                        await maybe_awaitable
        self._rabbit_channel = None
        self._rabbit_queue = None

        if self._rabbit_connection is not None:
            with contextlib.suppress(Exception):
                await self._rabbit_connection.close()
        self._rabbit_connection = None

    async def _cleanup_kafka(self) -> None:
        if self._kafka_listener_task is not None and not self._kafka_listener_task.done():
            self._kafka_listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, Exception):
                await self._kafka_listener_task
        self._kafka_listener_task = None

        if self._kafka_consumer is not None:
            with contextlib.suppress(Exception):
                await self._kafka_consumer.stop()
        self._kafka_consumer = None

        if self._kafka_producer is not None:
            with contextlib.suppress(Exception):
                await self._kafka_producer.stop()
        self._kafka_producer = None

    async def _ensure_redis_loop_compatibility(self) -> None:
        if self._backend != "redis":
            return
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

        if len(self._dlq_buffer) == self._dlq_buffer.maxlen and self._dlq_buffer:
            oldest_item = dict(self._dlq_buffer[0])
            await self._persist_dead_letter_item(oldest_item, dropped_from_memory=True)
        self._dlq_buffer.append(item)
        await self._persist_dead_letter_item(item)

        if self._backend == "redis" and self._redis_client is not None and self._redis_available is True:
            try:
                await self._redis_client.xadd(
                    self._dlq_channel,
                    {"payload": json.dumps(item, ensure_ascii=False)},
                    maxlen=self._dlq_buffer.maxlen,
                    approximate=True,
                )
            except Exception as exc:
                logger.debug("AgentEventBus DLQ yazımı başarısız: %s", exc)

    async def _persist_dead_letter_item(self, item: dict[str, object], *, dropped_from_memory: bool = False) -> None:
        if not self._dlq_persist_path:
            return
        record = {
            "ts": time.time(),
            "dropped_from_memory": dropped_from_memory,
            "item": item,
        }
        self._dlq_persist_pending.append(record)
        if len(self._dlq_persist_pending) >= self._dlq_persist_batch_size:
            await self._flush_dead_letter_persist_queue()
            return
        self._schedule_dead_letter_flush()

    def _schedule_dead_letter_flush(self) -> None:
        if self._dlq_persist_flush_task is not None and not self._dlq_persist_flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._dlq_persist_flush_task = loop.create_task(self._delayed_dead_letter_flush())

    async def _delayed_dead_letter_flush(self) -> None:
        await asyncio.sleep(self._dlq_persist_flush_interval)
        await self._flush_dead_letter_persist_queue()

    async def _flush_dead_letter_persist_queue(self) -> None:
        if not self._dlq_persist_path or not self._dlq_persist_pending:
            return
        if self._dlq_persist_lock is None:
            self._dlq_persist_lock = asyncio.Lock()

        async with self._dlq_persist_lock:
            if not self._dlq_persist_pending:
                return
            records = list(self._dlq_persist_pending)
            self._dlq_persist_pending.clear()
            await asyncio.to_thread(self._persist_dead_letter_items_sync, records)

    def _persist_dead_letter_item_sync(self, item: dict[str, object], *, dropped_from_memory: bool = False) -> None:
        record = {
            "ts": time.time(),
            "dropped_from_memory": dropped_from_memory,
            "item": item,
        }
        self._persist_dead_letter_items_sync([record])

    def _persist_dead_letter_items_sync(self, records: list[dict[str, object]]) -> None:
        if not self._dlq_persist_path:
            return
        try:
            parent = os.path.dirname(self._dlq_persist_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._dlq_persist_path, "a", encoding="utf-8") as fp:
                for record in records:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("AgentEventBus persistent DLQ yazımı başarısız: %s", exc)


_BUS = AgentEventBus()


def get_agent_event_bus() -> AgentEventBus:
    return _BUS
