import types

import pytest

import core.cache_metrics as cache_metrics


@pytest.fixture(autouse=True)
def reset_metric_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Her test için modül seviyesindeki sayaçları ve cache'i sıfırla."""
    monkeypatch.setattr(cache_metrics, "_cache_metrics", cache_metrics._CacheMetrics())
    cache_metrics._prometheus_metric_cache.clear()


def test_cache_metrics_snapshot_and_normalization() -> None:
    metrics = cache_metrics._CacheMetrics()

    metrics.record_hit()
    metrics.record_miss()
    metrics.record_skip()
    metrics.record_eviction(count=3)
    metrics.record_eviction(count=-5)
    metrics.record_redis_error(count=2)
    metrics.record_redis_error(count=None)  # type: ignore[arg-type]
    metrics.record_circuit_open_bypass(count=4)
    metrics.record_circuit_open_bypass(count=-3)
    metrics.set_items(count=7)
    metrics.set_items(count=-2)
    metrics.observe_redis_latency(latency_ms=12.34567)

    snapshot = metrics.snapshot()

    assert snapshot == {
        "hits": 1,
        "misses": 1,
        "skips": 1,
        "total_lookups": 2,
        "hit_rate": 0.5,
        "evictions": 3,
        "redis_errors": 2,
        "circuit_open_bypasses": 4,
        "items": 0,
        "redis_latency_ms": 12.3457,
    }


def test_snapshot_hit_rate_is_zero_when_total_lookup_is_zero() -> None:
    assert cache_metrics._CacheMetrics().snapshot()["hit_rate"] == 0.0


def test_get_prometheus_metric_returns_cached_instance_without_import() -> None:
    cached = object()
    cache_metrics._prometheus_metric_cache["my_metric"] = cached

    metric = cache_metrics._get_prometheus_metric("my_metric", "desc", "counter")

    assert metric is cached


def test_get_prometheus_metric_returns_none_when_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_metrics.importlib,
        "import_module",
        lambda _: (_ for _ in ()).throw(RuntimeError("import error")),
    )

    assert cache_metrics._get_prometheus_metric("x", "desc", "counter") is None


def test_get_prometheus_metric_returns_cached_inside_lock_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    cache_metrics._prometheus_metric_cache.clear()

    class EnterSetsCache:
        def __enter__(self):
            cache_metrics._prometheus_metric_cache["late_metric"] = sentinel
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cache_metrics, "_prometheus_metric_lock", EnterSetsCache())
    assert cache_metrics._get_prometheus_metric("late_metric", "desc", "counter") is sentinel


def test_get_prometheus_metric_uses_registry_existing_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_collector = object()
    fake_registry = types.SimpleNamespace(_names_to_collectors={"metric": existing_collector})
    fake_prom = types.SimpleNamespace(REGISTRY=fake_registry)
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _: fake_prom)

    metric = cache_metrics._get_prometheus_metric("metric", "desc", "counter")

    assert metric is existing_collector
    assert cache_metrics._prometheus_metric_cache["metric"] is existing_collector


def test_get_prometheus_metric_returns_none_when_factory_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_prom = types.SimpleNamespace(REGISTRY=None, Counter=None)
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _: fake_prom)

    metric = cache_metrics._get_prometheus_metric("metric", "desc", "counter")

    assert metric is None


def test_get_prometheus_metric_creates_new_counter_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_calls = []

    def fake_counter(name: str, desc: str) -> object:
        created_calls.append((name, desc))
        return {"name": name, "desc": desc}

    fake_prom = types.SimpleNamespace(REGISTRY=None, Counter=fake_counter, Gauge=None)
    monkeypatch.setattr(cache_metrics.importlib, "import_module", lambda _: fake_prom)

    metric = cache_metrics._get_prometheus_metric("fresh_metric", "fresh desc", "counter")

    assert metric == {"name": "fresh_metric", "desc": "fresh desc"}
    assert created_calls == [("fresh_metric", "fresh desc")]
    assert cache_metrics._prometheus_metric_cache["fresh_metric"] == metric


def test_inc_prometheus_counter_early_exit_for_non_positive_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = []
    monkeypatch.setattr(cache_metrics, "_get_prometheus_metric", lambda *args: called.append(args))

    cache_metrics._inc_prometheus_counter("metric", "desc", count=0)
    cache_metrics._inc_prometheus_counter("metric", "desc", count=-3)

    assert called == []


def test_inc_prometheus_counter_calls_inc_only_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inc_calls = []
    counter = types.SimpleNamespace(inc=lambda value: inc_calls.append(value))
    monkeypatch.setattr(cache_metrics, "_get_prometheus_metric", lambda *args: counter)

    cache_metrics._inc_prometheus_counter("metric", "desc", count=4)

    assert inc_calls == [4]


def test_inc_prometheus_counter_noop_when_counter_has_no_inc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_metrics, "_get_prometheus_metric", lambda *args: object())
    cache_metrics._inc_prometheus_counter("metric", "desc", count=2)


def test_set_prometheus_gauge_calls_set_only_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gauge_values = []
    gauge = types.SimpleNamespace(set=lambda value: gauge_values.append(value))
    monkeypatch.setattr(cache_metrics, "_get_prometheus_metric", lambda *args: gauge)

    cache_metrics._set_prometheus_gauge("metric", "desc", 7.5)

    assert gauge_values == [7.5]


def test_set_prometheus_gauge_noop_when_set_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_metrics, "_get_prometheus_metric", lambda *args: object())
    cache_metrics._set_prometheus_gauge("metric", "desc", 1.2)


def test_public_cache_record_functions_update_internal_metrics_and_prometheus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter_calls = []
    gauge_calls = []
    monkeypatch.setattr(
        cache_metrics,
        "_inc_prometheus_counter",
        lambda name, desc, count=1: counter_calls.append((name, desc, count)),
    )
    monkeypatch.setattr(
        cache_metrics,
        "_set_prometheus_gauge",
        lambda name, desc, value: gauge_calls.append((name, desc, value)),
    )

    cache_metrics.record_cache_hit()
    cache_metrics.record_cache_miss()
    cache_metrics.record_cache_skip()
    cache_metrics.record_cache_eviction(count=5)
    cache_metrics.record_cache_redis_error(count=2)
    cache_metrics.record_cache_circuit_open_bypass(count=3)
    cache_metrics.set_cache_items(count=-10)
    cache_metrics.observe_cache_redis_latency(latency_ms=-9.6)

    assert counter_calls == [
        ("sidar_semantic_cache_hits_total", "Semantic cache hit count", 1),
        ("sidar_semantic_cache_misses_total", "Semantic cache miss count", 1),
        ("sidar_semantic_cache_skips_total", "Semantic cache skip count", 1),
        ("sidar_semantic_cache_evictions_total", "Semantic cache eviction count", 5),
        (
            "sidar_semantic_cache_redis_errors_total",
            "Semantic cache Redis error count",
            2,
        ),
        (
            "sidar_semantic_cache_circuit_open_total",
            "Semantic cache circuit-open bypass count",
            3,
        ),
    ]
    assert gauge_calls == [
        ("sidar_semantic_cache_items", "Current semantic cache item count", 0),
        (
            "sidar_semantic_cache_redis_latency_ms",
            "Latest semantic cache Redis latency in milliseconds",
            0.0,
        ),
    ]

    assert cache_metrics.get_cache_metrics() == {
        "hits": 1,
        "misses": 1,
        "skips": 1,
        "total_lookups": 2,
        "hit_rate": 0.5,
        "evictions": 5,
        "redis_errors": 2,
        "circuit_open_bypasses": 3,
        "items": 0,
        "redis_latency_ms": 0.0,
    }
