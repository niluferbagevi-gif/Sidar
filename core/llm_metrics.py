"""LLM maliyet/latency metrikleri için hafif, process-içi toplayıcı."""

from __future__ import annotations

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
    success: bool
    rate_limited: bool
    error: str = ""


class LLMMetricsCollector:
    def __init__(self, max_events: int = 200) -> None:
        self._lock = threading.Lock()
        self._events: Deque[LLMMetricEvent] = deque(maxlen=max_events)

    def record(
        self,
        *,
        provider: str,
        model: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = prompt_tokens + completion_tokens
        err = (error or "").strip()
        rate_limited = ("429" in err) or ("rate limit" in err.lower())

        event = LLMMetricEvent(
            timestamp=time.time(),
            provider=provider,
            model=model,
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
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
            row["latency_ms_avg"] += e.latency_ms
            row["latency_ms_max"] = max(row["latency_ms_max"], e.latency_ms)

            total_failures += 0 if e.success else 1
            total_rate_limited += 1 if e.rate_limited else 0

        for row in by_provider.values():
            if row["calls"]:
                row["latency_ms_avg"] = round(row["latency_ms_avg"] / row["calls"], 2)
            row["latency_ms_max"] = round(row["latency_ms_max"], 2)

        return {
            "window_events": total_calls,
            "totals": {
                "calls": total_calls,
                "failures": total_failures,
                "rate_limited": total_rate_limited,
                "prompt_tokens": sum(e.prompt_tokens for e in events),
                "completion_tokens": sum(e.completion_tokens for e in events),
                "total_tokens": sum(e.total_tokens for e in events),
            },
            "by_provider": by_provider,
            "recent": [asdict(e) for e in events[-20:]],
        }


_COLLECTOR = LLMMetricsCollector()


def get_llm_metrics_collector() -> LLMMetricsCollector:
    return _COLLECTOR