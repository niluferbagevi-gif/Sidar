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

    def record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def record_skip(self) -> None:
        with self._lock:
            self.skips += 1

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "hits": self.hits,
                "misses": self.misses,
                "skips": self.skips,
                "total_lookups": total,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
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


def get_cache_metrics() -> Dict[str, object]:
    """Semantic cache hit/miss istatistiklerini döner."""
    return _cache_metrics.snapshot()