"""Ajan delegasyon/step süresi ve sayaç metrikleri (Prometheus-uyumlu).

Bu modül supervisor._delegate() ve _route_p2p() çağrılarından üretilen
latency/count verilerini process-içi saklar; /metrics/llm/prometheus
uç noktası tarafından Prometheus formatında döndürülür.
"""

from __future__ import annotations

import math
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Histogram bucket sınırları (saniye cinsinden)
# ---------------------------------------------------------------------------
_BUCKETS: list[float] = [0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, math.inf]
_AUTH_HASH_BUCKETS: list[float] = [
    0.025,
    0.05,
    0.075,
    0.1,
    0.12,
    0.15,
    0.2,
    0.3,
    0.5,
    1.0,
    math.inf,
]


class _DelegationHistogram:
    """Tek bir etiket kombinasyonu için histogram."""

    __slots__ = ("_buckets", "_counts", "_sum", "_total", "_lock")

    def __init__(self, buckets: list[float] | None = None) -> None:
        self._buckets = buckets or _BUCKETS
        self._counts: list[int] = [0] * len(self._buckets)
        self._sum: float = 0.0
        self._total: int = 0
        self._lock = threading.Lock()

    def observe(self, duration_s: float) -> None:
        with self._lock:
            self._sum += duration_s
            self._total += 1
            for i, bound in enumerate(self._buckets):
                if duration_s <= bound:
                    self._counts[i] += 1

    def snapshot(self) -> dict[str, Any]:
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
        self._histograms: dict[tuple[str, str, str], _DelegationHistogram] = {}
        # key: (receiver, intent, status) → int
        self._counters: dict[tuple[str, str, str], int] = {}
        # key: (agent, step, target, status) → _DelegationHistogram
        self._step_histograms: dict[tuple[str, str, str, str], _DelegationHistogram] = {}
        # key: (agent, step, target, status) → int
        self._step_counters: dict[tuple[str, str, str, str], int] = {}
        # key: (operation, status) → _DelegationHistogram
        self._auth_hash_histograms: dict[tuple[str, str], _DelegationHistogram] = {}
        # key: (operation, status) → int
        self._auth_hash_counters: dict[tuple[str, str], int] = {}
        # key: (operation, status, slo_ms) → int
        self._auth_hash_slo_warnings: dict[tuple[str, str, int], int] = {}

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

    def record_auth_hash_latency(
        self, operation: str, status: str, duration_s: float, *, slo_ms: int = 120
    ) -> None:
        """Parola hash/verify CPU maliyetini SLO uyarısıyla kaydet."""
        normalized_operation = str(operation or "unknown").strip().lower() or "unknown"
        normalized_status = str(status or "unknown").strip().lower() or "unknown"
        key = (normalized_operation, normalized_status)
        with self._lock:
            if key not in self._auth_hash_histograms:
                self._auth_hash_histograms[key] = _DelegationHistogram(_AUTH_HASH_BUCKETS)
            if key not in self._auth_hash_counters:
                self._auth_hash_counters[key] = 0
            self._auth_hash_counters[key] += 1
            if duration_s * 1000.0 > float(slo_ms):
                warning_key = (normalized_operation, normalized_status, int(slo_ms))
                self._auth_hash_slo_warnings[warning_key] = (
                    self._auth_hash_slo_warnings.get(warning_key, 0) + 1
                )
        self._auth_hash_histograms[key].observe(duration_s)

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

        # --- sidar_auth_password_hash_duration_seconds (histogram) ---
        lines.append(
            "# HELP sidar_auth_password_hash_duration_seconds Parola hash/verify süresi (saniye)"
        )
        lines.append("# TYPE sidar_auth_password_hash_duration_seconds histogram")
        with self._lock:
            auth_hash_histogram_items = list(self._auth_hash_histograms.items())

        for (operation, status), hist in auth_hash_histogram_items:
            snap = hist.snapshot()
            labels = f'operation="{operation}",status="{status}"'
            for i, bound in enumerate(_AUTH_HASH_BUCKETS):
                le = "+Inf" if math.isinf(bound) else str(bound)
                lines.append(
                    f'sidar_auth_password_hash_duration_seconds_bucket{{{labels},le="{le}"}} {snap["counts"][i]}'
                )
            lines.append(
                f"sidar_auth_password_hash_duration_seconds_sum{{{labels}}} {snap['sum']:.6f}"
            )
            lines.append(
                f"sidar_auth_password_hash_duration_seconds_count{{{labels}}} {snap['count']}"
            )

        lines.append("# HELP sidar_auth_password_hash_total Toplam parola hash/verify denemesi")
        lines.append("# TYPE sidar_auth_password_hash_total counter")
        with self._lock:
            auth_hash_counter_items = list(self._auth_hash_counters.items())
            auth_hash_slo_warning_items = list(self._auth_hash_slo_warnings.items())

        for (operation, status), count in auth_hash_counter_items:
            labels = f'operation="{operation}",status="{status}"'
            lines.append(f"sidar_auth_password_hash_total{{{labels}}} {count}")

        lines.append(
            "# HELP sidar_auth_password_hash_slo_warnings_total Parola hash/verify süresi SLO eşiğini aşan ölçüm sayısı"
        )
        lines.append("# TYPE sidar_auth_password_hash_slo_warnings_total counter")
        for (operation, status, slo_ms), count in auth_hash_slo_warning_items:
            labels = f'operation="{operation}",status="{status}",slo_ms="{slo_ms}"'
            lines.append(f"sidar_auth_password_hash_slo_warnings_total{{{labels}}} {count}")

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
