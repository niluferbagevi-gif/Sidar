import types

import core.cache_metrics as cache_metrics


class _FakeCounter:
    def __init__(self):
        self.value = 0

    def inc(self, amount=1):
        self.value += amount


class _FakeGauge:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _FakePromClient:
    def __init__(self):
        self.REGISTRY = types.SimpleNamespace(_names_to_collectors={})

    @staticmethod
    def Counter(_name, _desc):
        return _FakeCounter()

    @staticmethod
    def Gauge(_name, _desc):
        return _FakeGauge()


def _reset_metrics_state():
    cache_metrics._cache_metrics = cache_metrics._CacheMetrics()
    cache_metrics._prometheus_metric_cache.clear()


def test_record_functions_and_snapshot_values(monkeypatch):
    _reset_metrics_state()
    fake_prom = _FakePromClient()
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _name: fake_prom)

    cache_metrics.record_cache_hit()
    cache_metrics.record_cache_hit()
    cache_metrics.record_cache_miss()
    cache_metrics.record_cache_skip()
    cache_metrics.record_cache_eviction(count=2)
    cache_metrics.record_cache_redis_error(count=3)
    cache_metrics.set_cache_items(11)
    cache_metrics.observe_cache_redis_latency(13.45678)

    snap = cache_metrics.get_cache_metrics()
    assert snap["hits"] == 2
    assert snap["misses"] == 1
    assert snap["skips"] == 1
    assert snap["total_lookups"] == 3
    assert snap["hit_rate"] == 0.6667
    assert snap["evictions"] == 2
    assert snap["redis_errors"] == 3
    assert snap["items"] == 11
    assert snap["redis_latency_ms"] == 13.4568


def test_negative_values_are_safeguarded(monkeypatch):
    _reset_metrics_state()
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _name: _FakePromClient())

    cache_metrics.record_cache_eviction(count=-5)
    cache_metrics.record_cache_redis_error(count=-1)
    cache_metrics.set_cache_items(-3)
    cache_metrics.observe_cache_redis_latency(-99)

    snap = cache_metrics.get_cache_metrics()
    assert snap["evictions"] == 0
    assert snap["redis_errors"] == 0
    assert snap["items"] == 0
    assert snap["redis_latency_ms"] == 0.0


def test_prometheus_helpers_handle_missing_dependency(monkeypatch):
    _reset_metrics_state()

    def _raise(_name):
        raise ImportError("prometheus_client not installed")

    monkeypatch.setattr(cache_metrics.importlib, "import_module", _raise)

    # should not crash even without prometheus_client
    cache_metrics.record_cache_hit()
    cache_metrics.record_cache_miss()
    cache_metrics.record_cache_skip()
    cache_metrics.record_cache_eviction()
    cache_metrics.record_cache_redis_error()
    cache_metrics.set_cache_items(1)
    cache_metrics.observe_cache_redis_latency(1.23)

    snap = cache_metrics.get_cache_metrics()
    assert snap["hits"] == 1
    assert snap["misses"] == 1
    assert snap["skips"] == 1


def test_get_prometheus_metric_uses_existing_registry_collector(monkeypatch):
    _reset_metrics_state()
    existing = _FakeCounter()
    fake_prom = _FakePromClient()
    fake_prom.REGISTRY._names_to_collectors["sidar_semantic_cache_hits_total"] = existing
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _name: fake_prom)

    metric = cache_metrics._get_prometheus_metric(
        "sidar_semantic_cache_hits_total",
        "desc",
        "counter",
    )

    assert metric is existing


def test_get_prometheus_metric_returns_none_when_factory_missing(monkeypatch):
    _reset_metrics_state()
    fake_prom = types.SimpleNamespace(REGISTRY=types.SimpleNamespace(_names_to_collectors={}))
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _name: fake_prom)

    assert cache_metrics._get_prometheus_metric("x", "y", "counter") is None
