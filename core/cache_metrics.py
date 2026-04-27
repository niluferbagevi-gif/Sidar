"""Semantic Cache Hit/Miss Sayaçları (thread-safe, process-içi, opsiyonel Prometheus).

Bu modül kasıtlı olarak hafif tutulmuştur; llm_client'dan bağımsız
import edilebilir ve test edilebilir.
"""
from __future__ import annotations

import importlib
import threading
from typing import Dict


class _CacheMetrics:
    """Cache hit/miss/skip sayaçlarını thread-safe tutar."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.hits: int = 0
        self.misses: int = 0
        self.skips: int = 0  # cache devre dışı / stream
        self.evictions: int = 0
        self.redis_errors: int = 0
        self.circuit_open_bypasses: int = 0
        self.items: int = 0
        self.redis_latency_ms: float = 0.0

    def record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def record_skip(self) -> None:
        with self._lock:
            self.skips += 1

    def record_eviction(self, count: int = 1) -> None:
        with self._lock:
            self.evictions += max(0, int(count or 0))

    def record_redis_error(self, count: int = 1) -> None:
        with self._lock:
            self.redis_errors += max(0, int(count or 0))

    def record_circuit_open_bypass(self, count: int = 1) -> None:
        with self._lock:
            self.circuit_open_bypasses += max(0, int(count or 0))

    def set_items(self, count: int) -> None:
        with self._lock:
            self.items = max(0, int(count or 0))

    def observe_redis_latency(self, latency_ms: float) -> None:
        with self._lock:
            self.redis_latency_ms = max(0.0, round(float(latency_ms or 0.0), 4))

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "hits": self.hits,
                "misses": self.misses,
                "skips": self.skips,
                "total_lookups": total,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "evictions": self.evictions,
                "redis_errors": self.redis_errors,
                "circuit_open_bypasses": self.circuit_open_bypasses,
                "items": self.items,
                "redis_latency_ms": self.redis_latency_ms,
            }


_cache_metrics = _CacheMetrics()
_prometheus_metric_lock = threading.Lock()
_prometheus_metric_cache: Dict[str, object] = {}


def _get_prometheus_metric(metric_name: str, description: str, metric_type: str) -> object | None:
    """Varsa prometheus_client collector'ını döndürür; yoksa None."""
    cached = _prometheus_metric_cache.get(metric_name)
    if cached is not None:
        return cached

    with _prometheus_metric_lock:
        cached = _prometheus_metric_cache.get(metric_name)
        if cached is not None:
            return cached
        try:
            prometheus_client = importlib.import_module("prometheus_client")
        except Exception:
            return None

        registry = getattr(prometheus_client, "REGISTRY", None)
        existing = getattr(registry, "_names_to_collectors", {}).get(metric_name) if registry else None
        if existing is not None:
            _prometheus_metric_cache[metric_name] = existing
            return existing

        factory_name = "Counter" if metric_type == "counter" else "Gauge"
        factory = getattr(prometheus_client, factory_name, None)
        if factory is None:
            return None

        metric = factory(metric_name, description)
        _prometheus_metric_cache[metric_name] = metric
        return metric


def _inc_prometheus_counter(metric_name: str, description: str, count: int = 1) -> None:
    if int(count or 0) <= 0:
        return
    counter = _get_prometheus_metric(metric_name, description, "counter")
    if counter is not None and hasattr(counter, "inc"):
        counter.inc(int(count or 0))


def _set_prometheus_gauge(metric_name: str, description: str, value: float) -> None:
    gauge = _get_prometheus_metric(metric_name, description, "gauge")
    if gauge is not None and hasattr(gauge, "set"):
        gauge.set(value)


def record_cache_hit() -> None:
    """Semantic cache için hit sayacını artırır."""
    _cache_metrics.record_hit()
    _inc_prometheus_counter(
        "sidar_semantic_cache_hits_total",
        "Semantic cache hit count",
    )


def record_cache_miss() -> None:
    """Semantic cache için miss sayacını artırır."""
    _cache_metrics.record_miss()
    _inc_prometheus_counter(
        "sidar_semantic_cache_misses_total",
        "Semantic cache miss count",
    )


def record_cache_skip() -> None:
    """Semantic cache için skip sayacını artırır."""
    _cache_metrics.record_skip()
    _inc_prometheus_counter(
        "sidar_semantic_cache_skips_total",
        "Semantic cache skip count",
    )


def record_cache_eviction(count: int = 1) -> None:
    """Semantic cache LRU eviction sayacını artırır."""
    _cache_metrics.record_eviction(count=count)
    _inc_prometheus_counter(
        "sidar_semantic_cache_evictions_total",
        "Semantic cache eviction count",
        count=count,
    )


def record_cache_redis_error(count: int = 1) -> None:
    """Semantic cache Redis hata sayacını artırır."""
    _cache_metrics.record_redis_error(count=count)
    _inc_prometheus_counter(
        "sidar_semantic_cache_redis_errors_total",
        "Semantic cache Redis error count",
        count=count,
    )

def record_cache_circuit_open_bypass(count: int = 1) -> None:
    """Semantic cache circuit-open bypass sayacını artırır."""
    _cache_metrics.record_circuit_open_bypass(count=count)
    _inc_prometheus_counter(
        "sidar_semantic_cache_circuit_open_total",
        "Semantic cache circuit-open bypass count",
        count=count,
    )


def set_cache_items(count: int) -> None:
    """Semantic cache içindeki aktif öğe sayısını günceller."""
    _cache_metrics.set_items(count=count)
    _set_prometheus_gauge(
        "sidar_semantic_cache_items",
        "Current semantic cache item count",
        max(0, int(count or 0)),
    )


def observe_cache_redis_latency(latency_ms: float) -> None:
    """Semantic cache Redis erişiminin son gecikme değerini kaydeder."""
    _cache_metrics.observe_redis_latency(latency_ms=latency_ms)
    _set_prometheus_gauge(
        "sidar_semantic_cache_redis_latency_ms",
        "Latest semantic cache Redis latency in milliseconds",
        max(0.0, float(latency_ms or 0.0)),
    )


def get_cache_metrics() -> Dict[str, object]:
    """Semantic cache hit/miss istatistiklerini döner."""
    return _cache_metrics.snapshot()
