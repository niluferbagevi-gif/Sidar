from __future__ import annotations

import math
import threading

from core import agent_metrics
from core.agent_metrics import AgentMetricsCollector, _DelegationHistogram


def test_delegation_histogram_observe_accumulates_cumulative_buckets() -> None:
    hist = _DelegationHistogram()

    hist.observe(0.2)
    hist.observe(3.0)

    snap = hist.snapshot()

    assert snap["count"] == 2
    assert snap["sum"] == 3.2

    expected_counts = []
    for bound in agent_metrics._BUCKETS:
        expected_counts.append(sum(1 for value in (0.2, 3.0) if value <= bound))
    assert snap["counts"] == expected_counts


def test_delegation_histogram_snapshot_returns_copy() -> None:
    hist = _DelegationHistogram()
    hist.observe(0.1)

    snap = hist.snapshot()
    snap["counts"][0] = 999

    fresh = hist.snapshot()
    assert fresh["counts"][0] == 1


def test_agent_metrics_collector_record_and_step_increment_counters() -> None:
    collector = AgentMetricsCollector()

    collector.record("qa", "repair", "ok", 0.4)
    collector.record("qa", "repair", "ok", 0.6)
    collector.record_step("coder", "tool", "pytest", "ok", 1.5)
    collector.record_step("coder", "tool", "pytest", "ok", 0.5)

    assert collector._counters[("qa", "repair", "ok")] == 2
    assert collector._step_counters[("coder", "tool", "pytest", "ok")] == 2

    delegation_snap = collector._histograms[("qa", "repair", "ok")].snapshot()
    assert delegation_snap["count"] == 2
    assert delegation_snap["sum"] == 1.0

    step_snap = collector._step_histograms[("coder", "tool", "pytest", "ok")].snapshot()
    assert step_snap["count"] == 2
    assert step_snap["sum"] == 2.0


def test_render_prometheus_includes_headers_even_without_metrics() -> None:
    collector = AgentMetricsCollector()

    text = collector.render_prometheus()

    assert "# HELP sidar_agent_delegation_duration_seconds" in text
    assert "# TYPE sidar_agent_delegation_duration_seconds histogram" in text
    assert "# HELP sidar_agent_delegation_total" in text
    assert "# TYPE sidar_agent_delegation_total counter" in text
    assert "# HELP sidar_agent_step_duration_seconds" in text
    assert "# TYPE sidar_agent_step_duration_seconds histogram" in text
    assert "# HELP sidar_agent_step_total" in text
    assert "# TYPE sidar_agent_step_total counter" in text
    assert text.endswith("\n")


def test_render_prometheus_renders_delegation_and_step_metrics() -> None:
    collector = AgentMetricsCollector()
    collector.record("reviewer", "audit", "ok", 0.1)
    collector.record("reviewer", "audit", "ok", 7.0)
    collector.record_step("coder", "delegate", "qa", "error", math.inf)

    text = collector.render_prometheus()

    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="audit",status="ok",le="0.1"} 1'
        in text
    )
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="audit",status="ok",le="10.0"} 2'
        in text
    )
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="audit",status="ok",le="+Inf"} 2'
        in text
    )
    assert (
        'sidar_agent_delegation_duration_seconds_sum{receiver="reviewer",intent="audit",status="ok"} 7.100000'
        in text
    )
    assert (
        'sidar_agent_delegation_duration_seconds_count{receiver="reviewer",intent="audit",status="ok"} 2'
        in text
    )
    assert 'sidar_agent_delegation_total{receiver="reviewer",intent="audit",status="ok"} 2' in text

    assert (
        'sidar_agent_step_duration_seconds_bucket{agent="coder",step="delegate",target="qa",status="error",le="+Inf"} 1'
        in text
    )
    assert (
        'sidar_agent_step_duration_seconds_sum{agent="coder",step="delegate",target="qa",status="error"} inf'
        in text
    )
    assert (
        'sidar_agent_step_duration_seconds_count{agent="coder",step="delegate",target="qa",status="error"} 1'
        in text
    )
    assert (
        'sidar_agent_step_total{agent="coder",step="delegate",target="qa",status="error"} 1' in text
    )


def test_get_agent_metrics_collector_returns_singleton_instance() -> None:
    agent_metrics._COLLECTOR = None

    first = agent_metrics.get_agent_metrics_collector()
    second = agent_metrics.get_agent_metrics_collector()

    assert first is second


def test_get_agent_metrics_collector_thread_safe_singleton_creation() -> None:
    agent_metrics._COLLECTOR = None
    created = []

    def _worker() -> None:
        created.append(agent_metrics.get_agent_metrics_collector())

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == 8
    first = created[0]
    assert all(item is first for item in created)


def test_get_agent_metrics_collector_double_checked_lock_inner_branch() -> None:
    sentinel = AgentMetricsCollector()
    agent_metrics._COLLECTOR = None

    class EnterSetsCollector:
        def __enter__(self):
            agent_metrics._COLLECTOR = sentinel
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    original_lock = agent_metrics._COLLECTOR_LOCK
    try:
        agent_metrics._COLLECTOR_LOCK = EnterSetsCollector()
        assert agent_metrics.get_agent_metrics_collector() is sentinel
    finally:
        agent_metrics._COLLECTOR_LOCK = original_lock
