from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.router as router_mod


def _cfg(**overrides):
    base = dict(
        ENABLE_COST_ROUTING=True,
        COST_ROUTING_COMPLEXITY_THRESHOLD=0.55,
        COST_ROUTING_LOCAL_PROVIDER="ollama",
        COST_ROUTING_CLOUD_PROVIDER="openai",
        COST_ROUTING_DAILY_BUDGET_USD=1.0,
        COST_ROUTING_LOCAL_MODEL="llama3",
        COST_ROUTING_CLOUD_MODEL="gpt-4o-mini",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_query_complexity_analyzer_empty_and_penalized_simple_prompt() -> None:
    analyzer = router_mod.QueryComplexityAnalyzer()

    assert analyzer.score([{"role": "system", "content": "ignored"}]) == 0.0

    simple_prompt = [{"role": "user", "content": "What is Python? briefly explain"}]
    penalized = analyzer.score(simple_prompt)

    assert 0.0 < penalized < 0.2


def test_query_complexity_analyzer_complex_prompt_caps_to_max() -> None:
    analyzer = router_mod.QueryComplexityAnalyzer()
    heavy_text = (
        ("def class import async await lambda return raise try: except " * 30)
        + ("explain analyze compare evaluate describe in detail optimize architect " * 30)
        + ("what is " * 5)
        + ("?" * 20)
    )

    score = analyzer.score([{"role": "user", "content": heavy_text}])

    assert 0.0 <= score <= 1.0
    assert score == 0.5


def test_daily_budget_tracker_add_usage_exceeded_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline = iter(
        [
            1_000_000.0,  # __init__
            1_000_001.0,  # add #1
            1_000_002.0,  # add #2
            1_000_003.0,  # daily_usage (no reset)
            1_000_004.0,  # exceeded -> daily_usage (no reset)
            1_086_500.0,  # daily_usage (reset)
        ]
    )
    monkeypatch.setattr(router_mod.time, "time", lambda: next(timeline))

    tracker = router_mod._DailyBudgetTracker()
    tracker.add(0.75)
    tracker.add(-5.0)

    assert tracker.daily_usage() == 0.75
    assert tracker.exceeded(0.75) is True

    assert tracker.daily_usage() == 0.0


def test_record_routing_cost_delegates_to_global_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Tracker:
        def __init__(self):
            self.recorded = []

        def add(self, value: float) -> None:
            self.recorded.append(value)

    tracker = _Tracker()
    monkeypatch.setattr(router_mod, "_budget_tracker", tracker)

    router_mod.record_routing_cost(0.42)

    assert tracker.recorded == [0.42]


def test_cost_router_select_disabled_returns_defaults() -> None:
    router = router_mod.CostAwareRouter(_cfg(ENABLE_COST_ROUTING=False))

    provider, model = router.select([], "default-provider", "default-model")

    assert provider == "default-provider"
    assert model == "default-model"


def test_cost_router_select_budget_exceeded_forces_local(monkeypatch: pytest.MonkeyPatch) -> None:
    router = router_mod.CostAwareRouter(_cfg(COST_ROUTING_LOCAL_MODEL="local-model"))

    monkeypatch.setattr(router_mod, "_budget_tracker", SimpleNamespace(exceeded=lambda *_args, **_kwargs: True))

    provider, model = router.select([], "openai", "gpt-4")

    assert provider == "ollama"
    assert model == "local-model"


def test_cost_router_select_low_score_goes_local(monkeypatch: pytest.MonkeyPatch) -> None:
    router = router_mod.CostAwareRouter(_cfg())
    router._analyzer = SimpleNamespace(score=lambda *_args, **_kwargs: 0.10)
    monkeypatch.setattr(router_mod, "_budget_tracker", SimpleNamespace(exceeded=lambda *_args, **_kwargs: False))

    provider, model = router.select([{"role": "user", "content": "kısaca anlat"}], "openai", "gpt-4")

    assert provider == "ollama"
    assert model == "llama3"


def test_cost_router_select_high_score_without_cloud_keeps_default(monkeypatch: pytest.MonkeyPatch) -> None:
    router = router_mod.CostAwareRouter(_cfg(COST_ROUTING_CLOUD_PROVIDER=""))
    router._analyzer = SimpleNamespace(score=lambda *_args, **_kwargs: 0.9)
    monkeypatch.setattr(router_mod, "_budget_tracker", SimpleNamespace(exceeded=lambda *_args, **_kwargs: False))

    provider, model = router.select([{"role": "user", "content": "design pattern tradeoff"}], "openai", "gpt-4")

    assert provider == "openai"
    assert model == "gpt-4"


def test_cost_router_select_high_score_with_cloud_prefers_cloud_and_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    router = router_mod.CostAwareRouter(_cfg(COST_ROUTING_CLOUD_MODEL=""))
    router._analyzer = SimpleNamespace(score=lambda *_args, **_kwargs: 0.95)
    monkeypatch.setattr(router_mod, "_budget_tracker", SimpleNamespace(exceeded=lambda *_args, **_kwargs: False))

    provider, model = router.select([{"role": "user", "content": "analyze algorithm complexity"}], "openai", "gpt-4")

    assert provider == "openai"
    assert model == "gpt-4"


def test_cost_router_local_result_without_local_provider_returns_defaults() -> None:
    router = router_mod.CostAwareRouter(_cfg())
    router.local_provider = ""

    provider, model = router._local_result("default-provider", "default-model")

    assert provider == "default-provider"
    assert model == "default-model"


def test_cost_router_complexity_score_delegates_to_analyzer() -> None:
    router = router_mod.CostAwareRouter(_cfg())
    router._analyzer = SimpleNamespace(score=lambda messages: 0.33 if messages else 0.0)

    assert router.complexity_score([{"role": "user", "content": "test"}]) == 0.33
