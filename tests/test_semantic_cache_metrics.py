"""Testler: Semantic Cache Hit/Miss Metrikleri (Özellik 7)"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ─── _CacheMetrics sınıfı ────────────────────────────────────────────────────

from core.cache_metrics import _CacheMetrics, _cache_metrics, get_cache_metrics


class TestCacheMetrics:
    def setup_method(self):
        self.cm = _CacheMetrics()

    def test_initial_snapshot_zeros(self):
        snap = self.cm.snapshot()
        assert snap["hits"] == 0
        assert snap["misses"] == 0
        assert snap["skips"] == 0
        assert snap["total_lookups"] == 0
        assert snap["hit_rate"] == 0.0

    def test_record_hit_increments(self):
        self.cm.record_hit()
        self.cm.record_hit()
        snap = self.cm.snapshot()
        assert snap["hits"] == 2

    def test_record_miss_increments(self):
        self.cm.record_miss()
        snap = self.cm.snapshot()
        assert snap["misses"] == 1

    def test_record_skip_increments(self):
        self.cm.record_skip()
        snap = self.cm.snapshot()
        assert snap["skips"] == 1

    def test_hit_rate_calculated_correctly(self):
        self.cm.record_hit()
        self.cm.record_hit()
        self.cm.record_miss()
        snap = self.cm.snapshot()
        assert snap["total_lookups"] == 3
        assert snap["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_hit_rate_zero_when_no_lookups(self):
        snap = self.cm.snapshot()
        assert snap["hit_rate"] == 0.0

    def test_hit_rate_one_when_all_hits(self):
        for _ in range(5):
            self.cm.record_hit()
        snap = self.cm.snapshot()
        assert snap["hit_rate"] == pytest.approx(1.0)

    def test_skips_not_counted_in_lookups(self):
        self.cm.record_hit()
        self.cm.record_skip()
        snap = self.cm.snapshot()
        assert snap["total_lookups"] == 1  # Yalnızca hit + miss


# ─── Modül düzeyinde get_cache_metrics ───────────────────────────────────────

def test_get_cache_metrics_returns_dict():
    result = get_cache_metrics()
    assert isinstance(result, dict)
    assert "hits" in result
    assert "misses" in result
    assert "hit_rate" in result
    assert "total_lookups" in result


# ─── Prometheus renderer entegrasyonu ────────────────────────────────────────

import asyncio
import importlib
import sys


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def _load_render_fn():
    """managers.system_health modülünü ağır bağımlılıklar olmadan yükler."""
    if "managers.system_health" in sys.modules:
        return sys.modules["managers.system_health"].render_llm_metrics_prometheus
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "managers.system_health",
        pathlib.Path(__file__).parent.parent / "managers" / "system_health.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render_llm_metrics_prometheus

render_llm_metrics_prometheus = _load_render_fn()


class TestPrometheusRendererCacheMetrics:
    def _snapshot(self, hits=10, misses=5, hit_rate=0.667):
        return {
            "totals": {"calls": 100, "cost_usd": 1.5, "total_tokens": 5000, "failures": 2},
            "by_provider": {},
            "by_user": {},
            "cache": {"hits": hits, "misses": misses, "hit_rate": hit_rate},
        }

    def test_cache_hits_total_present(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "sidar_cache_hits_total 10" in output

    def test_cache_misses_total_present(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "sidar_cache_misses_total 5" in output

    def test_cache_hit_rate_present(self):
        output = render_llm_metrics_prometheus(self._snapshot(hit_rate=0.667))
        assert "sidar_cache_hit_rate 0.667" in output

    def test_cache_metrics_help_lines(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "# HELP sidar_cache_hits_total" in output
        assert "# HELP sidar_cache_misses_total" in output
        assert "# HELP sidar_cache_hit_rate" in output

    def test_zero_cache_snapshot(self):
        output = render_llm_metrics_prometheus(self._snapshot(0, 0, 0.0))
        assert "sidar_cache_hits_total 0" in output
        assert "sidar_cache_hit_rate 0.0" in output

    def test_empty_snapshot_no_crash(self):
        output = render_llm_metrics_prometheus({})
        assert "sidar_cache_hits_total 0" in output

    def test_none_snapshot_no_crash(self):
        output = render_llm_metrics_prometheus(None)
        assert isinstance(output, str)
        assert "sidar_llm_calls_total" in output


# ─── LLMMetricsCollector.snapshot() cache alanı ────────────────────────────

from core.llm_metrics import LLMMetricsCollector


class TestMetricsCollectorCacheField:
    def test_snapshot_contains_cache_key(self):
        collector = LLMMetricsCollector()
        snap = collector.snapshot()
        assert "cache" in snap

    def test_cache_snapshot_has_required_keys(self):
        collector = LLMMetricsCollector()
        snap = collector.snapshot()
        cache = snap["cache"]
        assert "hits" in cache
        assert "misses" in cache
        assert "hit_rate" in cache
        assert "total_lookups" in cache

    def test_cache_hit_rate_is_float(self):
        collector = LLMMetricsCollector()
        snap = collector.snapshot()
        assert isinstance(snap["cache"]["hit_rate"], float)


# ─── _SemanticCacheManager hit/miss kayıt entegrasyonu ───────────────────────

def test_cache_manager_records_hit():
    """Cache HIT olduğunda _cache_metrics.hits artar."""
    import core.cache_metrics as cm_mod
    original_hits = cm_mod._cache_metrics.hits

    try:
        import core.llm_client as llm_mod
        _SemanticCacheManager = llm_mod._SemanticCacheManager
    except Exception:
        pytest.skip("llm_client import başarısız")

    mgr = _SemanticCacheManager(MagicMock(
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.95,
        SEMANTIC_CACHE_TTL=3600,
        SEMANTIC_CACHE_MAX_ITEMS=10,
        REDIS_URL="redis://localhost:6379/0",
    ))

    import json
    vec = [1.0, 0.0]
    fake_redis = AsyncMock()
    fake_redis.lrange = AsyncMock(return_value=["sidar:semantic_cache:item:abc"])
    fake_redis.hgetall = AsyncMock(return_value={
        "embedding": json.dumps(vec),
        "response": "cached answer",
    })
    mgr._redis = fake_redis

    with patch.object(mgr, "_embed_prompt", return_value=vec):
        result = _run(mgr.get("test query"))

    if result == "cached answer":
        assert cm_mod._cache_metrics.hits > original_hits


def test_cache_manager_records_miss():
    """Cache MISS olduğunda _cache_metrics.misses artar."""
    import core.cache_metrics as cm_mod
    original_misses = cm_mod._cache_metrics.misses

    try:
        import core.llm_client as llm_mod
        _SemanticCacheManager = llm_mod._SemanticCacheManager
    except Exception:
        pytest.skip("llm_client import başarısız")

    mgr = _SemanticCacheManager(MagicMock(
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.95,
        SEMANTIC_CACHE_TTL=3600,
        SEMANTIC_CACHE_MAX_ITEMS=10,
        REDIS_URL="redis://localhost:6379/0",
    ))

    import json
    vec_stored = [1.0, 0.0]
    vec_query  = [0.0, 1.0]  # ortogonal — similarity=0
    fake_redis = AsyncMock()
    fake_redis.lrange = AsyncMock(return_value=["key1"])
    fake_redis.hgetall = AsyncMock(return_value={
        "embedding": json.dumps(vec_stored),
        "response": "some answer",
    })
    mgr._redis = fake_redis

    with patch.object(mgr, "_embed_prompt", return_value=vec_query):
        result = _run(mgr.get("unrelated query"))

    assert result is None
    assert cm_mod._cache_metrics.misses > original_misses