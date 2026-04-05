from types import SimpleNamespace

import pytest

from managers.system_health import SystemHealthManager, render_llm_metrics_prometheus


def _build_manager(monkeypatch, *, cfg=None, use_gpu=False):
    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(lambda _name: False))
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: False)
    return SystemHealthManager(use_gpu=use_gpu, cfg=cfg)


def test_render_llm_metrics_prometheus_with_snapshot_values():
    snapshot = {
        "totals": {"calls": 4, "cost_usd": 2.5, "total_tokens": 300, "failures": 1},
        "cache": {
            "hits": 9,
            "misses": 3,
            "skips": 2,
            "evictions": 1,
            "redis_errors": 4,
            "hit_rate": 0.75,
            "items": 7,
            "redis_latency_ms": 11.2,
        },
        "by_provider": {
            'open"ai': {"calls": 2, "cost_usd": 1.2, "total_tokens": 200, "failures": 1, "latency_ms_avg": 123.4}
        },
        "by_user": {'user"1': {"calls": 1, "cost_usd": 0.3, "total_tokens": 50}},
    }

    text = render_llm_metrics_prometheus(snapshot)

    assert "sidar_llm_calls_total 4" in text
    assert "sidar_semantic_cache_hits_total 9" in text
    assert 'sidar_llm_calls_total{provider="open\\"ai"} 2' in text
    assert 'sidar_llm_user_calls_total{user_id="user\\"1"} 1' in text
    assert text.endswith("\n")


def test_render_llm_metrics_prometheus_with_invalid_input_uses_defaults():
    text = render_llm_metrics_prometheus(None)

    assert "sidar_llm_calls_total 0" in text
    assert "sidar_cache_hit_rate 0.0" in text


def test_tcp_dependency_health_success_and_error(monkeypatch):
    manager = _build_manager(monkeypatch)

    class DummySock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: DummySock())
    ok = manager._tcp_dependency_health("localhost", 6379, label="redis")
    assert ok == {"healthy": True, "target": "localhost:6379", "kind": "redis"}

    def raise_conn(*_args, **_kwargs):
        raise OSError("cannot connect")

    monkeypatch.setattr("socket.create_connection", raise_conn)
    failed = manager._tcp_dependency_health("localhost", 5432, label="database")
    assert failed["healthy"] is False
    assert failed["kind"] == "database"
    assert "cannot connect" in failed["error"]


def test_check_redis_disabled_and_tcp(monkeypatch):
    disabled = _build_manager(monkeypatch, cfg=SimpleNamespace(REDIS_URL=""))
    assert disabled.check_redis() == {"healthy": True, "kind": "redis", "mode": "disabled"}

    enabled = _build_manager(monkeypatch, cfg=SimpleNamespace(REDIS_URL="redis://cache.local:6380"))
    monkeypatch.setattr(
        enabled,
        "_tcp_dependency_health",
        lambda host, port, label: {"healthy": True, "target": f"{host}:{port}", "kind": label},
    )

    status = enabled.check_redis()
    assert status["target"] == "cache.local:6380"
    assert status["mode"] == "tcp"


def test_check_database_sqlite_and_tcp(monkeypatch, tmp_path):
    existing = tmp_path / "app.db"
    existing.write_text("db")
    sqlite_manager = _build_manager(monkeypatch, cfg=SimpleNamespace(DATABASE_URL=f"sqlite:///{existing}"))
    sqlite_status = sqlite_manager.check_database()
    assert sqlite_status["healthy"] is True
    assert sqlite_status["mode"] == "sqlite"

    missing_manager = _build_manager(monkeypatch, cfg=SimpleNamespace(DATABASE_URL=f"sqlite:///{tmp_path / 'missing.db'}"))
    missing_status = missing_manager.check_database()
    assert missing_status["healthy"] is False
    assert "error" in missing_status

    tcp_manager = _build_manager(monkeypatch, cfg=SimpleNamespace(DATABASE_URL="postgres://db.internal:6543/sidar"))
    monkeypatch.setattr(
        tcp_manager,
        "_tcp_dependency_health",
        lambda host, port, label: {"healthy": True, "target": f"{host}:{port}", "kind": label},
    )
    tcp_status = tcp_manager.check_database()
    assert tcp_status["target"] == "db.internal:6543"
    assert tcp_status["mode"] == "postgres"


def test_update_prometheus_metrics_handles_missing_prometheus_client(monkeypatch):
    manager = _build_manager(monkeypatch)
    monkeypatch.setattr(manager, "_check_import", lambda name: False if name == "prometheus_client" else True)

    manager.update_prometheus_metrics({"cpu_percent": 22})

    assert manager._prometheus_gauges == {}


def test_update_prometheus_metrics_sets_expected_gauges(monkeypatch):
    manager = _build_manager(monkeypatch)

    class FakeGauge:
        def __init__(self, *_args, **_kwargs):
            self.values = []

        def set(self, value):
            self.values.append(value)

    import managers.system_health as system_health_module

    monkeypatch.setattr(manager, "_check_import", lambda _name: True)
    monkeypatch.setattr(system_health_module, "Gauge", FakeGauge, raising=False)

    class FakePromModule:
        Gauge = FakeGauge

    monkeypatch.setitem(__import__("sys").modules, "prometheus_client", FakePromModule())

    manager.update_prometheus_metrics(
        {
            "cpu_percent": 11,
            "ram_percent": 33,
            "gpu_utilization_pct": 44,
            "gpu_temperature_c": 66,
        }
    )

    assert manager._prometheus_gauges is not None
    assert manager._prometheus_gauges["cpu_percent"].values == [11.0]
    assert manager._prometheus_gauges["ram_percent"].values == [33.0]
    assert manager._prometheus_gauges["gpu_util_percent"].values == [44.0]
    assert manager._prometheus_gauges["gpu_temp_c"].values == [66.0]


def test_get_health_summary_marks_degraded_when_dependency_unhealthy(monkeypatch):
    cfg = SimpleNamespace(ENABLE_DEPENDENCY_HEALTHCHECKS=True)
    manager = _build_manager(monkeypatch, cfg=cfg)
    monkeypatch.setattr(manager, "get_cpu_usage", lambda interval=None: 12.0)
    monkeypatch.setattr(manager, "get_memory_info", lambda: {"percent": 40.0})
    monkeypatch.setattr(manager, "get_gpu_info", lambda: {"available": False})
    monkeypatch.setattr(manager, "check_ollama", lambda: True)
    monkeypatch.setattr(
        manager,
        "get_dependency_health",
        lambda: {
            "redis": {"healthy": True},
            "database": {"healthy": False},
        },
    )

    summary = manager.get_health_summary()

    assert summary["status"] == "degraded"
    assert summary["dependencies"]["database"]["healthy"] is False


def test_full_report_includes_gpu_reason_and_updates_metrics(monkeypatch):
    manager = _build_manager(monkeypatch)
    captured = {}
    monkeypatch.setattr(manager, "get_cpu_usage", lambda interval=None: None)
    monkeypatch.setattr(manager, "get_memory_info", lambda: {})
    monkeypatch.setattr(manager, "check_ollama", lambda: False)
    monkeypatch.setattr(manager, "get_gpu_info", lambda: {"available": False, "reason": "devre dışı"})
    monkeypatch.setattr(manager, "update_prometheus_metrics", lambda data: captured.update(data))

    report = manager.full_report()

    assert "GPU       : devre dışı" in report
    assert "Ollama    : Çevrimdışı" in report
    assert captured["cpu_percent"] == 0.0
    assert captured["ram_percent"] == 0.0


def test_optimize_gpu_memory_runs_gc_even_without_gpu(monkeypatch):
    manager = _build_manager(monkeypatch)
    calls = {"gc": 0}
    monkeypatch.setattr("gc.collect", lambda: calls.__setitem__("gc", calls["gc"] + 1))

    output = manager.optimize_gpu_memory()

    assert "0.0 MB" in output
    assert "Python GC çalıştırıldı" in output
    assert calls["gc"] == 1


def test_get_driver_version_falls_back_to_na_on_missing_command(monkeypatch):
    manager = _build_manager(monkeypatch)
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))

    assert manager._get_driver_version() == "N/A"
