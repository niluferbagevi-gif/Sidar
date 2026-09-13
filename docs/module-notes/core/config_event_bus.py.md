# `core/config_event_bus.py` — Event Bus / DLQ / Kafka-RabbitMQ Ayarları

- **Kaynak dosya:** `core/config_event_bus.py`
- **Not dosyası:** `docs/module-notes/core/config_event_bus.py.md`

**Amaç:** Agent event bus'ının transport (`redis`/`kafka`/`rabbitmq`), dead-
letter-queue kalıcılığı ve circuit-breaker eşiklerini `EventBusSettings` frozen
dataclass'ı olarak yükler.

**Özellikler:**
- `EventBusSettings` — backend/channel/group, DLQ channel+maxlen+persist path/
  batch/flush, RabbitMQ URL, Kafka topic/group/bootstrap servers, circuit-
  breaker `failure_threshold`/`open_seconds`.
- `load_event_bus_settings()` — `core/config_env_helpers.py`'deki prefixed
  helper'larla (`SIDAR_*` öncelikli, legacy fallback'li) değerleri okur; DLQ
  channel adı verilmemişse `f"{channel}:dlq"` türetir.
