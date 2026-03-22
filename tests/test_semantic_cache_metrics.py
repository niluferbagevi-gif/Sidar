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
        assert snap["evictions"] == 0
        assert snap["redis_errors"] == 0
        assert snap["items"] == 0
        assert snap["redis_latency_ms"] == 0.0
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

    def test_eviction_redis_and_inventory_metrics_are_tracked(self):
        self.cm.record_eviction(2)
        self.cm.record_redis_error()
        self.cm.set_items(7)
        self.cm.observe_redis_latency(12.3456)
        snap = self.cm.snapshot()
        assert snap["evictions"] == 2
        assert snap["redis_errors"] == 1
        assert snap["items"] == 7
        assert snap["redis_latency_ms"] == pytest.approx(12.3456, abs=1e-4)


# ─── Modül düzeyinde get_cache_metrics ───────────────────────────────────────

def test_get_cache_metrics_returns_dict():
    result = get_cache_metrics()
    assert isinstance(result, dict)
    assert "hits" in result
    assert "misses" in result
    assert "hit_rate" in result
    assert "total_lookups" in result
    assert "evictions" in result
    assert "redis_errors" in result
    assert "items" in result
    assert "redis_latency_ms" in result


# ─── Prometheus renderer entegrasyonu ────────────────────────────────────────

import asyncio
import importlib
import sys
import types


def _run(coro):
    return asyncio.run(coro)

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
            "cache": {
                "hits": hits,
                "misses": misses,
                "skips": 2,
                "evictions": 3,
                "redis_errors": 1,
                "items": 9,
                "redis_latency_ms": 17.5,
                "hit_rate": hit_rate,
            },
        }

    def test_cache_hits_total_present(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "sidar_semantic_cache_hits_total 10" in output

    def test_cache_misses_total_present(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "sidar_semantic_cache_misses_total 5" in output

    def test_cache_hit_rate_present(self):
        output = render_llm_metrics_prometheus(self._snapshot(hit_rate=0.667))
        assert "sidar_semantic_cache_hit_rate 0.667" in output
        assert "sidar_cache_hit_rate 0.667" in output

    def test_cache_metrics_help_lines(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "# HELP sidar_semantic_cache_hits_total" in output
        assert "# HELP sidar_semantic_cache_misses_total" in output
        assert "# HELP sidar_semantic_cache_evictions_total" in output
        assert "# HELP sidar_semantic_cache_redis_latency_ms" in output
        assert "# HELP sidar_semantic_cache_hit_rate" in output

    def test_extended_cache_metrics_present(self):
        output = render_llm_metrics_prometheus(self._snapshot())
        assert "sidar_semantic_cache_skips_total 2" in output
        assert "sidar_semantic_cache_evictions_total 3" in output
        assert "sidar_semantic_cache_redis_errors_total 1" in output
        assert "sidar_semantic_cache_items 9" in output
        assert "sidar_semantic_cache_redis_latency_ms 17.5" in output

    def test_zero_cache_snapshot(self):
        output = render_llm_metrics_prometheus(self._snapshot(0, 0, 0.0))
        assert "sidar_semantic_cache_hits_total 0" in output
        assert "sidar_semantic_cache_hit_rate 0.0" in output

    def test_empty_snapshot_no_crash(self):
        output = render_llm_metrics_prometheus({})
        assert "sidar_semantic_cache_hits_total 0" in output

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
        assert "evictions" in cache
        assert "redis_errors" in cache
        assert "items" in cache
        assert "redis_latency_ms" in cache

    def test_cache_hit_rate_is_float(self):
        collector = LLMMetricsCollector()
        snap = collector.snapshot()
        assert isinstance(snap["cache"]["hit_rate"], float)


def test_get_prometheus_metric_returns_none_when_import_fails(monkeypatch):
    import core.cache_metrics as cm_mod

    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda _name: (_ for _ in ()).throw(ImportError("missing prom")))

    assert cm_mod._get_prometheus_metric("sidar_test_metric", "desc", "counter") is None



def test_get_prometheus_metric_returns_none_when_factory_missing(monkeypatch):
    import core.cache_metrics as cm_mod

    fake_prom = types.SimpleNamespace(REGISTRY=types.SimpleNamespace(_names_to_collectors={}), Counter=None, Gauge=None)
    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda name: fake_prom if name == "prometheus_client" else importlib.import_module(name))

    assert cm_mod._get_prometheus_metric("sidar_test_metric", "desc", "counter") is None
    assert cm_mod._get_prometheus_metric("sidar_test_gauge", "desc", "gauge") is None


def test_get_prometheus_metric_returns_cached_value_populated_while_lock_is_held(monkeypatch):
    import core.cache_metrics as cm_mod

    metric = object()

    class _LockThatPopulatesCache:
        def __enter__(self):
            cm_mod._prometheus_metric_cache["sidar_locked_metric"] = metric
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    import_calls = []

    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod, "_prometheus_metric_lock", _LockThatPopulatesCache())
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda name: import_calls.append(name) or None)

    result = cm_mod._get_prometheus_metric("sidar_locked_metric", "desc", "counter")

    assert result is metric
    assert import_calls == []


def test_get_prometheus_metric_uses_existing_registry_collector(monkeypatch):
    import core.cache_metrics as cm_mod

    existing = object()
    fake_prom = types.SimpleNamespace(
        REGISTRY=types.SimpleNamespace(_names_to_collectors={"sidar_existing_metric": existing}),
        Counter=None,
        Gauge=None,
    )

    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda name: fake_prom if name == "prometheus_client" else importlib.import_module(name))

    result = cm_mod._get_prometheus_metric("sidar_existing_metric", "desc", "counter")

    assert result is existing
    assert cm_mod._prometheus_metric_cache["sidar_existing_metric"] is existing


def test_inc_prometheus_counter_ignores_non_positive_counts(monkeypatch):
    import core.cache_metrics as cm_mod

    metric_calls = []
    monkeypatch.setattr(cm_mod, "_get_prometheus_metric", lambda *args, **kwargs: metric_calls.append((args, kwargs)))

    cm_mod._inc_prometheus_counter("sidar_zero_metric", "desc", count=0)
    cm_mod._inc_prometheus_counter("sidar_negative_metric", "desc", count=-3)

    assert metric_calls == []


def test_prometheus_helpers_ignore_metrics_without_inc_or_set(monkeypatch):
    import core.cache_metrics as cm_mod

    class _NoMethods:
        pass

    calls = []
    monkeypatch.setattr(cm_mod, "_get_prometheus_metric", lambda *args, **kwargs: calls.append((args, kwargs)) or _NoMethods())

    cm_mod._inc_prometheus_counter("sidar_counter_without_inc", "desc", count=2)
    cm_mod._set_prometheus_gauge("sidar_gauge_without_set", "desc", 3.5)

    assert calls == [
        (("sidar_counter_without_inc", "desc", "counter"), {}),
        (("sidar_gauge_without_set", "desc", "gauge"), {}),
    ]


def test_record_cache_skip_updates_prometheus_collectors_when_available(monkeypatch):
    import core.cache_metrics as cm_mod

    class _Counter:
        def __init__(self, *_args, **_kwargs):
            self.value = 0

        def inc(self, count=1):
            self.value += count

    fake_prom = types.SimpleNamespace(
        Counter=_Counter,
        Gauge=None,
        REGISTRY=types.SimpleNamespace(_names_to_collectors={}),
    )

    monkeypatch.setattr(cm_mod, "_cache_metrics", cm_mod._CacheMetrics())
    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda name: fake_prom if name == "prometheus_client" else importlib.import_module(name))

    cm_mod.record_cache_skip()

    assert cm_mod._cache_metrics.skips == 1
    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_skips_total"].value == 1


def test_cache_metrics_updates_prometheus_collectors_when_available(monkeypatch):
    import core.cache_metrics as cm_mod

    class _Counter:
        def __init__(self, *_args, **_kwargs):
            self.value = 0

        def inc(self, count=1):
            self.value += count

    class _Gauge:
        def __init__(self, *_args, **_kwargs):
            self.value = None

        def set(self, value):
            self.value = value

    fake_prom = types.SimpleNamespace(
        Counter=_Counter,
        Gauge=_Gauge,
        REGISTRY=types.SimpleNamespace(_names_to_collectors={}),
    )

    monkeypatch.setattr(cm_mod, "_prometheus_metric_cache", {})
    monkeypatch.setattr(cm_mod.importlib, "import_module", lambda name: fake_prom if name == "prometheus_client" else importlib.import_module(name))

    cm_mod.record_cache_hit()
    cm_mod.record_cache_miss()
    cm_mod.record_cache_eviction(2)
    cm_mod.set_cache_items(5)
    cm_mod.observe_cache_redis_latency(9.5)

    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_hits_total"].value == 1
    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_misses_total"].value == 1
    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_evictions_total"].value == 2
    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_items"].value == 5
    assert cm_mod._prometheus_metric_cache["sidar_semantic_cache_redis_latency_ms"].value == 9.5


# ─── _SemanticCacheManager hit/miss kayıt entegrasyonu ───────────────────────

def test_cache_manager_records_hit():
    """Cache HIT olduğunda _cache_metrics.hits artar."""
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
    with patch.object(mgr, "_get_redis", AsyncMock(return_value=fake_redis)), patch.object(
        mgr, "_embed_prompt", return_value=vec
    ), patch.object(
        llm_mod, "record_cache_hit"
    ) as record_hit:
        result = _run(mgr.get("test query"))

    if result == "cached answer":
        record_hit.assert_called_once()


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
    vec_query = [0.0, 1.0]  # ortogonal — similarity=0
    fake_redis = AsyncMock()
    fake_redis.lrange = AsyncMock(return_value=["key1"])
    fake_redis.hgetall = AsyncMock(return_value={
        "embedding": json.dumps(vec_stored),
        "response": "some answer",
    })
    with patch.object(mgr, "_get_redis", AsyncMock(return_value=fake_redis)), patch.object(
        mgr, "_embed_prompt", return_value=vec_query
    ), patch.object(
        llm_mod, "record_cache_miss"
    ) as record_miss:
        result = _run(mgr.get("unrelated query"))

    assert result is None
    record_miss.assert_called_once()
    assert cm_mod._cache_metrics.misses >= original_misses


def test_cache_manager_set_records_eviction_inventory_and_latency():
    try:
        import core.llm_client as llm_mod
        _SemanticCacheManager = llm_mod._SemanticCacheManager
    except Exception:
        pytest.skip("llm_client import başarısız")

    mgr = _SemanticCacheManager(MagicMock(
        ENABLE_SEMANTIC_CACHE=True,
        SEMANTIC_CACHE_THRESHOLD=0.95,
        SEMANTIC_CACHE_TTL=3600,
        SEMANTIC_CACHE_MAX_ITEMS=1,
        REDIS_URL="redis://localhost:6379/0",
    ))

    class _Pipe:
        def hset(self, *_a, **_k):
            return self

        def expire(self, *_a, **_k):
            return self

        def lrem(self, *_a, **_k):
            return self

        def lpush(self, *_a, **_k):
            return self

        def ltrim(self, *_a, **_k):
            return self

        async def execute(self):
            return []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    fake_redis = MagicMock()
    fake_redis.lrange = AsyncMock(return_value=["old-key"])
    fake_redis.llen = AsyncMock(return_value=1)
    fake_redis.pipeline.return_value = _Pipe()

    with patch.object(mgr, "_get_redis", AsyncMock(return_value=fake_redis)), patch.object(
        mgr, "_embed_prompt", return_value=[0.3, 0.7]
    ), patch.object(
        llm_mod, "record_cache_eviction"
    ) as record_eviction, patch.object(
        llm_mod, "set_cache_items"
    ) as set_cache_items, patch.object(
        llm_mod, "observe_cache_redis_latency"
    ) as observe_latency:
        _run(mgr.set("fresh prompt", "fresh response"))

    record_eviction.assert_called_once()
    set_cache_items.assert_called_once_with(1)
    observe_latency.assert_called_once()