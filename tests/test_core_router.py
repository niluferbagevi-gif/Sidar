"""
core/router.py için birim testleri.
QueryComplexityAnalyzer, _DailyBudgetTracker, CostAwareRouter ve
record_routing_cost fonksiyonunu kapsar.
"""
from __future__ import annotations

import sys
import time
from unittest.mock import patch


def _get_router():
    if "core.router" in sys.modules:
        del sys.modules["core.router"]
    import core.router as router
    return router


# ══════════════════════════════════════════════════════════════
# QueryComplexityAnalyzer
# ══════════════════════════════════════════════════════════════

class TestQueryComplexityAnalyzerEmpty:
    def test_empty_messages_returns_zero(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        assert analyzer.score([]) == 0.0

    def test_no_user_messages_returns_zero(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [{"role": "assistant", "content": "cevap"}]
        assert analyzer.score(msgs) == 0.0

    def test_empty_content_returns_zero(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [{"role": "user", "content": ""}]
        assert analyzer.score(msgs) == 0.0

    def test_none_content_returns_zero(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [{"role": "user", "content": None}]
        assert analyzer.score(msgs) == 0.0


class TestQueryComplexityAnalyzerLength:
    def test_short_text_low_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        score = analyzer.score([{"role": "user", "content": "hi"}])
        assert score < 0.1

    def test_long_text_contributes_up_to_035(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        long_text = "x " * 500  # 1000 chars, above 800 budget
        score = analyzer.score([{"role": "user", "content": long_text}])
        assert score >= 0.35

    def test_score_in_range_zero_to_one(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [{"role": "user", "content": "def foo(): pass\n" * 20}]
        score = analyzer.score(msgs)
        assert 0.0 <= score <= 1.0


class TestQueryComplexityAnalyzerKeywords:
    def test_code_keywords_increase_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        base = analyzer.score([{"role": "user", "content": "merhaba"}])
        code = analyzer.score([{"role": "user", "content": "def foo(): return import class"}])
        assert code > base

    def test_reasoning_keywords_increase_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        base = analyzer.score([{"role": "user", "content": "merhaba"}])
        reason = analyzer.score([{"role": "user", "content": "explain analyze compare evaluate"}])
        assert reason > base

    def test_simple_keyword_penalty_halves_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        normal = analyzer.score([{"role": "user", "content": "explain the algorithm architecture in detail"}])
        simple = analyzer.score([{"role": "user", "content": "what is the algorithm architecture in detail"}])
        assert simple < normal

    def test_multiple_questions_increase_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        base = analyzer.score([{"role": "user", "content": "ne yapmalıyım"}])
        multi = analyzer.score([{"role": "user", "content": "ne yapmalıyım? ne oldu? neden? nasıl?"}])
        assert multi > base

    def test_combined_long_code_high_score(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        text = ("refactor optimize architect design pattern algorithm complexity tradeoff "
                "def class import async await lambda ```python " * 5)
        score = analyzer.score([{"role": "user", "content": text}])
        assert score >= 0.8


class TestQueryComplexityAnalyzerMultiUser:
    def test_only_user_messages_counted(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [
            {"role": "system", "content": "def class import " * 10},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "def class " * 10},
        ]
        score = analyzer.score(msgs)
        assert score < 0.15  # Only "hi" from user

    def test_multiple_user_messages_combined(self):
        mod = _get_router()
        analyzer = mod.QueryComplexityAnalyzer()
        msgs = [
            {"role": "user", "content": "x " * 200},
            {"role": "user", "content": "y " * 200},
        ]
        score = analyzer.score(msgs)
        assert score >= 0.35  # Combined = 800 chars, should hit length cap


# ══════════════════════════════════════════════════════════════
# _DailyBudgetTracker
# ══════════════════════════════════════════════════════════════

class TestDailyBudgetTracker:
    def _new_tracker(self):
        mod = _get_router()
        return mod._DailyBudgetTracker()

    def test_initial_usage_is_zero(self):
        tracker = self._new_tracker()
        assert tracker.daily_usage() == 0.0

    def test_add_increases_usage(self):
        tracker = self._new_tracker()
        tracker.add(0.5)
        assert tracker.daily_usage() == 0.5

    def test_multiple_adds_accumulate(self):
        tracker = self._new_tracker()
        tracker.add(0.3)
        tracker.add(0.4)
        assert abs(tracker.daily_usage() - 0.7) < 1e-9

    def test_negative_add_ignored(self):
        tracker = self._new_tracker()
        tracker.add(-1.0)
        assert tracker.daily_usage() == 0.0

    def test_exceeded_false_below_limit(self):
        tracker = self._new_tracker()
        tracker.add(0.5)
        assert tracker.exceeded(1.0) is False

    def test_exceeded_true_at_limit(self):
        tracker = self._new_tracker()
        tracker.add(1.0)
        assert tracker.exceeded(1.0) is True

    def test_exceeded_true_above_limit(self):
        tracker = self._new_tracker()
        tracker.add(1.5)
        assert tracker.exceeded(1.0) is True

    def test_resets_after_86400_seconds(self):
        tracker = self._new_tracker()
        tracker.add(0.8)
        # Simulate a day having passed
        tracker._day_start -= 86401
        assert tracker.daily_usage() == 0.0


# ══════════════════════════════════════════════════════════════
# CostAwareRouter
# ══════════════════════════════════════════════════════════════

def _make_config(**kwargs):
    class _Cfg:
        ENABLE_COST_ROUTING = False
        COST_ROUTING_COMPLEXITY_THRESHOLD = 0.55
        COST_ROUTING_LOCAL_PROVIDER = "ollama"
        COST_ROUTING_CLOUD_PROVIDER = "anthropic"
        COST_ROUTING_DAILY_BUDGET_USD = 1.0
        COST_ROUTING_LOCAL_MODEL = "llama3"
        COST_ROUTING_CLOUD_MODEL = "claude-3-5-sonnet"

    for k, v in kwargs.items():
        setattr(_Cfg, k, v)
    return _Cfg()


class TestCostAwareRouterDisabled:
    def test_disabled_returns_default(self):
        mod = _get_router()
        router = mod.CostAwareRouter(_make_config(ENABLE_COST_ROUTING=False))
        provider, model = router.select(
            [{"role": "user", "content": "test"}], "gemini", "gemini-pro"
        )
        assert provider == "gemini"
        assert model == "gemini-pro"

    def test_disabled_default_none_model(self):
        mod = _get_router()
        router = mod.CostAwareRouter(_make_config(ENABLE_COST_ROUTING=False))
        provider, model = router.select([], "openai")
        assert provider == "openai"
        assert model is None


class TestCostAwareRouterBudgetExceeded:
    def test_budget_exceeded_routes_to_local(self):
        mod = _get_router()
        router = mod.CostAwareRouter(_make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_DAILY_BUDGET_USD=0.01))
        # Inject budget exceeded state
        with patch.object(mod._budget_tracker, "exceeded", return_value=True):
            provider, model = router.select(
                [{"role": "user", "content": "complex " * 100}],
                "anthropic",
                "claude-3-5-sonnet",
            )
        assert provider == "ollama"
        assert model == "llama3"


class TestCostAwareRouterComplexityRouting:
    def test_simple_query_routes_to_local(self):
        mod = _get_router()
        router = mod.CostAwareRouter(
            _make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_COMPLEXITY_THRESHOLD=0.55)
        )
        with patch.object(mod._budget_tracker, "exceeded", return_value=False):
            provider, model = router.select(
                [{"role": "user", "content": "hi"}], "anthropic", "claude-3-5-sonnet"
            )
        assert provider == "ollama"

    def test_complex_query_routes_to_cloud(self):
        mod = _get_router()
        router = mod.CostAwareRouter(
            _make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_COMPLEXITY_THRESHOLD=0.1)
        )
        complex_msg = [{"role": "user", "content": "refactor optimize design pattern algorithm " * 5 + "x " * 300}]
        with patch.object(mod._budget_tracker, "exceeded", return_value=False):
            provider, model = router.select(complex_msg, "ollama", "llama3")
        assert provider == "anthropic"
        assert model == "claude-3-5-sonnet"

    def test_no_cloud_provider_returns_default(self):
        mod = _get_router()
        router = mod.CostAwareRouter(
            _make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_COMPLEXITY_THRESHOLD=0.1, COST_ROUTING_CLOUD_PROVIDER="")
        )
        complex_msg = [{"role": "user", "content": "analyze evaluate compare " * 5 + "x " * 300}]
        with patch.object(mod._budget_tracker, "exceeded", return_value=False):
            provider, model = router.select(complex_msg, "gemini", "gemini-pro")
        assert provider == "gemini"
        assert model == "gemini-pro"


class TestCostAwareRouterLocalResult:
    def test_empty_local_provider_falls_back_to_ollama(self):
        # `or "ollama"` guard: empty string becomes "ollama"
        mod = _get_router()
        router = mod.CostAwareRouter(
            _make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_LOCAL_PROVIDER="")
        )
        # local_provider is "ollama" (fallback), so simple query → "ollama"
        with patch.object(mod._budget_tracker, "exceeded", return_value=False):
            provider, _ = router.select(
                [{"role": "user", "content": "hi"}], "gemini", "gemini-pro"
            )
        assert provider == "ollama"

    def test_local_model_empty_returns_none(self):
        mod = _get_router()
        router = mod.CostAwareRouter(
            _make_config(ENABLE_COST_ROUTING=True, COST_ROUTING_LOCAL_MODEL="")
        )
        with patch.object(mod._budget_tracker, "exceeded", return_value=False):
            provider, model = router.select(
                [{"role": "user", "content": "hi"}], "gemini", "gemini-pro"
            )
        assert provider == "ollama"
        assert model is None


class TestCostAwareRouterComplexityScore:
    def test_complexity_score_delegates_to_analyzer(self):
        mod = _get_router()
        router = mod.CostAwareRouter(_make_config())
        score = router.complexity_score([{"role": "user", "content": "def foo(): pass"}])
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ══════════════════════════════════════════════════════════════
# record_routing_cost
# ══════════════════════════════════════════════════════════════

class TestRecordRoutingCost:
    def test_adds_to_budget_tracker(self):
        mod = _get_router()
        before = mod._budget_tracker.daily_usage()
        mod.record_routing_cost(0.05)
        after = mod._budget_tracker.daily_usage()
        assert after >= before + 0.05 - 1e-9
