import pytest

from core.llm_metrics import LLMMetricsCollector
from managers.system_health import render_llm_metrics_prometheus


@pytest.mark.integration
def test_llm_metrics_snapshot_is_exported_to_prometheus_text() -> None:
    collector = LLMMetricsCollector(max_events=10)
    collector.record(
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=120,
        prompt_tokens=10,
        completion_tokens=20,
        success=True,
        user_id="u-1",
    )
    collector.record(
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=240,
        prompt_tokens=5,
        completion_tokens=5,
        success=False,
        error="429 rate limit",
        user_id="u-1",
    )

    metrics_text = render_llm_metrics_prometheus(collector.snapshot())

    assert "sidar_llm_calls_total 2" in metrics_text
    assert 'sidar_llm_calls_total{provider="openai"} 2' in metrics_text
    assert 'sidar_llm_user_calls_total{user_id="u-1"} 2' in metrics_text
    assert "sidar_llm_failures_total 1" in metrics_text
