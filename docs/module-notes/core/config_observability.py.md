# `core/config_observability.py` — Tracing/Metrics/Dashboard Ayarları

- **Kaynak dosya:** `core/config_observability.py`
- **Not dosyası:** `docs/module-notes/core/config_observability.py.md`

**Amaç:** OpenTelemetry tracing, metrics token'ı, Grafana URL'i ve DLP tespit
loglaması gibi observability ayarlarını `ObservabilitySettings` frozen
dataclass'ı olarak yükler.

**Özellikler:**
- `ObservabilitySettings` — `metrics_token`, `enable_tracing`,
  `otel_exporter_endpoint`, `otel_service_name`, `otel_instrument_fastapi`,
  `otel_instrument_httpx`, `grafana_url`, `dlp_log_detections`.
- `load_observability_settings()` — `get_bool_env` ile bayrakları, `os.getenv`
  ile URL/token değerlerini okur.
