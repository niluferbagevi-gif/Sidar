import sys
import time

# Bazı runtime testleri core/core.llm_metrics için stub modül bırakabiliyor.
# Bu durumda gerçek modülü zorla yeniden çöz.
sys.modules.pop("core.llm_metrics", None)
_core_pkg = sys.modules.get("core")
if _core_pkg is not None:
    _core_paths = [str(p) for p in (getattr(_core_pkg, "__path__", []) or [])]
    if not any("sidar_project/core" in p.replace("\\", "/") for p in _core_paths):
        sys.modules.pop("core", None)

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


def test_llm_metrics_record_uses_explicit_cost_without_estimating_and_falls_back_to_context_user():
    from core.llm_metrics import reset_current_metrics_user_id, set_current_metrics_user_id

    collector = LLMMetricsCollector(max_events=5)
    collector.estimate_cost_usd = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("estimate_cost_usd should not run"))

    token = set_current_metrics_user_id(" ctx-user ")
    try:
        collector.record(
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=9,
            prompt_tokens=3,
            completion_tokens=2,
            cost_usd=1.2345,
            user_id="",
        )
    finally:
        reset_current_metrics_user_id(token)

    snap = collector.snapshot()
    assert snap["totals"]["cost_usd"] == 1.2345
    assert snap["by_user"]["ctx-user"]["calls"] == 1
    assert snap["by_user"]["ctx-user"]["cost_usd"] == 1.2345

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

def test_env_float_handles_none_empty_nan_inf_and_invalid(monkeypatch):
    from core.llm_metrics import _env_float

    monkeypatch.setenv("LLM_F", "")
    assert _env_float("LLM_F", None) == 0.0

    monkeypatch.setenv("LLM_F", "NaN")
    assert _env_float("LLM_F", 1.5) == 1.5

    monkeypatch.setenv("LLM_F", "inf")
    assert _env_float("LLM_F", 2.5) == 2.5

    monkeypatch.setenv("LLM_F", "abc")
    assert _env_float("LLM_F", 3.5) == 3.5

def test_llm_metrics_record_handles_empty_metric_payload_without_user_bucket():
    collector = LLMMetricsCollector(max_events=5)
    collector.record(provider="", model="", latency_ms=0, prompt_tokens=None, completion_tokens=None, user_id="   ")

    snap = collector.snapshot()
    assert snap["totals"]["calls"] == 1
    assert snap["totals"]["total_tokens"] == 0
    assert snap["by_user"] == {}
    assert "" in snap["by_provider"]

def test_env_float_returns_default_for_getenv_none_and_invalid_text(monkeypatch):
    from core.llm_metrics import _env_float

    monkeypatch.setattr("core.llm_metrics.os.getenv", lambda _key: None)
    assert _env_float("LLM_MISSING", 4.2) == 4.2

    monkeypatch.setattr("core.llm_metrics.os.getenv", lambda _key: "12oops")
    assert _env_float("LLM_INVALID", 6.7) == 6.7


def test_env_float_returns_parsed_numeric_value(monkeypatch):
    from core.llm_metrics import _env_float

    monkeypatch.setattr("core.llm_metrics.os.getenv", lambda _key: "7.25")
    assert _env_float("LLM_VALID", 1.0) == 7.25


def test_safe_calls_normalizes_none_and_invalid_values():
    from core.llm_metrics import _safe_calls

    assert _safe_calls(None) == 0
    assert _safe_calls("oops") == 0
    assert _safe_calls(-3) == 0
    assert _safe_calls("2") == 2


def test_llm_metrics_snapshot_uses_zero_cache_stats_when_cache_metrics_import_fails(monkeypatch):
    import builtins

    collector = LLMMetricsCollector(max_events=5)
    collector.record(provider="openai", model="unknown-model-v1", latency_ms=10, prompt_tokens=10, completion_tokens=5)

    real_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "core.cache_metrics":
            raise RuntimeError("cache metrics unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)

    snap = collector.snapshot()

    assert snap["totals"]["cost_usd"] == 0.0
    assert snap["cache"]["hits"] == 0
    assert snap["cache"]["redis_latency_ms"] == 0.0


def test_llm_metrics_snapshot_handles_empty_event_window_without_provider_rows():
    collector = LLMMetricsCollector(max_events=5)

    snap = collector.snapshot()

    assert snap["window_events"] == 0
    assert snap["totals"]["calls"] == 0
    assert snap["totals"]["failures"] == 0
    assert snap["totals"]["rate_limited"] == 0
    assert snap["totals"]["total_tokens"] == 0
    assert snap["totals"]["cost_usd"] == 0.0
    assert snap["by_provider"] == {}
    assert snap["by_user"] == {}


def test_llm_metrics_snapshot_daily_budget_excludes_stale_events():
    from core.llm_metrics import LLMMetricEvent

    collector = LLMMetricsCollector(max_events=5)
    now = time.time()
    collector._events.extend(
        [
            LLMMetricEvent(
                timestamp=now - 90000,
                provider="openai",
                model="gpt-4o-mini",
                latency_ms=5,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_usd=0.4,
                success=True,
                rate_limited=False,
            ),
            LLMMetricEvent(
                timestamp=now,
                provider="openai",
                model="gpt-4o-mini",
                latency_ms=7,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_usd=0.6,
                success=True,
                rate_limited=False,
            ),
        ]
    )

    snap = collector.snapshot()
    budget = snap["by_provider"]["openai"]["budget"]
    assert snap["totals"]["cost_usd"] == 1.0
    assert budget["daily_usage_usd"] == 0.6
    assert budget["total_usage_usd"] == 1.0


def test_llm_metrics_snapshot_skips_latency_average_division_when_calls_is_zero_via_trace():
    collector = LLMMetricsCollector(max_events=5)
    collector.record(provider="openai", model="gpt-4o-mini", latency_ms=5, prompt_tokens=1, completion_tokens=1)

    previous = sys.gettrace()

    def _tracer(frame, event, arg):
        if frame.f_code.co_name == "snapshot" and event == "line" and frame.f_lineno == 209:
            row = frame.f_locals.get("row")
            if isinstance(row, dict):
                row["calls"] = 0
        return _tracer

    sys.settrace(_tracer)
    try:
        snap = collector.snapshot()
    finally:
        sys.settrace(previous)

    assert snap["by_provider"]["openai"]["latency_ms_avg"] == 5.0
    assert snap["by_provider"]["openai"]["latency_ms_max"] == 5.0
