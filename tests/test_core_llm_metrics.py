"""
core/llm_metrics.py için birim testleri.
LLMMetricEvent, _env_float, LLMMetricsCollector ve get_llm_metrics_collector
fonksiyonlarını kapsar.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import patch


def _get_llm_metrics():
    if "core.llm_metrics" in sys.modules:
        del sys.modules["core.llm_metrics"]
    import core.llm_metrics as lm
    # Modül seviyesi collector'ı sıfırla
    lm._COLLECTOR = lm.LLMMetricsCollector()
    return lm


# ══════════════════════════════════════════════════════════════
# _env_float
# ══════════════════════════════════════════════════════════════

class TestEnvFloat:
    def test_returns_default_when_env_not_set(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("_SIDAR_TEST_VAR", None)
            result = lm._env_float("_SIDAR_TEST_VAR", 3.14)
        assert result == 3.14

    def test_parses_float_from_env(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {"_SIDAR_TEST_VAR": "2.5"}):
            result = lm._env_float("_SIDAR_TEST_VAR", 0.0)
        assert result == 2.5

    def test_empty_string_returns_default(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {"_SIDAR_TEST_VAR": ""}):
            result = lm._env_float("_SIDAR_TEST_VAR", 9.9)
        assert result == 9.9

    def test_invalid_string_returns_default(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {"_SIDAR_TEST_VAR": "not_a_number"}):
            result = lm._env_float("_SIDAR_TEST_VAR", 7.0)
        assert result == 7.0

    def test_nan_returns_default(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {"_SIDAR_TEST_VAR": "nan"}):
            result = lm._env_float("_SIDAR_TEST_VAR", 5.0)
        assert result == 5.0

    def test_inf_returns_default(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {"_SIDAR_TEST_VAR": "inf"}):
            result = lm._env_float("_SIDAR_TEST_VAR", 5.0)
        assert result == 5.0


# ══════════════════════════════════════════════════════════════
# estimate_cost_usd
# ══════════════════════════════════════════════════════════════

class TestEstimateCostUsd:
    def test_known_model_computes_cost(self):
        lm = _get_llm_metrics()
        # openai:gpt-4o-mini: prompt=0.15, completion=0.60 per 1M tokens
        cost = lm.LLMMetricsCollector.estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert abs(cost - 0.75) < 1e-5

    def test_unknown_model_returns_zero(self):
        lm = _get_llm_metrics()
        cost = lm.LLMMetricsCollector.estimate_cost_usd("unknown", "model", 1000, 500)
        assert cost == 0.0

    def test_zero_tokens_returns_zero(self):
        lm = _get_llm_metrics()
        cost = lm.LLMMetricsCollector.estimate_cost_usd("openai", "gpt-4o", 0, 0)
        assert cost == 0.0

    def test_case_insensitive_provider_model(self):
        lm = _get_llm_metrics()
        cost1 = lm.LLMMetricsCollector.estimate_cost_usd("Anthropic", "claude-3-5-sonnet-latest", 500_000, 500_000)
        cost2 = lm.LLMMetricsCollector.estimate_cost_usd("anthropic", "claude-3-5-sonnet-latest", 500_000, 500_000)
        assert cost1 == cost2

    def test_negative_tokens_treated_as_zero(self):
        lm = _get_llm_metrics()
        cost = lm.LLMMetricsCollector.estimate_cost_usd("openai", "gpt-4o-mini", -100, -200)
        assert cost == 0.0


# ══════════════════════════════════════════════════════════════
# LLMMetricsCollector.record
# ══════════════════════════════════════════════════════════════

class TestLLMMetricsCollectorRecord:
    def setup_method(self):
        self.lm = _get_llm_metrics()
        self.collector = self.lm.LLMMetricsCollector()

    def test_record_creates_event(self):
        self.collector.record(provider="openai", model="gpt-4o-mini", latency_ms=100.0)
        snap = self.collector.snapshot()
        assert snap["totals"]["calls"] == 1

    def test_record_tokens_accumulated(self):
        self.collector.record(
            provider="openai", model="gpt-4o-mini", latency_ms=50.0,
            prompt_tokens=100, completion_tokens=50
        )
        snap = self.collector.snapshot()
        assert snap["totals"]["prompt_tokens"] == 100
        assert snap["totals"]["completion_tokens"] == 50
        assert snap["totals"]["total_tokens"] == 150

    def test_record_success_false(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=200.0, success=False)
        snap = self.collector.snapshot()
        assert snap["totals"]["failures"] == 1

    def test_record_rate_limited_detected_from_error(self):
        self.collector.record(
            provider="openai", model="gpt-4o", latency_ms=50.0,
            error="HTTP 429: rate limit exceeded"
        )
        snap = self.collector.snapshot()
        assert snap["totals"]["rate_limited"] == 1

    def test_record_rate_limited_by_429(self):
        self.collector.record(
            provider="openai", model="gpt-4o", latency_ms=50.0,
            error="Error 429"
        )
        snap = self.collector.snapshot()
        assert snap["totals"]["rate_limited"] == 1

    def test_record_auto_estimates_cost(self):
        self.collector.record(
            provider="openai", model="gpt-4o-mini", latency_ms=50.0,
            prompt_tokens=1_000_000, completion_tokens=0
        )
        snap = self.collector.snapshot()
        assert snap["totals"]["cost_usd"] > 0

    def test_record_explicit_cost_overrides_estimate(self):
        self.collector.record(
            provider="openai", model="gpt-4o-mini", latency_ms=50.0,
            cost_usd=99.99
        )
        snap = self.collector.snapshot()
        assert abs(snap["totals"]["cost_usd"] - 99.99) < 1e-4

    def test_record_by_provider_grouped(self):
        self.collector.record(provider="anthropic", model="claude-3-5-sonnet-latest", latency_ms=100.0)
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=80.0)
        snap = self.collector.snapshot()
        assert "anthropic" in snap["by_provider"]
        assert "openai" in snap["by_provider"]

    def test_record_user_id_from_context_var(self):
        token = self.lm.set_current_metrics_user_id("user42")
        try:
            self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0)
        finally:
            self.lm.reset_current_metrics_user_id(token)
        snap = self.collector.snapshot()
        assert "user42" in snap["by_user"]

    def test_record_explicit_user_id_used(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0, user_id="alice")
        snap = self.collector.snapshot()
        assert "alice" in snap["by_user"]

    def test_record_judge_score_stored(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0, judge_score=0.85)
        snap = self.collector.snapshot()
        recent = snap["recent"]
        assert len(recent) == 1
        assert recent[0]["judge_score"] == 0.85

    def test_record_hallucination_risk_stored(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0, hallucination_risk=0.2)
        snap = self.collector.snapshot()
        assert snap["recent"][0]["hallucination_risk"] == 0.2

    def test_record_error_truncated_at_500(self):
        long_error = "e" * 600
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0, error=long_error)
        snap = self.collector.snapshot()
        assert len(snap["recent"][0]["error"]) == 500

    @patch("core.llm_metrics.asyncio.get_running_loop")
    def test_record_usage_sink_awaitable_schedules_task_when_loop_exists(self, mock_get_loop):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector()
        done = {"value": False}

        async def _sink(_event):
            done["value"] = True

        class _FakeLoop:
            def create_task(self, coro):
                asyncio.run(coro)

        collector._usage_sink = _sink
        mock_get_loop.return_value = _FakeLoop()

        collector.record(provider="openai", model="gpt-4o", latency_ms=12.0)

        assert done["value"] is True


# ══════════════════════════════════════════════════════════════
# LLMMetricsCollector.snapshot
# ══════════════════════════════════════════════════════════════

class TestLLMMetricsCollectorSnapshot:
    def setup_method(self):
        self.lm = _get_llm_metrics()
        self.collector = self.lm.LLMMetricsCollector()

    def test_empty_snapshot_has_required_keys(self):
        snap = self.collector.snapshot()
        for key in ("window_events", "totals", "budget", "cache", "by_provider", "by_user", "recent"):
            assert key in snap

    def test_snapshot_budget_contains_limits(self):
        snap = self.collector.snapshot()
        budget = snap["budget"]
        assert "daily_limit_usd" in budget
        assert "total_limit_usd" in budget
        assert "daily_remaining_usd" in budget

    def test_snapshot_recent_limited_to_20(self):
        for i in range(25):
            self.collector.record(provider="openai", model="gpt-4o", latency_ms=float(i))
        snap = self.collector.snapshot()
        assert len(snap["recent"]) == 20

    def test_snapshot_latency_avg_computed(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=100.0)
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=200.0)
        snap = self.collector.snapshot()
        assert snap["by_provider"]["openai"]["latency_ms_avg"] == 150.0

    def test_snapshot_latency_max_computed(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0)
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=300.0)
        snap = self.collector.snapshot()
        assert snap["by_provider"]["openai"]["latency_ms_max"] == 300.0

    def test_snapshot_budget_exceeded_when_over_limit(self):
        self.collector.record(provider="openai", model="gpt-4o-mini", latency_ms=50.0, cost_usd=100.0)
        snap = self.collector.snapshot()
        assert snap["budget"]["total_exceeded"] is True

    def test_snapshot_by_provider_budget_present(self):
        self.collector.record(provider="openai", model="gpt-4o", latency_ms=50.0)
        snap = self.collector.snapshot()
        assert "budget" in snap["by_provider"]["openai"]

    def test_snapshot_empty_collector_never_divides_by_zero(self):
        collector = self.lm.LLMMetricsCollector(max_events=0)
        snap = collector.snapshot()
        assert snap["totals"]["calls"] == 0
        assert snap["totals"]["cost_usd"] == 0
        assert snap["by_provider"] == {}

    def test_snapshot_cache_metrics_exception_falls_back_to_zeroed_payload(self):
        fake_cache_mod = type("FakeCacheMod", (), {})()

        def _boom():
            raise ZeroDivisionError("bad cache denominator")

        fake_cache_mod.get_cache_metrics = _boom
        with patch.dict(sys.modules, {"core.cache_metrics": fake_cache_mod}):
            snap = self.collector.snapshot()
        assert snap["cache"]["hit_rate"] == 0.0
        assert snap["cache"]["total_lookups"] == 0

    def test_snapshot_daily_budget_ignores_events_older_than_24h(self):
        now = 1_700_000_000.0
        with patch("core.llm_metrics.time.time", return_value=now):
            self.collector.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0, cost_usd=2.5)
            self.collector.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0, cost_usd=1.5)
            # En eski olayı 24 saatin dışına it
            self.collector._events[0].timestamp = now - 86401
            snap = self.collector.snapshot()

        provider_budget = snap["by_provider"]["openai"]["budget"]
        assert provider_budget["daily_usage_usd"] == 1.5
        assert provider_budget["total_usage_usd"] == 4.0


# ══════════════════════════════════════════════════════════════
# ContextVar user id helpers
# ══════════════════════════════════════════════════════════════

class TestContextVarUserIds:
    def test_set_and_get_user_id(self):
        lm = _get_llm_metrics()
        token = lm.set_current_metrics_user_id("test_user")
        try:
            assert lm.get_current_metrics_user_id() == "test_user"
        finally:
            lm.reset_current_metrics_user_id(token)

    def test_reset_clears_user_id(self):
        lm = _get_llm_metrics()
        token = lm.set_current_metrics_user_id("temp_user")
        lm.reset_current_metrics_user_id(token)
        assert lm.get_current_metrics_user_id() == ""

    def test_empty_user_id_stripped(self):
        lm = _get_llm_metrics()
        token = lm.set_current_metrics_user_id("  ")
        try:
            assert lm.get_current_metrics_user_id() == ""
        finally:
            lm.reset_current_metrics_user_id(token)


# ══════════════════════════════════════════════════════════════
# get_llm_metrics_collector
# ══════════════════════════════════════════════════════════════

class TestGetLlmMetricsCollector:
    def test_returns_collector_instance(self):
        lm = _get_llm_metrics()
        collector = lm.get_llm_metrics_collector()
        assert isinstance(collector, lm.LLMMetricsCollector)

    def test_same_instance_on_repeated_calls(self):
        lm = _get_llm_metrics()
        c1 = lm.get_llm_metrics_collector()
        c2 = lm.get_llm_metrics_collector()
        assert c1 is c2


# ══════════════════════════════════════════════════════════════
# max_events deque sınırı
# ══════════════════════════════════════════════════════════════

class TestMaxEvents:
    def test_max_events_limits_stored_events(self):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector(max_events=5)
        for i in range(10):
            collector.record(provider="openai", model="gpt-4o", latency_ms=float(i))
        snap = collector.snapshot()
        # Only 5 events retained
        assert snap["totals"]["calls"] == 5


class TestUsageSinkAndAsyncPaths:
    def test_record_calls_usage_sink_sync(self):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector()
        called = []

        def sink(event):
            called.append(event.provider)

        collector.set_usage_sink(sink)
        collector.record(provider="openai", model="gpt-4o", latency_ms=10.0)

        assert called == ["openai"]

    def test_record_usage_sink_exception_is_swallowed(self):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector()

        def bad_sink(_event):
            raise RuntimeError("sink failed")

        collector.set_usage_sink(bad_sink)
        collector.record(provider="openai", model="gpt-4o", latency_ms=10.0)

        snap = collector.snapshot()
        assert snap["totals"]["calls"] == 1

    def test_record_usage_sink_awaitable_without_running_loop(self):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector()

        async def sink_async(_event):
            return None

        collector.set_usage_sink(sink_async)
        collector.record(provider="openai", model="gpt-4o", latency_ms=10.0)

        snap = collector.snapshot()
        assert snap["totals"]["calls"] == 1

    def test_record_usage_sink_awaitable_without_close_does_not_crash(self):
        lm = _get_llm_metrics()
        collector = lm.LLMMetricsCollector()

        class _AwaitableNoClose:
            def __await__(self):
                if False:
                    yield
                return None

        def sink_async_like(_event):
            return _AwaitableNoClose()

        collector.set_usage_sink(sink_async_like)
        with patch("core.llm_metrics.asyncio.get_running_loop", side_effect=RuntimeError):
            collector.record(provider="openai", model="gpt-4o", latency_ms=10.0)

        snap = collector.snapshot()
        assert snap["totals"]["calls"] == 1


class TestEnvFloatExtra:
    def test_none_default_is_normalized_to_zero(self):
        lm = _get_llm_metrics()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("_SIDAR_TEST_VAR_NONE_DEFAULT", None)
            result = lm._env_float("_SIDAR_TEST_VAR_NONE_DEFAULT", None)
        assert result == 0.0
