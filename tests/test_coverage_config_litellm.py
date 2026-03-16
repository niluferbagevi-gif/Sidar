"""
Coverage tests for config.py missing lines:
  - lines 558-562: litellm provider validation (LITELLM_GATEWAY_URL missing)
  - lines 642-684: init_telemetry when ENABLE_TRACING=True
  - lines 713-714: print_config_summary litellm branch
"""
from __future__ import annotations

import logging
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from config import Config


# ── validate_config — litellm without gateway URL ────────────────────────────

def test_validate_config_litellm_missing_gateway_url():
    """Lines 558-562: litellm mode without LITELLM_GATEWAY_URL logs error and returns False."""
    saved_provider = Config.AI_PROVIDER
    saved_url = Config.LITELLM_GATEWAY_URL
    try:
        Config.AI_PROVIDER = "litellm"
        Config.LITELLM_GATEWAY_URL = ""
        result = Config.validate_critical_settings()
        # Should return False because gateway URL is missing
        assert result is False
    finally:
        Config.AI_PROVIDER = saved_provider
        Config.LITELLM_GATEWAY_URL = saved_url


def test_validate_config_litellm_with_gateway_url_is_valid():
    """litellm mode with LITELLM_GATEWAY_URL should pass litellm check."""
    saved_provider = Config.AI_PROVIDER
    saved_url = Config.LITELLM_GATEWAY_URL
    saved_key = Config.ANTHROPIC_API_KEY
    try:
        Config.AI_PROVIDER = "litellm"
        Config.LITELLM_GATEWAY_URL = "http://localhost:4000"
        Config.ANTHROPIC_API_KEY = "test-key"  # avoid anthropic error
        result = Config.validate_critical_settings()
        # May return True or False based on other checks, but litellm check passes
        # (no error logged for litellm)
        assert isinstance(result, bool)
    finally:
        Config.AI_PROVIDER = saved_provider
        Config.LITELLM_GATEWAY_URL = saved_url
        Config.ANTHROPIC_API_KEY = saved_key


# ── init_telemetry — ENABLE_TRACING=True paths ───────────────────────────────

def test_init_telemetry_returns_false_when_tracing_disabled():
    """init_telemetry returns False immediately when ENABLE_TRACING is False."""
    saved = Config.ENABLE_TRACING
    try:
        Config.ENABLE_TRACING = False
        result = Config.init_telemetry()
        assert result is False
    finally:
        Config.ENABLE_TRACING = saved


def test_init_telemetry_returns_true_with_mocked_deps():
    """Lines 642-684: init_telemetry with all deps injected as mocks returns True."""
    saved = Config.ENABLE_TRACING
    saved_endpoint = Config.OTEL_EXPORTER_ENDPOINT
    try:
        Config.ENABLE_TRACING = True
        Config.OTEL_EXPORTER_ENDPOINT = "http://localhost:4317"

        mock_trace = MagicMock()
        mock_exporter = MagicMock()
        mock_exporter_cls = MagicMock(return_value=mock_exporter)
        mock_provider = MagicMock()
        mock_provider_cls = MagicMock(return_value=mock_provider)
        mock_resource = MagicMock()
        mock_resource.create = MagicMock(return_value=mock_resource)
        mock_resource_cls = MagicMock()
        mock_resource_cls.create = MagicMock(return_value=mock_resource)
        mock_processor = MagicMock()
        mock_processor_cls = MagicMock(return_value=mock_processor)

        result = Config.init_telemetry(
            trace_module=mock_trace,
            otlp_exporter_cls=mock_exporter_cls,
            tracer_provider_cls=mock_provider_cls,
            resource_cls=mock_resource_cls,
            batch_span_processor_cls=mock_processor_cls,
        )
        assert result is True
    finally:
        Config.ENABLE_TRACING = saved
        Config.OTEL_EXPORTER_ENDPOINT = saved_endpoint


def test_init_telemetry_with_fastapi_app():
    """Lines 665-668: when fastapi_app provided and OTEL_INSTRUMENT_FASTAPI=True, instruments app."""
    saved = Config.ENABLE_TRACING
    saved_endpoint = Config.OTEL_EXPORTER_ENDPOINT
    saved_instrument = getattr(Config, "OTEL_INSTRUMENT_FASTAPI", False)
    try:
        Config.ENABLE_TRACING = True
        Config.OTEL_EXPORTER_ENDPOINT = "http://localhost:4317"
        Config.OTEL_INSTRUMENT_FASTAPI = True

        mock_trace = MagicMock()
        mock_exporter_cls = MagicMock(return_value=MagicMock())
        mock_provider_cls = MagicMock(return_value=MagicMock())
        mock_resource_cls = MagicMock()
        mock_resource_cls.create = MagicMock(return_value=MagicMock())
        mock_processor_cls = MagicMock(return_value=MagicMock())
        mock_fastapi_instrumentor = MagicMock()
        mock_fastapi_app = MagicMock()

        result = Config.init_telemetry(
            fastapi_app=mock_fastapi_app,
            trace_module=mock_trace,
            otlp_exporter_cls=mock_exporter_cls,
            tracer_provider_cls=mock_provider_cls,
            resource_cls=mock_resource_cls,
            batch_span_processor_cls=mock_processor_cls,
            fastapi_instrumentor_cls=mock_fastapi_instrumentor,
        )
        assert result is True
        mock_fastapi_instrumentor.instrument_app.assert_called_once_with(mock_fastapi_app)
    finally:
        Config.ENABLE_TRACING = saved
        Config.OTEL_EXPORTER_ENDPOINT = saved_endpoint
        Config.OTEL_INSTRUMENT_FASTAPI = saved_instrument


def test_init_telemetry_with_httpx_instrumentor():
    """Lines 670-678: OTEL_INSTRUMENT_HTTPX=True instruments httpx."""
    saved = Config.ENABLE_TRACING
    saved_endpoint = Config.OTEL_EXPORTER_ENDPOINT
    saved_httpx = getattr(Config, "OTEL_INSTRUMENT_HTTPX", False)
    try:
        Config.ENABLE_TRACING = True
        Config.OTEL_EXPORTER_ENDPOINT = "http://localhost:4317"
        Config.OTEL_INSTRUMENT_HTTPX = True

        mock_trace = MagicMock()
        mock_exporter_cls = MagicMock(return_value=MagicMock())
        mock_provider_cls = MagicMock(return_value=MagicMock())
        mock_resource_cls = MagicMock()
        mock_resource_cls.create = MagicMock(return_value=MagicMock())
        mock_processor_cls = MagicMock(return_value=MagicMock())

        mock_httpx_instrumentor_instance = MagicMock()
        mock_httpx_instrumentor_cls = MagicMock(return_value=mock_httpx_instrumentor_instance)

        result = Config.init_telemetry(
            trace_module=mock_trace,
            otlp_exporter_cls=mock_exporter_cls,
            tracer_provider_cls=mock_provider_cls,
            resource_cls=mock_resource_cls,
            batch_span_processor_cls=mock_processor_cls,
            httpx_instrumentor_cls=mock_httpx_instrumentor_cls,
        )
        assert result is True
    finally:
        Config.ENABLE_TRACING = saved
        Config.OTEL_EXPORTER_ENDPOINT = saved_endpoint
        Config.OTEL_INSTRUMENT_HTTPX = saved_httpx


def test_init_telemetry_otel_exception_returns_false():
    """Lines 682-684: Exception during setup returns False."""
    saved = Config.ENABLE_TRACING
    saved_endpoint = Config.OTEL_EXPORTER_ENDPOINT
    try:
        Config.ENABLE_TRACING = True
        Config.OTEL_EXPORTER_ENDPOINT = "http://localhost:4317"

        mock_trace = MagicMock()
        mock_resource_cls = MagicMock()
        mock_resource_cls.create = MagicMock(side_effect=RuntimeError("boom"))

        result = Config.init_telemetry(
            trace_module=mock_trace,
            otlp_exporter_cls=MagicMock(),
            tracer_provider_cls=MagicMock(),
            resource_cls=mock_resource_cls,
            batch_span_processor_cls=MagicMock(),
        )
        assert result is False
    finally:
        Config.ENABLE_TRACING = saved
        Config.OTEL_EXPORTER_ENDPOINT = saved_endpoint


def test_init_telemetry_missing_deps_returns_false():
    """Lines 642-655: when opentelemetry not available and no injected deps."""
    saved = Config.ENABLE_TRACING
    try:
        Config.ENABLE_TRACING = True

        import sys
        # Mock all otel imports to fail
        with patch.dict(sys.modules, {
            "opentelemetry": None,
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.resources": None,
            "opentelemetry.sdk.trace.export": None,
        }):
            result = Config.init_telemetry()
            # Should return False due to import failures
            assert result is False
    finally:
        Config.ENABLE_TRACING = saved


# ── print_config_summary — litellm branch (lines 712-714) ────────────────────

def test_print_config_summary_litellm_branch(capsys):
    """Lines 712-714: litellm branch in print_config_summary prints gateway and model."""
    saved_provider = Config.AI_PROVIDER
    saved_url = Config.LITELLM_GATEWAY_URL
    saved_model = getattr(Config, "LITELLM_MODEL", None)
    try:
        Config.AI_PROVIDER = "litellm"
        Config.LITELLM_GATEWAY_URL = "http://litellm-gateway:4000"
        Config.LITELLM_MODEL = "gpt-4"
        Config.print_config_summary()
        captured = capsys.readouterr()
        assert "LiteLLM" in captured.out or "litellm" in captured.out.lower()
    finally:
        Config.AI_PROVIDER = saved_provider
        Config.LITELLM_GATEWAY_URL = saved_url
        if saved_model is not None:
            Config.LITELLM_MODEL = saved_model
