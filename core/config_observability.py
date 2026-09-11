"""Observability configuration defaults for the Sidar settings facade."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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


# Sentinel distinguishing "caller didn't pass this dependency, auto-import the
# real one" from an explicit ``None`` ("this dependency is unavailable, fail
# closed"). Shared identity with ``config.py``'s ``Config.init_telemetry``
# default parameter values and its re-exported ``config._DEPENDENCY_AUTO`` --
# see that module's import of this name.
DEPENDENCY_AUTO = object()


def init_telemetry(
    *,
    enable_tracing: bool,
    otel_service_name: str,
    otel_exporter_endpoint: str,
    otel_instrument_fastapi: bool,
    otel_instrument_httpx: bool,
    logger_obj: logging.Logger,
    localized_log_message: Callable[[str], str],
    service_name: str | None = None,
    fastapi_app: Any | None = None,
    trace_module: Any = DEPENDENCY_AUTO,
    otlp_exporter_cls: Any = DEPENDENCY_AUTO,
    tracer_provider_cls: Any = DEPENDENCY_AUTO,
    resource_cls: Any = DEPENDENCY_AUTO,
    batch_span_processor_cls: Any = DEPENDENCY_AUTO,
    fastapi_instrumentor_cls: Any = DEPENDENCY_AUTO,
    httpx_instrumentor_cls: Any = DEPENDENCY_AUTO,
) -> bool:
    """Initialize OpenTelemetry tracing plus optional FastAPI/HTTPX instrumentation.

    Extracted from ``config.Config.init_telemetry`` (previously ~95 lines of the
    Config class body) as part of consolidating config.py's remaining large
    logic blocks into the established ``core/config_*.py`` domain-module
    pattern -- see docs/module-notes/config.py.md. ``Config.init_telemetry``
    stays the public entrypoint and forwards its live ``cls.ENABLE_TRACING``
    etc. class attributes (which existing tests monkeypatch directly on
    ``Config``) into the settings-shaped keyword arguments here; this function
    itself takes no dependency on ``config.Config``.
    """
    log = logger_obj
    if not enable_tracing:
        return False

    if (
        trace_module is None
        or otlp_exporter_cls is None
        or tracer_provider_cls is None
        or resource_cls is None
        or batch_span_processor_cls is None
    ):
        log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
        return False

    try:
        if trace_module is DEPENDENCY_AUTO:
            from opentelemetry import trace as imported_trace_module

            trace_module = imported_trace_module
        if otlp_exporter_cls is DEPENDENCY_AUTO:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as imported_otlp_exporter_cls,
            )

            otlp_exporter_cls = imported_otlp_exporter_cls
        if tracer_provider_cls is DEPENDENCY_AUTO:
            from opentelemetry.sdk.trace import TracerProvider as imported_tracer_provider_cls

            tracer_provider_cls = imported_tracer_provider_cls
        if resource_cls is DEPENDENCY_AUTO:
            from opentelemetry.sdk.resources import Resource as imported_resource_cls

            resource_cls = imported_resource_cls
        if batch_span_processor_cls is DEPENDENCY_AUTO:
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor as imported_batch_span_processor_cls,
            )

            batch_span_processor_cls = imported_batch_span_processor_cls
    except Exception:
        log.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
        return False

    try:
        svc_name = service_name or otel_service_name or "sidar"
        resource = resource_cls.create({"service.name": svc_name})
        provider = tracer_provider_cls(resource=resource)
        exporter = otlp_exporter_cls(endpoint=otel_exporter_endpoint, insecure=True)
        provider.add_span_processor(batch_span_processor_cls(exporter))
        trace_module.set_tracer_provider(provider)

        if fastapi_app is not None and otel_instrument_fastapi:
            if fastapi_instrumentor_cls is DEPENDENCY_AUTO:
                from opentelemetry.instrumentation.fastapi import (
                    FastAPIInstrumentor as imported_fastapi_instrumentor_cls,
                )

                fastapi_instrumentor_cls = imported_fastapi_instrumentor_cls
            fastapi_instrumentor_cls.instrument_app(fastapi_app)

        if otel_instrument_httpx:
            if httpx_instrumentor_cls is DEPENDENCY_AUTO:
                try:
                    from opentelemetry.instrumentation.httpx import (
                        HTTPXClientInstrumentor as imported_httpx_instrumentor_cls,
                    )

                    httpx_instrumentor_cls = imported_httpx_instrumentor_cls
                except Exception:
                    httpx_instrumentor_cls = None
            if httpx_instrumentor_cls is not None:
                with contextlib.suppress(Exception):
                    httpx_instrumentor_cls().instrument()

        log.info(localized_log_message("otel_active"), otel_exporter_endpoint)
        return True
    except Exception as exc:
        log.warning(localized_log_message("otel_failed"), exc)
        return False
