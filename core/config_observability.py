"""Observability configuration defaults for the Sidar settings facade."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env


@dataclass(frozen=True)
class ObservabilitySettings:
    """Tracing, metrics and dashboard settings consumed by ``config.Config``."""

    metrics_token: str
    enable_tracing: bool
    otel_exporter_endpoint: str
    otel_service_name: str
    otel_instrument_fastapi: bool
    otel_instrument_httpx: bool
    grafana_url: str
    dlp_log_detections: bool


def load_observability_settings() -> ObservabilitySettings:
    """Load observability-related settings from environment variables."""
    return ObservabilitySettings(
        metrics_token=os.getenv("METRICS_TOKEN", ""),
        enable_tracing=get_bool_env("ENABLE_TRACING", False),
        otel_exporter_endpoint=os.getenv("OTEL_EXPORTER_ENDPOINT", "http://jaeger:4317"),
        otel_service_name=os.getenv("OTEL_SERVICE_NAME", "sidar"),
        otel_instrument_fastapi=get_bool_env("OTEL_INSTRUMENT_FASTAPI", True),
        otel_instrument_httpx=get_bool_env("OTEL_INSTRUMENT_HTTPX", True),
        grafana_url=os.getenv("GRAFANA_URL", "http://localhost:3000"),
        dlp_log_detections=get_bool_env("DLP_LOG_DETECTIONS", False),
    )
