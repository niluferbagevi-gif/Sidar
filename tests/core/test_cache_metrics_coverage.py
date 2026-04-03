from __future__ import annotations

import importlib
import sys
import types

import core.cache_metrics as mod


def setup_function() -> None:
    mod._cache_metrics = mod._CacheMetrics()
    mod._prometheus_metric_cache.clear()


class _Metric:
    def __init__(self) -> None:
        self.inc_calls: list[int] = []
        self.set_calls: list[float] = []

    def inc(self, value: int) -> None:
        self.inc_calls.append(value)

    def set(self, value: float) -> None:
        self.set_calls.append(value)


def test_record_and_snapshot_values() -> None:
    mod.record_cache_hit()
    mod.record_cache_miss()
    mod.record_cache_skip()
    mod.record_cache_eviction(-1)
    mod.record_cache_eviction(3)
    mod.record_cache_redis_error(2)
    mod.set_cache_items(-4)
    mod.observe_cache_redis_latency(-9)

    snap = mod.get_cache_metrics()
    assert snap["hits"] == 1
    assert snap["misses"] == 1
    assert snap["skips"] == 1
    assert snap["total_lookups"] == 2
    assert snap["hit_rate"] == 0.5
    assert snap["evictions"] == 3
    assert snap["redis_errors"] == 2
    assert snap["items"] == 0
    assert snap["redis_latency_ms"] == 0.0


def test_get_prometheus_metric_handles_missing_module(monkeypatch) -> None:
    monkeypatch.setattr(importlib, "import_module", lambda _name: (_ for _ in ()).throw(ImportError("x")))
    assert mod._get_prometheus_metric("m", "d", "counter") is None


def test_get_prometheus_metric_reuses_registry_collector(monkeypatch) -> None:
    existing = _Metric()
    fake_prom = types.SimpleNamespace(
        REGISTRY=types.SimpleNamespace(_names_to_collectors={"sidar_existing": existing}),
        Counter=lambda *_args, **_kwargs: _Metric(),
        Gauge=lambda *_args, **_kwargs: _Metric(),
    )
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake_prom)

    metric = mod._get_prometheus_metric("sidar_existing", "desc", "counter")
    assert metric is existing


def test_get_prometheus_metric_returns_cached_without_lock() -> None:
    cached = _Metric()
    mod._prometheus_metric_cache["sidar_cached"] = cached

    metric = mod._get_prometheus_metric("sidar_cached", "desc", "counter")
    assert metric is cached


def test_get_prometheus_metric_returns_cached_after_lock(monkeypatch) -> None:
    cached = _Metric()

    class _LockThatInjectsCache:
        def __enter__(self):
            mod._prometheus_metric_cache["sidar_cached_after_lock"] = cached
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mod, "_prometheus_metric_lock", _LockThatInjectsCache())

    metric = mod._get_prometheus_metric("sidar_cached_after_lock", "desc", "counter")
    assert metric is cached


def test_get_prometheus_metric_returns_none_when_metric_factory_missing(monkeypatch) -> None:
    fake_prom = types.SimpleNamespace(REGISTRY=types.SimpleNamespace(_names_to_collectors={}), Counter=_Metric)
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake_prom)

    assert mod._get_prometheus_metric("sidar_missing_gauge", "desc", "gauge") is None


def test_counter_and_gauge_helpers(monkeypatch) -> None:
    counter = _Metric()
    gauge = _Metric()

    def _fake_get(name: str, _desc: str, kind: str):
        if kind == "counter":
            return counter if name != "none" else None
        return gauge if name != "none" else None

    monkeypatch.setattr(mod, "_get_prometheus_metric", _fake_get)

    mod._inc_prometheus_counter("hit", "d", 0)
    mod._inc_prometheus_counter("hit", "d", 2)
    mod._set_prometheus_gauge("g", "d", 1.25)
    mod._set_prometheus_gauge("none", "d", 1.0)

    assert counter.inc_calls == [2]
    assert gauge.set_calls == [1.25]


def test_inc_prometheus_counter_ignores_metric_without_inc(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_get_prometheus_metric", lambda *_args, **_kwargs: object())

    mod._inc_prometheus_counter("hit", "d", 3)
