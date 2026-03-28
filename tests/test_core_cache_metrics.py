"""
core/cache_metrics.py için birim testleri.
_CacheMetrics ve modül seviyesi sarmalayıcı fonksiyonları kapsar.
"""
from __future__ import annotations

import sys
import threading
import importlib


def _get_cache_metrics():
    """Her test için temiz bir modül yükler; Prometheus yoksa sorun olmaz."""
    if "core.cache_metrics" in sys.modules:
        del sys.modules["core.cache_metrics"]
    # prometheus_client'ı stub'la ki test izole olsun
    import types
    prom_stub = types.ModuleType("prometheus_client")
    sys.modules.setdefault("prometheus_client", prom_stub)
    import core.cache_metrics as cm
    # Modül seviyesi sayaçları sıfırla
    cm._cache_metrics = cm._CacheMetrics()
    cm._prometheus_metric_cache.clear()
    return cm


# ══════════════════════════════════════════════════════════════
# _CacheMetrics sınıf testleri
# ══════════════════════════════════════════════════════════════

class TestCacheMetricsInit:
    def test_initial_values_are_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        snap = m.snapshot()
        assert snap["hits"] == 0
        assert snap["misses"] == 0
        assert snap["skips"] == 0
        assert snap["evictions"] == 0
        assert snap["redis_errors"] == 0
        assert snap["items"] == 0
        assert snap["redis_latency_ms"] == 0.0

    def test_initial_hit_rate_is_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        assert m.snapshot()["hit_rate"] == 0.0

    def test_initial_total_lookups_is_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        assert m.snapshot()["total_lookups"] == 0


class TestCacheMetricsRecordHit:
    def test_record_hit_increments(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_hit()
        assert m.snapshot()["hits"] == 1

    def test_multiple_hits(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        for _ in range(5):
            m.record_hit()
        assert m.snapshot()["hits"] == 5

    def test_hit_rate_with_only_hits(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_hit()
        m.record_hit()
        snap = m.snapshot()
        assert snap["hit_rate"] == 1.0
        assert snap["total_lookups"] == 2


class TestCacheMetricsRecordMiss:
    def test_record_miss_increments(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_miss()
        assert m.snapshot()["misses"] == 1

    def test_hit_rate_with_mixed(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_hit()
        m.record_miss()
        snap = m.snapshot()
        assert snap["hit_rate"] == 0.5
        assert snap["total_lookups"] == 2


class TestCacheMetricsRecordSkip:
    def test_record_skip_increments(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_skip()
        assert m.snapshot()["skips"] == 1

    def test_skip_does_not_affect_total_lookups(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_skip()
        assert m.snapshot()["total_lookups"] == 0


class TestCacheMetricsEviction:
    def test_record_eviction_default_count(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_eviction()
        assert m.snapshot()["evictions"] == 1

    def test_record_eviction_custom_count(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_eviction(5)
        assert m.snapshot()["evictions"] == 5

    def test_negative_eviction_ignored(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_eviction(-3)
        assert m.snapshot()["evictions"] == 0

    def test_none_eviction_safe(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_eviction(None)
        assert m.snapshot()["evictions"] == 0


class TestCacheMetricsRedisError:
    def test_record_redis_error_default(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_redis_error()
        assert m.snapshot()["redis_errors"] == 1

    def test_record_redis_error_count(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.record_redis_error(3)
        assert m.snapshot()["redis_errors"] == 3


class TestCacheMetricsSetItems:
    def test_set_items_positive(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.set_items(42)
        assert m.snapshot()["items"] == 42

    def test_set_items_negative_becomes_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.set_items(-10)
        assert m.snapshot()["items"] == 0

    def test_set_items_none_safe(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.set_items(None)
        assert m.snapshot()["items"] == 0


class TestCacheMetricsRedisLatency:
    def test_observe_latency_stored(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.observe_redis_latency(12.5)
        assert m.snapshot()["redis_latency_ms"] == 12.5

    def test_negative_latency_becomes_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.observe_redis_latency(-5.0)
        assert m.snapshot()["redis_latency_ms"] == 0.0

    def test_none_latency_becomes_zero(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.observe_redis_latency(None)
        assert m.snapshot()["redis_latency_ms"] == 0.0

    def test_latency_rounded_to_4_decimals(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        m.observe_redis_latency(3.141592653)
        snap = m.snapshot()["redis_latency_ms"]
        assert snap == round(3.141592653, 4)


class TestCacheMetricsThreadSafety:
    def test_concurrent_hits_correct_count(self):
        cm = _get_cache_metrics()
        m = cm._CacheMetrics()
        threads = [threading.Thread(target=m.record_hit) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert m.snapshot()["hits"] == 50


# ══════════════════════════════════════════════════════════════
# Modül seviyesi yardımcı fonksiyonlar
# ══════════════════════════════════════════════════════════════

class TestModuleLevelFunctions:
    def test_record_cache_hit_increments_module_counter(self):
        cm = _get_cache_metrics()
        cm.record_cache_hit()
        assert cm._cache_metrics.hits == 1

    def test_record_cache_miss_increments_module_counter(self):
        cm = _get_cache_metrics()
        cm.record_cache_miss()
        assert cm._cache_metrics.misses == 1

    def test_record_cache_skip_increments_module_counter(self):
        cm = _get_cache_metrics()
        cm.record_cache_skip()
        assert cm._cache_metrics.skips == 1

    def test_record_cache_eviction_increments(self):
        cm = _get_cache_metrics()
        cm.record_cache_eviction(2)
        assert cm._cache_metrics.evictions == 2

    def test_record_cache_redis_error_increments(self):
        cm = _get_cache_metrics()
        cm.record_cache_redis_error(3)
        assert cm._cache_metrics.redis_errors == 3

    def test_set_cache_items_updates(self):
        cm = _get_cache_metrics()
        cm.set_cache_items(99)
        assert cm._cache_metrics.items == 99

    def test_observe_cache_redis_latency_updates(self):
        cm = _get_cache_metrics()
        cm.observe_cache_redis_latency(7.5)
        assert cm._cache_metrics.redis_latency_ms == 7.5

    def test_get_cache_metrics_returns_snapshot_dict(self):
        cm = _get_cache_metrics()
        cm.record_cache_hit()
        cm.record_cache_miss()
        result = cm.get_cache_metrics()
        assert isinstance(result, dict)
        assert result["hits"] == 1
        assert result["misses"] == 1
        assert result["hit_rate"] == 0.5
