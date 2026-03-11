from core.llm_metrics import LLMMetricsCollector


def test_llm_metrics_collector_aggregates_calls_tokens_and_costs():
    c = LLMMetricsCollector(max_events=10)
    c.record(provider="openai", model="gpt-4o-mini", latency_ms=120, prompt_tokens=10, completion_tokens=5, success=True)
    c.record(provider="openai", model="gpt-4o-mini", latency_ms=80, prompt_tokens=8, completion_tokens=4, success=False, error="429 rate limit")

    snap = c.snapshot()
    assert snap["totals"]["calls"] == 2
    assert snap["totals"]["total_tokens"] == 27
    assert snap["totals"]["failures"] == 1
    assert snap["totals"]["rate_limited"] == 1
    assert snap["by_provider"]["openai"]["calls"] == 2
    assert snap["totals"]["cost_usd"] >= 0
    assert "budget" in snap
    assert "budget" in snap["by_provider"]["openai"]


def test_llm_metrics_cost_estimation_known_model_positive():
    c = LLMMetricsCollector(max_events=3)
    cost = c.estimate_cost_usd("openai", "gpt-4o-mini", 1000, 2000)
    assert cost > 0

def test_llm_metrics_snapshot_exposes_by_user():
    collector = LLMMetricsCollector(max_events=10)
    collector.record(provider="openai", model="gpt-4o-mini", latency_ms=10, prompt_tokens=10, completion_tokens=5, user_id="u-1")
    snap = collector.snapshot()
    assert "by_user" in snap
    assert "u-1" in snap["by_user"]