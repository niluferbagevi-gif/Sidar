from __future__ import annotations

import core.agent_metrics as mod


def setup_function() -> None:
    mod._COLLECTOR = None


def test_delegation_histogram_snapshot_and_bucket_progression() -> None:
    hist = mod._DelegationHistogram()

    hist.observe(0.2)
    hist.observe(1000.0)

    snap = hist.snapshot()
    assert snap["count"] == 2
    assert snap["sum"] == 1000.2

    # 0.2s yalnızca >=0.25 bucket'larına; 1000s yalnızca +Inf bucket'ına yansır.
    assert snap["counts"][0] == 0
    assert snap["counts"][1] == 1
    assert snap["counts"][-1] == 2


def test_record_and_record_step_create_and_increment_metrics() -> None:
    collector = mod.AgentMetricsCollector()

    collector.record("reviewer", "audit", "ok", 0.5)
    collector.record("reviewer", "audit", "ok", 1.5)
    collector.record_step("coder", "tool_call", "pytest", "ok", 2.0)
    collector.record_step("coder", "tool_call", "pytest", "ok", 3.0)

    assert collector._counters[("reviewer", "audit", "ok")] == 2
    assert collector._step_counters[("coder", "tool_call", "pytest", "ok")] == 2

    delegation_snap = collector._histograms[("reviewer", "audit", "ok")].snapshot()
    step_snap = collector._step_histograms[("coder", "tool_call", "pytest", "ok")].snapshot()

    assert delegation_snap["count"] == 2
    assert delegation_snap["sum"] == 2.0
    assert step_snap["count"] == 2
    assert step_snap["sum"] == 5.0


def test_render_prometheus_contains_all_metric_sections() -> None:
    collector = mod.AgentMetricsCollector()
    collector.record("qa", "validation", "ok", 0.25)
    collector.record_step("qa", "judge", "policy", "ok", 0.4)

    text = collector.render_prometheus()

    assert "# HELP sidar_agent_delegation_duration_seconds" in text
    assert "# TYPE sidar_agent_delegation_duration_seconds histogram" in text
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="qa",intent="validation",status="ok",le="0.25"} 1'
        in text
    )
    assert (
        'sidar_agent_delegation_duration_seconds_sum{receiver="qa",intent="validation",status="ok"} 0.250000'
        in text
    )
    assert 'sidar_agent_delegation_total{receiver="qa",intent="validation",status="ok"} 1' in text

    assert "# HELP sidar_agent_step_duration_seconds" in text
    assert "# TYPE sidar_agent_step_duration_seconds histogram" in text
    assert (
        'sidar_agent_step_duration_seconds_bucket{agent="qa",step="judge",target="policy",status="ok",le="0.5"} 1'
        in text
    )
    assert 'sidar_agent_step_total{agent="qa",step="judge",target="policy",status="ok"} 1' in text
    assert text.endswith("\n")


def test_render_prometheus_empty_collector_has_help_and_type_lines() -> None:
    collector = mod.AgentMetricsCollector()

    text = collector.render_prometheus()

    assert "# HELP sidar_agent_delegation_total" in text
    assert "# TYPE sidar_agent_delegation_total counter" in text
    assert "# HELP sidar_agent_step_total" in text
    assert "# TYPE sidar_agent_step_total counter" in text
    assert "sidar_agent_delegation_total{" not in text
    assert "sidar_agent_step_total{" not in text


def test_get_agent_metrics_collector_singleton_reuses_existing_instance() -> None:
    first = mod.get_agent_metrics_collector()
    second = mod.get_agent_metrics_collector()

    assert first is second
