"""Ajan delegasyon/step süresi ve sayaç metrikleri (Prometheus-uyumlu).

Bu modül supervisor._delegate() ve _route_p2p() çağrılarından üretilen
latency/count verilerini process-içi saklar; /metrics/llm/prometheus
uç noktası tarafından Prometheus formatında döndürülür.
"""

from __future__ import annotations

import math
import threading

# ---------------------------------------------------------------------------
# Histogram bucket sınırları (saniye cinsinden)
# ---------------------------------------------------------------------------
_BUCKETS: list[float] = [0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, math.inf]


class _DelegationHistogram:
    """Tek bir etiket kombinasyonu için histogram."""

    __slots__ = ("_counts", "_sum", "_total", "_lock")

    def __init__(self) -> None:
        self._counts: list[int] = [0] * len(_BUCKETS)
        self._sum: float = 0.0
        self._total: int = 0
        self._lock = threading.Lock()

    def observe(self, duration_s: float) -> None:
        with self._lock:
            self._sum += duration_s
            self._total += 1
            for i, bound in enumerate(_BUCKETS):
                if duration_s <= bound:
                    self._counts[i] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counts": list(self._counts),
                "sum": self._sum,
                "count": self._total,
            }


class AgentMetricsCollector:
    """Thread-safe ajan delegasyon ve step metrik toplayıcısı."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key: (receiver, intent, status) → _DelegationHistogram
        self._histograms: dict[tuple, _DelegationHistogram] = {}
        # key: (receiver, intent, status) → int
        self._counters: dict[tuple, int] = {}
        # key: (agent, step, target, status) → _DelegationHistogram
        self._step_histograms: dict[tuple, _DelegationHistogram] = {}
        # key: (agent, step, target, status) → int
        self._step_counters: dict[tuple, int] = {}

    def record(self, receiver: str, intent: str, status: str, duration_s: float) -> None:
        """Delegasyon sonucunu kaydet."""
        key = (receiver, intent, status)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = _DelegationHistogram()
            if key not in self._counters:
                self._counters[key] = 0
            self._counters[key] += 1
        # histogram kendi kilidi var
        self._histograms[key].observe(duration_s)

    def record_step(
        self, agent: str, step: str, target: str, status: str, duration_s: float
    ) -> None:
        """Ajan içindeki tekil karar/tool adımını kaydet."""
        key = (agent, step, target, status)
        with self._lock:
            if key not in self._step_histograms:
                self._step_histograms[key] = _DelegationHistogram()
            if key not in self._step_counters:
                self._step_counters[key] = 0
            self._step_counters[key] += 1
        self._step_histograms[key].observe(duration_s)

    def render_prometheus(self) -> str:
        """Prometheus metin formatında metrik çıktısı üret."""
        lines: list[str] = []

        # --- sidar_agent_delegation_duration_seconds (histogram) ---
        lines.append(
            "# HELP sidar_agent_delegation_duration_seconds Ajan delegasyon süresi (saniye)"
        )
        lines.append("# TYPE sidar_agent_delegation_duration_seconds histogram")
        with self._lock:
            histogram_items = list(self._histograms.items())

        for (receiver, intent, status), hist in histogram_items:
            snap = hist.snapshot()
            labels = f'receiver="{receiver}",intent="{intent}",status="{status}"'
            for i, bound in enumerate(_BUCKETS):
                le = "+Inf" if math.isinf(bound) else str(bound)
                lines.append(
                    f'sidar_agent_delegation_duration_seconds_bucket{{{labels},le="{le}"}} {snap["counts"][i]}'
                )
            lines.append(
                f"sidar_agent_delegation_duration_seconds_sum{{{labels}}} {snap['sum']:.6f}"
            )
            lines.append(
                f"sidar_agent_delegation_duration_seconds_count{{{labels}}} {snap['count']}"
            )

        # --- sidar_agent_delegation_total (counter) ---
        lines.append("# HELP sidar_agent_delegation_total Toplam delegasyon sayısı")
        lines.append("# TYPE sidar_agent_delegation_total counter")
        with self._lock:
            counter_items = list(self._counters.items())

        for (receiver, intent, status), count in counter_items:
            labels = f'receiver="{receiver}",intent="{intent}",status="{status}"'
            lines.append(f"sidar_agent_delegation_total{{{labels}}} {count}")

        # --- sidar_agent_step_duration_seconds (histogram) ---
        lines.append(
            "# HELP sidar_agent_step_duration_seconds Ajan içi karar/tool adımı süresi (saniye)"
        )
        lines.append("# TYPE sidar_agent_step_duration_seconds histogram")
        with self._lock:
            step_histogram_items = list(self._step_histograms.items())

        for (agent, step, target, status), hist in step_histogram_items:
            snap = hist.snapshot()
            labels = f'agent="{agent}",step="{step}",target="{target}",status="{status}"'
            for i, bound in enumerate(_BUCKETS):
                le = "+Inf" if math.isinf(bound) else str(bound)
                lines.append(
                    f'sidar_agent_step_duration_seconds_bucket{{{labels},le="{le}"}} {snap["counts"][i]}'
                )
            lines.append(f"sidar_agent_step_duration_seconds_sum{{{labels}}} {snap['sum']:.6f}")
            lines.append(f"sidar_agent_step_duration_seconds_count{{{labels}}} {snap['count']}")

        # --- sidar_agent_step_total (counter) ---
        lines.append("# HELP sidar_agent_step_total Toplam ajan içi step sayısı")
        lines.append("# TYPE sidar_agent_step_total counter")
        with self._lock:
            step_counter_items = list(self._step_counters.items())

        for (agent, step, target, status), count in step_counter_items:
            labels = f'agent="{agent}",step="{step}",target="{target}",status="{status}"'
            lines.append(f"sidar_agent_step_total{{{labels}}} {count}")

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Singleton erişimi
# ---------------------------------------------------------------------------
_COLLECTOR: AgentMetricsCollector | None = None
_COLLECTOR_LOCK = threading.Lock()


def get_agent_metrics_collector() -> AgentMetricsCollector:
    global _COLLECTOR
    if _COLLECTOR is None:
        with _COLLECTOR_LOCK:
            if _COLLECTOR is None:
                _COLLECTOR = AgentMetricsCollector()
    return _COLLECTOR
