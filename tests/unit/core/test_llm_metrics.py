import asyncio
import builtins
import types

import pytest

from core import llm_metrics
from core.llm_metrics import LLMMetricsCollector


def test_env_float_handles_defaults_and_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_FLOAT", raising=False)
    assert llm_metrics._env_float("TEST_FLOAT", 1.5) == 1.5

    monkeypatch.setenv("TEST_FLOAT", " ")
    assert llm_metrics._env_float("TEST_FLOAT", 2.5) == 2.5

    monkeypatch.setenv("TEST_FLOAT", "nan")
    assert llm_metrics._env_float("TEST_FLOAT", 3.5) == 3.5

    monkeypatch.setenv("TEST_FLOAT", "inf")
    assert llm_metrics._env_float("TEST_FLOAT", 4.5) == 4.5

    monkeypatch.setenv("TEST_FLOAT", "oops")
    assert llm_metrics._env_float("TEST_FLOAT", 5.5) == 5.5

    monkeypatch.setenv("TEST_FLOAT", "7.25")
    assert llm_metrics._env_float("TEST_FLOAT", 7.25) == 7.25


def test_env_float_handles_none_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_FLOAT_NONE", raising=False)
    assert llm_metrics._env_float("TEST_FLOAT_NONE", None) == 0.0


def test_context_user_id_roundtrip() -> None:
    token = llm_metrics.set_current_metrics_user_id("  user-1  ")
    assert llm_metrics.get_current_metrics_user_id() == "user-1"

    llm_metrics.reset_current_metrics_user_id(token)
    assert llm_metrics.get_current_metrics_user_id() == ""


def test_estimate_cost_known_and_unknown_models() -> None:
    known = LLMMetricsCollector.estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
    unknown = LLMMetricsCollector.estimate_cost_usd("x", "y", 100, 100)

    assert known == 0.75
    assert unknown == 0.0


def test_record_clamps_values_and_detects_rate_limit() -> None:
    collector = LLMMetricsCollector(max_events=3)

    token = llm_metrics.set_current_metrics_user_id("ctx-user")
    try:
        collector.record(
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=-10,
            prompt_tokens=-5,
            completion_tokens=-6,
            cost_usd=-1,
            success=False,
            error="429 rate limit happened",
            judge_score=0.9,
            hallucination_risk=0.2,
        )
    finally:
        llm_metrics.reset_current_metrics_user_id(token)

    event = list(collector._events)[0]
    assert event.user_id == "ctx-user"
    assert event.prompt_tokens == 0
    assert event.completion_tokens == 0
    assert event.total_tokens == 0
    assert event.cost_usd == 0.0
    assert event.latency_ms == 0.0
    assert event.rate_limited is True
    assert event.judge_score == 0.9
    assert event.hallucination_risk == 0.2


def test_record_usage_sink_schedules_awaitable_with_running_loop() -> None:
    collector = LLMMetricsCollector()
    seen = []

    async def sink(event):
        await asyncio.sleep(0)
        seen.append(event.provider)

    async def run_case() -> None:
        collector.set_usage_sink(sink)
        collector.record(provider="openai", model="gpt-4o", latency_ms=1)
        await asyncio.sleep(0)

    asyncio.run(run_case())
    assert seen == ["openai"]


def test_record_usage_sink_closes_awaitable_without_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = LLMMetricsCollector()

    class ClosableAwaitable:
        def __init__(self) -> None:
            self.closed = False

        def __await__(self):
            if False:
                yield None
            return None

        def close(self) -> None:
            self.closed = True

    awaitable = ClosableAwaitable()

    async def _await_closable() -> None:
        return await awaitable

    assert asyncio.run(_await_closable()) is None
    collector.set_usage_sink(lambda _event: awaitable)
    monkeypatch.setattr(
        asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop"))
    )

    collector.record(provider="openai", model="gpt-4o", latency_ms=1)

    assert awaitable.closed is True


def test_record_usage_sink_awaitable_without_close_and_without_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = LLMMetricsCollector()

    class NonClosableAwaitable:
        def __await__(self):
            if False:
                yield None
            return None

    awaitable = NonClosableAwaitable()

    async def _await_non_closable() -> None:
        return await awaitable

    assert asyncio.run(_await_non_closable()) is None
    collector.set_usage_sink(lambda _event: awaitable)
    monkeypatch.setattr(
        asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop"))
    )

    collector.record(provider="openai", model="gpt-4o", latency_ms=1)

    assert len(list(collector._events)) == 1


def test_record_usage_sink_errors_are_swallowed() -> None:
    collector = LLMMetricsCollector()
    collector.set_usage_sink(lambda _event: (_ for _ in ()).throw(RuntimeError("sink failed")))

    collector.record(provider="openai", model="gpt-4o", latency_ms=1)

    assert len(list(collector._events)) == 1


def test_record_usage_sink_non_awaitable_result_is_ignored() -> None:
    collector = LLMMetricsCollector()
    called = {"n": 0}

    def sink(_event):
        called["n"] += 1
        return "ok"

    collector.set_usage_sink(sink)
    collector.record(provider="openai", model="gpt-4o", latency_ms=1)
    assert called["n"] == 1


def test_snapshot_aggregates_provider_user_budget_recent_and_fallback_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = LLMMetricsCollector(max_events=10)

    monkeypatch.setenv("LLM_BUDGET_DAILY_USD", "1.0")
    monkeypatch.setenv("LLM_BUDGET_TOTAL_USD", "2.0")
    monkeypatch.setenv("OPENAI_BUDGET_DAILY_USD", "0.2")
    monkeypatch.setenv("OPENAI_BUDGET_TOTAL_USD", "0.3")

    now = 1_000_000.0
    monkeypatch.setattr(llm_metrics.time, "time", lambda: now)

    collector.record(
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=100,
        prompt_tokens=100,
        completion_tokens=200,
        cost_usd=0.25,
        success=False,
        error="failed",
        user_id="u1",
    )
    collector.record(
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=300,
        prompt_tokens=50,
        completion_tokens=50,
        cost_usd=0.10,
        success=True,
        user_id="u1",
    )

    events = list(collector._events)
    events[0].timestamp = now - 90000
    events[1].timestamp = now

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.cache_metrics":
            raise ImportError("blocked")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert builtins.__import__("json").__name__ == "json"

    snap = collector.snapshot()

    assert snap["window_events"] == 2
    assert snap["totals"]["calls"] == 2
    assert snap["totals"]["failures"] == 1
    assert snap["totals"]["total_tokens"] == 400
    assert snap["totals"]["cost_usd"] == 0.35

    openai = snap["by_provider"]["openai"]
    assert openai["latency_ms_avg"] == 200.0
    assert openai["latency_ms_max"] == 300.0
    assert openai["budget"]["daily_usage_usd"] == 0.1
    assert openai["budget"]["total_usage_usd"] == 0.35
    assert openai["budget"]["daily_exceeded"] is False
    assert openai["budget"]["total_exceeded"] is True

    assert snap["budget"]["daily_exceeded"] is False
    assert snap["budget"]["total_exceeded"] is False
    assert snap["by_user"]["u1"]["calls"] == 2
    assert len(snap["recent"]) == 2
    assert snap["cache"]["hits"] == 0


def test_snapshot_uses_cache_metrics_module_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = LLMMetricsCollector()
    collector.record(provider="openai", model="gpt-4o", latency_ms=1)

    monkeypatch.setitem(
        __import__("sys").modules,
        "core.cache_metrics",
        types.SimpleNamespace(get_cache_metrics=lambda: {"hits": 9, "misses": 1}),
    )

    snap = collector.snapshot()
    assert snap["cache"] == {"hits": 9, "misses": 1}


def test_get_collector_returns_singleton_instance() -> None:
    assert llm_metrics.get_llm_metrics_collector() is llm_metrics._COLLECTOR
