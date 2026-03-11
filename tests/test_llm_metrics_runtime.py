from core.llm_metrics import LLMMetricsCollector


def test_llm_metrics_collector_aggregates_calls_and_tokens():
    c = LLMMetricsCollector(max_events=10)
    c.record(provider="openai", model="gpt-4o-mini", latency_ms=120, prompt_tokens=10, completion_tokens=5, success=True)
    c.record(provider="openai", model="gpt-4o-mini", latency_ms=80, prompt_tokens=8, completion_tokens=4, success=False, error="429 rate limit")

    snap = c.snapshot()
    assert snap["totals"]["calls"] == 2
    assert snap["totals"]["total_tokens"] == 27
    assert snap["totals"]["failures"] == 1
    assert snap["totals"]["rate_limited"] == 1
    assert snap["by_provider"]["openai"]["calls"] == 2
