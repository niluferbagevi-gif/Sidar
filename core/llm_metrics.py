"""LLM maliyet/latency/bütçe metrikleri için hafif, process-içi toplayıcı."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Deque, Dict, Optional


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
    error: str = ""


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# Yaklaşık maliyet tablosu (1M token başına USD)
# Not: Bu değerler dashboard trend amaçlıdır; faturalama sisteminin tek-kaynağı değildir.
_MODEL_PRICES_PER_1M: Dict[str, Dict[str, float]] = {
    "openai:gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "openai:gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "anthropic:claude-3-5-sonnet-latest": {"prompt": 3.00, "completion": 15.00},
    "anthropic:claude-3-5-haiku-latest": {"prompt": 0.80, "completion": 4.00},
}


class LLMMetricsCollector:
    def __init__(self, max_events: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: Deque[LLMMetricEvent] = deque(maxlen=max_events)

    @staticmethod
    def estimate_cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
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
        cost_usd: Optional[float] = None,
        success: bool = True,
        error: str = "",
    ) -> None:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = prompt_tokens + completion_tokens
        err = (error or "").strip()
        rate_limited = ("429" in err) or ("rate limit" in err.lower())
        if cost_usd is None:
            cost_usd = self.estimate_cost_usd(provider, model, prompt_tokens, completion_tokens)

        event = LLMMetricEvent(
            timestamp=time.time(),
            provider=provider,
            model=model,
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=max(0.0, float(cost_usd or 0.0)),
            success=bool(success),
            rate_limited=rate_limited,
            error=err[:500],
        )
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            events = list(self._events)

        by_provider: Dict[str, Dict[str, Any]] = {}
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

            total_failures += 0 if e.success else 1
            total_rate_limited += 1 if e.rate_limited else 0

        for provider, row in by_provider.items():
            if row["calls"]:
                row["latency_ms_avg"] = round(row["latency_ms_avg"] / row["calls"], 2)
            row["latency_ms_max"] = round(row["latency_ms_max"], 2)
            row["cost_usd"] = round(row["cost_usd"], 6)

            daily_limit = _env_float(f"{provider.upper()}_BUDGET_DAILY_USD", _env_float("LLM_BUDGET_DAILY_USD", 5.0))
            total_limit = _env_float(f"{provider.upper()}_BUDGET_TOTAL_USD", _env_float("LLM_BUDGET_TOTAL_USD", 20.0))
            row["budget"] = {
                "daily_limit_usd": daily_limit,
                "total_limit_usd": total_limit,
                "daily_usage_usd": row["cost_usd"],
                "total_usage_usd": row["cost_usd"],
                "daily_remaining_usd": round(max(0.0, daily_limit - row["cost_usd"]), 6),
                "total_remaining_usd": round(max(0.0, total_limit - row["cost_usd"]), 6),
                "daily_exceeded": row["cost_usd"] > daily_limit,
                "total_exceeded": row["cost_usd"] > total_limit,
            }

        total_cost = round(sum(e.cost_usd for e in events), 6)
        global_daily = _env_float("LLM_BUDGET_DAILY_USD", 5.0)
        global_total = _env_float("LLM_BUDGET_TOTAL_USD", 20.0)

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
            "by_provider": by_provider,
            "recent": [asdict(e) for e in events[-20:]],
        }


_COLLECTOR = LLMMetricsCollector()


def get_llm_metrics_collector() -> LLMMetricsCollector:
    return _COLLECTOR