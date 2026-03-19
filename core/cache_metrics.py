"""Semantic Cache Hit/Miss Sayaçları (thread-safe, process-içi, bağımlılıksız).

Bu modül kasıtlı olarak hafif tutulmuştur; llm_client'dan bağımsız
import edilebilir ve test edilebilir.
"""
from __future__ import annotations

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
                "items": self.items,
                "redis_latency_ms": self.redis_latency_ms,
            }


_cache_metrics = _CacheMetrics()


def record_cache_hit() -> None:
    """Semantic cache için hit sayacını artırır."""
    _cache_metrics.record_hit()


def record_cache_miss() -> None:
    """Semantic cache için miss sayacını artırır."""
    _cache_metrics.record_miss()


def record_cache_skip() -> None:
    """Semantic cache için skip sayacını artırır."""
    _cache_metrics.record_skip()


def record_cache_eviction(count: int = 1) -> None:
    """Semantic cache LRU eviction sayacını artırır."""
    _cache_metrics.record_eviction(count=count)


def record_cache_redis_error(count: int = 1) -> None:
    """Semantic cache Redis hata sayacını artırır."""
    _cache_metrics.record_redis_error(count=count)


def set_cache_items(count: int) -> None:
    """Semantic cache içindeki aktif öğe sayısını günceller."""
    _cache_metrics.set_items(count=count)


def observe_cache_redis_latency(latency_ms: float) -> None:
    """Semantic cache Redis erişiminin son gecikme değerini kaydeder."""
    _cache_metrics.observe_redis_latency(latency_ms=latency_ms)


def get_cache_metrics() -> Dict[str, object]:
    """Semantic cache hit/miss istatistiklerini döner."""
    return _cache_metrics.snapshot()
