"""Event bus, DLQ, RabbitMQ and Kafka settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_float_env, get_int_env, get_prefixed_env


@dataclass(frozen=True)
class EventBusSettings:
    """Agent event bus transport and durability settings."""

    sidar_event_bus_backend: str
    sidar_event_bus_channel: str
    sidar_event_bus_group: str
    sidar_event_bus_dlq_channel: str
    sidar_event_bus_dlq_maxlen: int
    sidar_event_bus_dlq_persist_path: str
    sidar_event_bus_dlq_persist_batch_size: int
    sidar_event_bus_dlq_persist_flush_interval: float
    sidar_rabbitmq_url: str
    sidar_event_bus_kafka_topic: str
    sidar_event_bus_kafka_group: str
    sidar_kafka_bootstrap_servers: str
    sidar_event_bus_cb_failure_threshold: int
    sidar_event_bus_cb_open_seconds: float


def load_event_bus_settings() -> EventBusSettings:
    """Load event bus settings from environment variables."""

    channel = os.getenv("SIDAR_EVENT_BUS_CHANNEL", "sidar:agent_events")
    return EventBusSettings(
        sidar_event_bus_backend=os.getenv("SIDAR_EVENT_BUS_BACKEND", "redis"),
        sidar_event_bus_channel=channel,
        sidar_event_bus_group=os.getenv("SIDAR_EVENT_BUS_GROUP", "sidar:agent_events:cg"),
        sidar_event_bus_dlq_channel=os.getenv("SIDAR_EVENT_BUS_DLQ_CHANNEL", f"{channel}:dlq"),
        sidar_event_bus_dlq_maxlen=get_int_env("SIDAR_EVENT_BUS_DLQ_MAXLEN", 1000),
        sidar_event_bus_dlq_persist_path=os.getenv("SIDAR_EVENT_BUS_DLQ_PERSIST_PATH", ""),
        sidar_event_bus_dlq_persist_batch_size=get_int_env(
            "SIDAR_EVENT_BUS_DLQ_PERSIST_BATCH_SIZE", 100
        ),
        sidar_event_bus_dlq_persist_flush_interval=get_float_env(
            "SIDAR_EVENT_BUS_DLQ_PERSIST_FLUSH_INTERVAL", 1.0
        ),
        sidar_rabbitmq_url=get_prefixed_env(
            "SIDAR_RABBITMQ_URL", "RABBITMQ_URL", "amqp://guest:guest@localhost/"
        ),
        sidar_event_bus_kafka_topic=os.getenv("SIDAR_EVENT_BUS_KAFKA_TOPIC", "sidar.agent_events"),
        sidar_event_bus_kafka_group=os.getenv("SIDAR_EVENT_BUS_KAFKA_GROUP", ""),
        sidar_kafka_bootstrap_servers=get_prefixed_env(
            "SIDAR_KAFKA_BOOTSTRAP_SERVERS",
            "KAFKA_BOOTSTRAP_SERVERS",
            "localhost:9092",
        ),
        sidar_event_bus_cb_failure_threshold=get_int_env("SIDAR_EVENT_BUS_CB_FAILURE_THRESHOLD", 5),
        sidar_event_bus_cb_open_seconds=get_float_env("SIDAR_EVENT_BUS_CB_OPEN_SECONDS", 15.0),
    )
