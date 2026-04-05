"""Unit tests for Prometheus text rendering in system health manager."""

from __future__ import annotations

from managers.system_health import render_llm_metrics_prometheus


def test_render_llm_metrics_prometheus_includes_totals_cache_provider_and_user() -> None:
    snapshot = {
        "totals": {"calls": 10, "cost_usd": 1.23, "total_tokens": 456, "failures": 2},
        "cache": {"hits": 7, "misses": 3, "skips": 1, "evictions": 2, "redis_errors": 0, "hit_rate": 0.7, "items": 5, "redis_latency_ms": 12.5},
        "by_provider": {"openai": {"calls": 6, "cost_usd": 0.9, "total_tokens": 300, "failures": 1, "latency_ms_avg": 250.0}},
        "by_user": {"user-1": {"calls": 4, "cost_usd": 0.33, "total_tokens": 120}},
    }

    output = render_llm_metrics_prometheus(snapshot)

    assert "sidar_llm_calls_total 10" in output
    assert "sidar_semantic_cache_hits_total 7" in output
    assert 'sidar_llm_calls_total{provider="openai"} 6' in output
    assert 'sidar_llm_user_calls_total{user_id="user-1"} 4' in output
