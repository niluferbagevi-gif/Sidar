from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import core.router as router
from core.router import CostAwareRouter, QueryComplexityAnalyzer, record_routing_cost


def _make_config(**overrides: object) -> SimpleNamespace:
    base = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.55,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_DAILY_BUDGET_USD": 1.0,
        "COST_ROUTING_TOKEN_THRESHOLD": 0,
        "COST_ROUTING_LOCAL_MODEL": "llama3",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def reset_budget_tracker() -> None:
    tracker = router._budget_tracker
    if hasattr(tracker, "_lock"):
        with tracker._lock:
            tracker._daily_cost = 0.0
            tracker._day_start = router.time.time()
    else:
        conn = sqlite3.connect(tracker._db_path)
        try:
            conn.execute(f"DELETE FROM {tracker._TABLE_NAME}")
            conn.commit()
        finally:
            conn.close()


def test_query_complexity_score_returns_zero_without_user_messages() -> None:
    analyzer = QueryComplexityAnalyzer()

    assert analyzer.score([]) == 0.0
    assert analyzer.score([{"role": "assistant", "content": "ignored"}]) == 0.0


def test_query_complexity_score_increases_with_code_and_reasoning_keywords() -> None:
    analyzer = QueryComplexityAnalyzer()
    messages = [
        {
            "role": "user",
            "content": (
                "Please explain and analyze this algorithm complexity. "
                "Use def example(): return value and ```python blocks? ?"
            ),
        }
    ]

    score = analyzer.score(messages)

    assert 0.55 <= score <= 1.0


def test_query_complexity_score_applies_simple_keyword_penalty() -> None:
    analyzer = QueryComplexityAnalyzer()
    complex_text = "analyze this algorithm and compare tradeoff?"
    simple_text = "what is analyze this algorithm and compare tradeoff?"

    score_without_penalty = analyzer.score([{"role": "user", "content": complex_text}])
    score_with_penalty = analyzer.score([{"role": "user", "content": simple_text}])

    assert score_with_penalty < score_without_penalty


def test_query_complexity_score_respects_upper_bound() -> None:
    analyzer = QueryComplexityAnalyzer()
    huge_payload = " ".join(
        [
            "analyze",
            "compare",
            "evaluate",
            "refactor",
            "optimize",
            "algorithm",
            "complexity",
            "tradeoff",
            "best practice",
            "def test_function():",
            "class TestClass:",
            "import os",
            "async def x():",
            "await y",
            "```python",
            "?",
        ]
        * 200
    )

    assert analyzer.score([{"role": "user", "content": huge_payload}]) == 1.0


def test_daily_budget_tracker_add_daily_usage_and_exceeded() -> None:
    tracker = router._DailyBudgetTracker()

    tracker.add(-2.0)
    tracker.add(0.25)
    tracker.add(0.15)

    assert tracker.daily_usage() == pytest.approx(0.40)
    assert tracker.exceeded(0.39) is True
    assert tracker.exceeded(1.0) is False


def test_daily_budget_tracker_resets_when_new_day(frozen_time) -> None:
    tracker = router._DailyBudgetTracker()
    tracker.add(0.5)

    assert tracker.daily_usage() == 0.5
    frozen_time.tick(delta=86401.0)
    assert tracker.daily_usage() == 0.0


def test_record_routing_cost_uses_global_tracker() -> None:
    record_routing_cost(0.33)

    assert router._budget_tracker.daily_usage() == pytest.approx(0.33)


def test_router_returns_defaults_when_disabled() -> None:
    cfg = _make_config(ENABLE_COST_ROUTING=False)
    cost_router = CostAwareRouter(cfg)

    provider, model = cost_router.select([], "default-provider", "default-model")

    assert (provider, model) == ("default-provider", "default-model")


def test_router_routes_to_local_when_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_config(COST_ROUTING_DAILY_BUDGET_USD=0.5)
    cost_router = CostAwareRouter(cfg)
    record_routing_cost(0.6)

    provider, model = cost_router.select(
        [{"role": "user", "content": "complex content analyze optimize"}],
        "default-provider",
        "default-model",
    )

    assert (provider, model) == ("ollama", "llama3")


def test_router_routes_to_local_for_low_complexity() -> None:
    cfg = _make_config(COST_ROUTING_COMPLEXITY_THRESHOLD=0.8)
    cost_router = CostAwareRouter(cfg)

    provider, model = cost_router.select(
        [{"role": "user", "content": "hello"}],
        "default-provider",
        "default-model",
    )

    assert (provider, model) == ("ollama", "llama3")


def test_router_returns_default_when_cloud_provider_missing() -> None:
    cfg = _make_config(COST_ROUTING_COMPLEXITY_THRESHOLD=0.2)
    cost_router = CostAwareRouter(cfg)
    cost_router.cloud_provider = ""

    provider, model = cost_router.select(
        [{"role": "user", "content": "analyze compare optimize algorithm tradeoff?"}],
        "default-provider",
        "default-model",
    )

    assert (provider, model) == ("default-provider", "default-model")


def test_router_routes_to_cloud_for_complex_queries() -> None:
    cfg = _make_config(COST_ROUTING_CLOUD_MODEL="", COST_ROUTING_COMPLEXITY_THRESHOLD=0.2)
    cost_router = CostAwareRouter(cfg)

    provider, model = cost_router.select(
        [
            {
                "role": "user",
                "content": "Please analyze and compare design pattern tradeoff with algorithm complexity?",
            }
        ],
        "default-provider",
        "fallback-model",
    )

    assert (provider, model) == ("openai", "fallback-model")


def test_local_result_returns_defaults_if_local_provider_missing() -> None:
    cfg = _make_config()
    cost_router = CostAwareRouter(cfg)
    cost_router.local_provider = ""

    provider, model = cost_router._local_result("default-provider", "default-model")

    assert (provider, model) == ("default-provider", "default-model")


def test_local_result_prefers_none_when_local_model_missing() -> None:
    cfg = _make_config(COST_ROUTING_LOCAL_MODEL="")
    cost_router = CostAwareRouter(cfg)

    provider, model = cost_router._local_result("default-provider", "default-model")

    assert (provider, model) == ("ollama", None)


def test_router_complexity_score_exposes_analyzer() -> None:
    cfg = _make_config()
    cost_router = CostAwareRouter(cfg)

    score = cost_router.complexity_score([{"role": "user", "content": "analyze this"}])

    assert score == cost_router._analyzer.score([{"role": "user", "content": "analyze this"}])


def test_router_stress_budget_threshold_always_falls_back_to_local() -> None:
    cfg = _make_config(COST_ROUTING_DAILY_BUDGET_USD=0.3, COST_ROUTING_COMPLEXITY_THRESHOLD=0.1)
    cost_router = CostAwareRouter(cfg)

    for _ in range(20):
        record_routing_cost(0.02)

    for _ in range(100):
        provider, model = cost_router.select(
            [{"role": "user", "content": "analyze and compare algorithm tradeoffs in detail?"}],
            "default-provider",
            "default-model",
        )
        assert (provider, model) == ("ollama", "llama3")


def test_router_stress_token_threshold_always_falls_back_to_local() -> None:
    cfg = _make_config(COST_ROUTING_TOKEN_THRESHOLD=40, COST_ROUTING_COMPLEXITY_THRESHOLD=0.1)
    cost_router = CostAwareRouter(cfg)

    high_token_messages = [
        {
            "role": "user",
            "content": " ".join(["analyze complex distributed orchestration and testing fallback behavior"] * 30),
        }
    ]

    for _ in range(100):
        provider, model = cost_router.select(
            high_token_messages,
            "default-provider",
            "default-model",
        )
        assert (provider, model) == ("ollama", "llama3")


def test_router_uses_sqlite_shared_budget_tracker_when_configured(tmp_path) -> None:
    db_path = str(tmp_path / "shared_budget.db")
    cfg = _make_config(COST_ROUTING_DAILY_BUDGET_USD=0.5, COST_ROUTING_SHARED_BUDGET_DB_PATH=db_path)
    cost_router = CostAwareRouter(cfg)
    assert isinstance(router._budget_tracker, router._SqliteDailyBudgetTracker)

    record_routing_cost(0.6)
    provider, model = cost_router.select(
        [{"role": "user", "content": "analyze distributed architecture tradeoffs in detail"}],
        "default-provider",
        "default-model",
    )
    assert (provider, model) == ("ollama", "llama3")
