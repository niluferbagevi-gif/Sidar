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

def test_llm_metrics_rate_limit_detection_variants():
    c = LLMMetricsCollector(max_events=10)
    c.record(provider="anthropic", model="claude", latency_ms=50, success=False, error="HTTP 429 Too Many Requests")
    c.record(provider="anthropic", model="claude", latency_ms=50, success=False, error="Rate limit exceeded")
    c.record(provider="anthropic", model="claude", latency_ms=50, success=False, error="timeout")

    snap = c.snapshot()
    assert snap["totals"]["calls"] == 3
    assert snap["totals"]["rate_limited"] == 2
    assert snap["by_provider"]["anthropic"]["failures"] == 3

def test_llm_metrics_snapshot_by_user_counts_failures():
    collector = LLMMetricsCollector(max_events=10)
    collector.record(
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=12,
        prompt_tokens=1,
        completion_tokens=1,
        success=False,
        error="boom",
        user_id="test_user",
    )
    snap = collector.snapshot()
    assert snap["by_user"]["test_user"]["calls"] == 1
    assert snap["by_user"]["test_user"]["failures"] == 1


def test_llm_metrics_record_calculates_cost_when_none_and_handles_async_sink():
    collector = LLMMetricsCollector(max_events=5)
    observed = {"task_calls": 0}

    async def _sink(_event):
        observed["task_calls"] += 1

    collector.set_usage_sink(_sink)

    async def _run():
        collector.record(provider="openai", model="gpt-4o-mini", latency_ms=5, prompt_tokens=10, completion_tokens=2, cost_usd=None)
        await asyncio.sleep(0)

    import asyncio

    asyncio.run(_run())
    snap = collector.snapshot()
    assert snap["totals"]["cost_usd"] > 0
    assert observed["task_calls"] == 1

def test_estimate_cost_usd_openai_and_anthropic_exact_values():
    c = LLMMetricsCollector(max_events=5)

    # openai:gpt-4o-mini -> prompt:0.15$/1M, completion:0.60$/1M
    # 2_000 prompt + 3_000 completion = 0.0003 + 0.0018 = 0.0021
    openai_cost = c.estimate_cost_usd("openai", "gpt-4o-mini", 2_000, 3_000)
    assert openai_cost == 0.0021

    # anthropic:claude-3-5-sonnet-latest -> prompt:3$/1M, completion:15$/1M
    # 1_000 + 2_000 = 0.003 + 0.03 = 0.033
    anthropic_cost = c.estimate_cost_usd("anthropic", "claude-3-5-sonnet-latest", 1_000, 2_000)
    assert anthropic_cost == 0.033


def test_estimate_cost_usd_is_case_insensitive_and_unknown_model_zero():
    c = LLMMetricsCollector(max_events=5)

    mixed_case = c.estimate_cost_usd("OpenAI", "GPT-4O-MINI", 1_000, 1_000)
    lower_case = c.estimate_cost_usd("openai", "gpt-4o-mini", 1_000, 1_000)

    assert mixed_case == lower_case
    assert c.estimate_cost_usd("openai", "unknown-model", 10_000, 10_000) == 0.0