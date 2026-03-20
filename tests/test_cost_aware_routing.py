"""Testler: Cost-Aware Model Routing (Özellik 5)"""
from __future__ import annotations
import time
import pytest
from unittest.mock import MagicMock, patch


# ─── Karmaşıklık Analizörü ───────────────────────────────────────────────────

from core.router import QueryComplexityAnalyzer, CostAwareRouter, _DailyBudgetTracker


def _msgs(content: str):
    return [{"role": "user", "content": content}]


class TestQueryComplexityAnalyzer:
    def setup_method(self):
        self.analyzer = QueryComplexityAnalyzer()

    def test_empty_returns_zero(self):
        assert self.analyzer.score([]) == 0.0

    def test_simple_question_low_score(self):
        score = self.analyzer.score(_msgs("what is Python?"))
        assert score < 0.55, f"Basit soru yüksek skor aldı: {score}"

    def test_code_keywords_increase_score(self):
        code_msg = _msgs("Write a Python ```python def fibonacci(n): ...``` function")
        score = self.analyzer.score(code_msg)
        assert score > 0.2

    def test_long_complex_query_high_score(self):
        long_msg = _msgs(
            "Please analyze and compare the architectural tradeoffs between "
            "microservices and monolithic architectures, explain the best practice "
            "design patterns for each, refactor the code to implement dependency "
            "injection using async class def import patterns, evaluate the algorithmic "
            "complexity of each approach, consider async await patterns for performance "
            "optimization, and describe in detail how the tradeoff decisions affect "
            "long-term maintainability. How should we design the architecture? "
            "Which patterns are most scalable? What are the performance implications?"
        )
        score = self.analyzer.score(long_msg)
        assert score >= 0.55, f"Karmaşık sorgu düşük skor aldı: {score}"

    def test_simple_keyword_reduces_score(self):
        simple_msg = _msgs("briefly what is a list?")
        complex_msg = _msgs("what is a list and can you explain compare evaluate?")
        simple_score = self.analyzer.score(simple_msg)
        complex_score = self.analyzer.score(complex_msg)
        assert simple_score < complex_score

    def test_score_bounded_0_to_1(self):
        very_long = _msgs("a" * 5000 + " ".join(["def class import async await lambda"] * 30))
        score = self.analyzer.score(very_long)
        assert 0.0 <= score <= 1.0

    def test_multiple_questions_increase_score(self):
        multi_q = _msgs("What is this? How does it work? Why? When?")
        single_q = _msgs("What is this?")
        assert self.analyzer.score(multi_q) > self.analyzer.score(single_q)


# ─── Bütçe Takibçisi ────────────────────────────────────────────────────────

class TestDailyBudgetTracker:
    def setup_method(self):
        self.tracker = _DailyBudgetTracker()

    def test_initial_usage_is_zero(self):
        assert self.tracker.daily_usage() == 0.0

    def test_add_increases_usage(self):
        self.tracker.add(0.5)
        assert self.tracker.daily_usage() == pytest.approx(0.5)

    def test_exceeded_returns_true_when_over_limit(self):
        self.tracker.add(2.0)
        assert self.tracker.exceeded(1.0) is True

    def test_exceeded_returns_false_when_under_limit(self):
        self.tracker.add(0.5)
        assert self.tracker.exceeded(1.0) is False

    def test_negative_cost_ignored(self):
        self.tracker.add(-1.0)
        assert self.tracker.daily_usage() == 0.0

    def test_daily_usage_resets_when_new_day_starts(self):
        self.tracker.add(0.75)
        self.tracker._day_start = time.time() - 86500

        usage = self.tracker.daily_usage()

        assert usage == 0.0
        assert self.tracker._day_start > time.time() - 5


# ─── CostAwareRouter ────────────────────────────────────────────────────────

def _make_config(**kwargs):
    cfg = MagicMock()
    defaults = {
        "ENABLE_COST_ROUTING": True,
        "COST_ROUTING_COMPLEXITY_THRESHOLD": 0.55,
        "COST_ROUTING_LOCAL_PROVIDER": "ollama",
        "COST_ROUTING_LOCAL_MODEL": "",
        "COST_ROUTING_CLOUD_PROVIDER": "openai",
        "COST_ROUTING_CLOUD_MODEL": "gpt-4o",
        "COST_ROUTING_DAILY_BUDGET_USD": 10.0,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


class TestCostAwareRouter:
    def _router(self, **kwargs):
        cfg = _make_config(**kwargs)
        return CostAwareRouter(cfg)

    def test_disabled_returns_default(self):
        router = self._router(ENABLE_COST_ROUTING=False)
        provider, model = router.select(_msgs("complex query with class def async"), "ollama", "llama")
        assert provider == "ollama"
        assert model == "llama"

    def test_simple_query_routes_to_local(self):
        router = self._router()
        provider, model = router.select(_msgs("what is Python?"), "openai", "gpt-4o")
        assert provider == "ollama"

    def test_complex_query_routes_to_cloud(self):
        router = self._router()
        complex_msgs = [{"role": "user", "content": (
            "Please analyze and compare architectural tradeoffs between "
            "microservices and monolith, explain best practice design patterns, "
            "refactor the async class def import code and evaluate complexity."
        )}]
        provider, model = router.select(complex_msgs, "ollama", None)
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_budget_exceeded_routes_to_local(self):
        router = self._router(COST_ROUTING_DAILY_BUDGET_USD=0.001)
        # Kendi tracker'ına çok küçük limit ver
        router.daily_budget_usd = 0.001
        router._router_budget = _DailyBudgetTracker()
        import core.router as r_mod
        original = r_mod._budget_tracker
        r_mod._budget_tracker = _DailyBudgetTracker()
        r_mod._budget_tracker.add(1.0)  # Bütçeyi aş
        try:
            complex_msgs = [{"role": "user", "content": "analyze compare refactor evaluate algorithm complexity"}]
            provider, _ = router.select(complex_msgs, "ollama", None)
            assert provider == "ollama"
        finally:
            r_mod._budget_tracker = original

    def test_no_cloud_provider_returns_default(self):
        router = self._router(COST_ROUTING_CLOUD_PROVIDER="")
        # Eşiği 0.0 yaparak herhangi bir sorgunun "karmaşık" sayılmasını sağla
        router.complexity_threshold = 0.0
        complex_msgs = [{"role": "user", "content": "analyze compare evaluate refactor algorithm complex class def"}]
        provider, model = router.select(complex_msgs, "anthropic", "claude-3")
        # Bulut sağlayıcı yoksa varsayılan provider'a dönmeli
        assert provider == "anthropic"
        assert model == "claude-3"

    def test_complexity_score_method(self):
        router = self._router()
        score = router.complexity_score(_msgs("what is this?"))
        assert 0.0 <= score <= 1.0

    def test_no_cloud_model_uses_default(self):
        router = self._router(COST_ROUTING_CLOUD_MODEL="")
        complex_msgs = [{"role": "user", "content": "analyze compare refactor evaluate architectural algorithm complex class def async"}]
        provider, model = router.select(complex_msgs, "ollama", "fallback-model")
        if provider == "openai":
            assert model == "fallback-model"

    def test_local_result_returns_defaults_when_local_provider_is_blank(self):
        router = self._router()
        router.local_provider = ""

        provider, model = router._local_result("openai", "gpt-4o-mini")

        assert provider == "openai"
        assert model == "gpt-4o-mini"


# ─── record_routing_cost yardımcı fonksiyon ─────────────────────────────────

def test_record_routing_cost():
    import core.router as r_mod
    original = r_mod._budget_tracker
    r_mod._budget_tracker = _DailyBudgetTracker()
    try:
        r_mod.record_routing_cost(0.25)
        assert r_mod._budget_tracker.daily_usage() == pytest.approx(0.25)
    finally:
        r_mod._budget_tracker = original
