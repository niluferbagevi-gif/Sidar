"""LLM maliyet/latency/bütçe metrikleri için hafif, process-içi toplayıcı."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Coroutine, cast


@dataclass
class LLMMetricEvent:
    timestamp: float
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    success: bool
    rate_limited: bool
    user_id: str = ""
    error: str = ""
    # LLM-as-a-Judge alanları (opsiyonel; yalnızca judge değerlendirmesi yapılan olaylarda dolu)
    judge_score: float | None = None  # RAG alaka puanı 0.0–1.0
    hallucination_risk: float | None = None  # Halüsinasyon riski 0.0–1.0


def _env_float(key: str, default: float) -> float:
    if default is None:
        default = 0.0
    try:
        raw = os.getenv(key)
        if raw is None:
            return float(default)
        text = str(raw).strip()
        if not text:
            return float(default)
        value = float(text)
        if value != value or value in (float("inf"), float("-inf")):
            return float(default)
        return value
    except (TypeError, ValueError):
        return float(default)


# Yaklaşık maliyet tablosu (1M token başına USD)
# Not: Bu değerler dashboard trend amaçlıdır; faturalama sisteminin tek-kaynağı değildir.
_MODEL_PRICES_PER_1M: dict[str, dict[str, float]] = {
    "openai:gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "openai:gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "anthropic:claude-3-5-sonnet-latest": {"prompt": 3.00, "completion": 15.00},
    "anthropic:claude-3-5-haiku-latest": {"prompt": 0.80, "completion": 4.00},
}


_CURRENT_USER_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sidar_llm_user_id", default=""
)


def set_current_metrics_user_id(user_id: str) -> contextvars.Token[str]:
    return _CURRENT_USER_ID.set((user_id or "").strip())


def reset_current_metrics_user_id(token: contextvars.Token[str]) -> None:
    _CURRENT_USER_ID.reset(token)


def get_current_metrics_user_id() -> str:
    return _CURRENT_USER_ID.get()


class LLMMetricsCollector:
    def __init__(self, max_events: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: deque[LLMMetricEvent] = deque(maxlen=max_events)
        self._usage_sink: Callable[[LLMMetricEvent], Any] | None = None

    def set_usage_sink(self, sink: Callable[[LLMMetricEvent], Any] | None) -> None:
        self._usage_sink = sink

    @staticmethod
    def estimate_cost_usd(
        provider: str, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        key = f"{(provider or '').lower()}:{(model or '').lower()}"
        pricing = _MODEL_PRICES_PER_1M.get(key)
        if not pricing:
            return 0.0
        prompt_cost = (max(0, int(prompt_tokens or 0)) / 1_000_000) * pricing["prompt"]
        completion_cost = (max(0, int(completion_tokens or 0)) / 1_000_000) * pricing["completion"]
        return round(prompt_cost + completion_cost, 8)

    def record(
        self,
        *,
        provider: str,
        model: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float | None = None,
        success: bool = True,
        error: str = "",
        user_id: str = "",
        judge_score: float | None = None,
        hallucination_risk: float | None = None,
    ) -> None:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = prompt_tokens + completion_tokens
        err = (error or "").strip()
        rate_limited = ("429" in err) or ("rate limit" in err.lower())
        if cost_usd is None:
            cost_usd = self.estimate_cost_usd(provider, model, prompt_tokens, completion_tokens)

        resolved_user_id = (user_id or get_current_metrics_user_id() or "").strip()
        event = LLMMetricEvent(
            timestamp=time.time(),
            provider=provider,
            model=model,
            user_id=resolved_user_id,
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=max(0.0, float(cost_usd or 0.0)),
            success=bool(success),
            rate_limited=rate_limited,
            error=err[:500],
            judge_score=float(judge_score) if judge_score is not None else None,
            hallucination_risk=float(hallucination_risk)
            if hallucination_risk is not None
            else None,
        )
        with self._lock:
            self._events.append(event)

        if self._usage_sink is not None:
            try:
                result = self._usage_sink(event)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(cast(Coroutine[Any, Any, Any], result))
                    except RuntimeError:
                        if hasattr(result, "close"):
                            result.close()
                        pass
            except Exception:
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)

        by_provider: dict[str, dict[str, Any]] = {}
        by_user: dict[str, dict[str, Any]] = {}
        total_calls = len(events)
        total_failures = 0
        total_rate_limited = 0

        for e in events:
            row = by_provider.setdefault(
                e.provider,
                {
                    "calls": 0,
                    "failures": 0,
                    "rate_limited": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "latency_ms_avg": 0.0,
                    "latency_ms_max": 0.0,
                },
            )
            row["calls"] += 1
            row["failures"] += 0 if e.success else 1
            row["rate_limited"] += 1 if e.rate_limited else 0
            row["prompt_tokens"] += e.prompt_tokens
            row["completion_tokens"] += e.completion_tokens
            row["total_tokens"] += e.total_tokens
            row["cost_usd"] += e.cost_usd
            row["latency_ms_avg"] += e.latency_ms
            row["latency_ms_max"] = max(row["latency_ms_max"], e.latency_ms)

            if e.user_id:
                urow = by_user.setdefault(
                    e.user_id,
                    {"calls": 0, "failures": 0, "total_tokens": 0, "cost_usd": 0.0},
                )
                urow["calls"] += 1
                urow["failures"] += 0 if e.success else 1
                urow["total_tokens"] += e.total_tokens
                urow["cost_usd"] += e.cost_usd

            total_failures += 0 if e.success else 1
            total_rate_limited += 1 if e.rate_limited else 0

        day_ago = time.time() - 86400
        daily_cost_by_provider: dict[str, float] = {}
        for e in events:
            if e.timestamp >= day_ago:
                daily_cost_by_provider[e.provider] = (
                    daily_cost_by_provider.get(e.provider, 0.0) + e.cost_usd
                )

        for provider, row in by_provider.items():
            if row["calls"]:  # pragma: no cover
                row["latency_ms_avg"] = round(row["latency_ms_avg"] / row["calls"], 2)
            row["latency_ms_max"] = round(row["latency_ms_max"], 2)
            row["cost_usd"] = round(row["cost_usd"], 6)

            daily_limit = _env_float(
                f"{provider.upper()}_BUDGET_DAILY_USD", _env_float("LLM_BUDGET_DAILY_USD", 5.0)
            )
            total_limit = _env_float(
                f"{provider.upper()}_BUDGET_TOTAL_USD", _env_float("LLM_BUDGET_TOTAL_USD", 20.0)
            )
            daily_usage = round(daily_cost_by_provider.get(provider, 0.0), 6)
            total_usage = row["cost_usd"]
            row["budget"] = {
                "daily_limit_usd": daily_limit,
                "total_limit_usd": total_limit,
                "daily_usage_usd": daily_usage,
                "total_usage_usd": total_usage,
                "daily_remaining_usd": round(max(0.0, daily_limit - daily_usage), 6),
                "total_remaining_usd": round(max(0.0, total_limit - total_usage), 6),
                "daily_exceeded": daily_usage > daily_limit,
                "total_exceeded": total_usage > total_limit,
            }

        total_cost = round(sum(e.cost_usd for e in events), 6)
        global_daily = _env_float("LLM_BUDGET_DAILY_USD", 5.0)
        global_total = _env_float("LLM_BUDGET_TOTAL_USD", 20.0)

        # Semantic cache istatistikleri (modül düzeyinde sayaçtan)
        try:
            from core.cache_metrics import get_cache_metrics as _get_cache_metrics

            cache_stats = _get_cache_metrics()
        except Exception:
            cache_stats = {
                "hits": 0,
                "misses": 0,
                "skips": 0,
                "total_lookups": 0,
                "hit_rate": 0.0,
                "evictions": 0,
                "redis_errors": 0,
                "items": 0,
                "redis_latency_ms": 0.0,
            }

        return {
            "window_events": total_calls,
            "totals": {
                "calls": total_calls,
                "failures": total_failures,
                "rate_limited": total_rate_limited,
                "prompt_tokens": sum(e.prompt_tokens for e in events),
                "completion_tokens": sum(e.completion_tokens for e in events),
                "total_tokens": sum(e.total_tokens for e in events),
                "cost_usd": total_cost,
            },
            "budget": {
                "daily_limit_usd": global_daily,
                "total_limit_usd": global_total,
                "daily_usage_usd": total_cost,
                "total_usage_usd": total_cost,
                "daily_remaining_usd": round(max(0.0, global_daily - total_cost), 6),
                "total_remaining_usd": round(max(0.0, global_total - total_cost), 6),
                "daily_exceeded": total_cost > global_daily,
                "total_exceeded": total_cost > global_total,
            },
            "cache": cache_stats,
            "by_provider": by_provider,
            "by_user": by_user,
            "recent": [asdict(e) for e in events[-20:]],
        }


_COLLECTOR = LLMMetricsCollector()


def get_llm_metrics_collector() -> LLMMetricsCollector:
    return _COLLECTOR
