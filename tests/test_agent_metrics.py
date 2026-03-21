from core.agent_metrics import AgentMetricsCollector, _DelegationHistogram


def test_delegation_histogram_snapshot_returns_copy_with_totals():
    hist = _DelegationHistogram()

    hist.observe(0.2)
    snap = hist.snapshot()

    assert snap["count"] == 1
    assert snap["sum"] == 0.2
    assert snap["counts"][0] == 0
    assert snap["counts"][1] == 1

    snap["counts"][1] = 999
    assert hist.snapshot()["counts"][1] == 1


def test_agent_metrics_render_prometheus_emits_histogram_and_counter_series():
    collector = AgentMetricsCollector()

    collector.record("reviewer", "code_review", "success", 0.2)
    collector.record("reviewer", "code_review", "success", 3.0)

    rendered = collector.render_prometheus()

    assert "# TYPE sidar_agent_delegation_duration_seconds histogram" in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="code_review",'
        'status="success",le="0.1"} 0'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="code_review",'
        'status="success",le="0.25"} 1'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="code_review",'
        'status="success",le="2.5"} 1'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="code_review",'
        'status="success",le="5.0"} 2'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_bucket{receiver="reviewer",intent="code_review",'
        'status="success",le="+Inf"} 2'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_sum{receiver="reviewer",intent="code_review",'
        'status="success"} 3.200000'
    ) in rendered
    assert (
        'sidar_agent_delegation_duration_seconds_count{receiver="reviewer",intent="code_review",'
        'status="success"} 2'
    ) in rendered
    assert (
        'sidar_agent_delegation_total{receiver="reviewer",intent="code_review",status="success"} 2'
    ) in rendered


def test_agent_metrics_render_prometheus_emits_step_histogram_and_counter_series():
    collector = AgentMetricsCollector()

    collector.record_step("sidar_agent", "llm_decision", "text-model", "success", 0.15)
    collector.record_step("sidar_agent", "tool_execution", "list_dir", "failed", 1.5)

    rendered = collector.render_prometheus()

    assert "# TYPE sidar_agent_step_duration_seconds histogram" in rendered
    assert (
        'sidar_agent_step_duration_seconds_bucket{agent="sidar_agent",step="llm_decision",'
        'target="text-model",status="success",le="0.25"} 1'
    ) in rendered
    assert (
        'sidar_agent_step_duration_seconds_bucket{agent="sidar_agent",step="tool_execution",'
        'target="list_dir",status="failed",le="2.5"} 1'
    ) in rendered
    assert (
        'sidar_agent_step_total{agent="sidar_agent",step="tool_execution",target="list_dir",status="failed"} 1'
    ) in rendered