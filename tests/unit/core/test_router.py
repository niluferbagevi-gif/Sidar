from types import SimpleNamespace

import core.router as router_module
from core.router import CostAwareRouter, QueryComplexityAnalyzer, _DailyBudgetTracker


def _config(**overrides):
    base = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.55,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_DAILY_BUDGET_USD": 1.0,
        "COST_ROUTING_LOCAL_MODEL": "llama3",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o-mini",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_query_complexity_analyzer_scores_empty_and_simple_prompts():
    analyzer = QueryComplexityAnalyzer()

    assert analyzer.score([]) == 0.0
    assert analyzer.score([{"role": "assistant", "content": "ignored"}]) == 0.0

    score = analyzer.score([{"role": "user", "content": "What is cache? briefly"}])
    assert 0.0 < score < 0.2


def test_query_complexity_analyzer_scores_complex_prompt_higher_than_simple():
    analyzer = QueryComplexityAnalyzer()
    simple = analyzer.score([{"role": "user", "content": "define api"}])

    complex_prompt = """
    Please explain and analyze the tradeoff of this algorithm?
    compare alternatives and optimize this function.
    ```python
    async def solve(x):
        return x
    ```
    """
    complex_score = analyzer.score([{"role": "user", "content": complex_prompt}])

    assert complex_score > simple
    assert 0.4 <= complex_score <= 1.0


def test_daily_budget_tracker_add_daily_usage_and_reset(monkeypatch):
    tracker = _DailyBudgetTracker()
    start = 1_700_000_000.0
    times = iter([start, start, start + 10, start + 86_401, start + 86_401])
    monkeypatch.setattr(router_module.time, "time", lambda: next(times))

    tracker._day_start = start
    tracker.add(0.5)
    tracker.add(-5)
    assert tracker.daily_usage() == 0.5

    # next day call should reset usage
    assert tracker.daily_usage() == 0.0


def test_cost_aware_router_returns_default_when_disabled():
    cfg = _config(ENABLE_COST_ROUTING=False)
    router = CostAwareRouter(cfg)

    provider, model = router.select([{"role": "user", "content": "anything"}], "anthropic", "claude")

    assert (provider, model) == ("anthropic", "claude")


def test_cost_aware_router_uses_local_when_budget_exceeded(monkeypatch):
    cfg = _config(COST_ROUTING_DAILY_BUDGET_USD=0.1)
    router = CostAwareRouter(cfg)
    monkeypatch.setattr(router_module._budget_tracker, "exceeded", lambda _limit: True)

    provider, model = router.select([{"role": "user", "content": "hard question"}], "openai", "gpt-4o")

    assert (provider, model) == ("ollama", "llama3")


def test_cost_aware_router_uses_local_for_low_complexity(monkeypatch):
    cfg = _config(COST_ROUTING_COMPLEXITY_THRESHOLD=0.9)
    router = CostAwareRouter(cfg)
    monkeypatch.setattr(router_module._budget_tracker, "exceeded", lambda _limit: False)

    provider, model = router.select([{"role": "user", "content": "what is python?"}], "openai", "gpt-4o")

    assert (provider, model) == ("ollama", "llama3")


def test_cost_aware_router_uses_cloud_for_complex_queries(monkeypatch):
    cfg = _config(COST_ROUTING_COMPLEXITY_THRESHOLD=0.2)
    router = CostAwareRouter(cfg)
    monkeypatch.setattr(router_module._budget_tracker, "exceeded", lambda _limit: False)

    provider, model = router.select(
        [{"role": "user", "content": "analyze and compare this algorithm? refactor code"}],
        "openai",
        "gpt-4o",
    )

    assert (provider, model) == ("openai", "gpt-4o-mini")


def test_cost_aware_router_falls_back_to_default_when_cloud_not_configured(monkeypatch):
    cfg = _config(COST_ROUTING_CLOUD_PROVIDER="", COST_ROUTING_COMPLEXITY_THRESHOLD=0.1)
    router = CostAwareRouter(cfg)
    monkeypatch.setattr(router_module._budget_tracker, "exceeded", lambda _limit: False)

    provider, model = router.select(
        [{"role": "user", "content": "analyze compare evaluate optimize"}],
        "anthropic",
        "claude-3-5-sonnet",
    )

    assert (provider, model) == ("anthropic", "claude-3-5-sonnet")


def test_local_result_uses_default_when_local_provider_empty():
    cfg = _config(COST_ROUTING_LOCAL_PROVIDER="")
    router = CostAwareRouter(cfg)

    provider, model = router._local_result("openai", "gpt-4o")

    assert (provider, model) == ("ollama", "llama3")


def test_complexity_score_proxies_to_analyzer(monkeypatch):
    router = CostAwareRouter(_config())
    monkeypatch.setattr(router._analyzer, "score", lambda _messages: 0.42)

    assert router.complexity_score([{"role": "user", "content": "x"}]) == 0.42
