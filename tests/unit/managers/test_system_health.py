from types import SimpleNamespace
import types
import sys

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
            "circuit_open_bypasses": 6,
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
    assert "sidar_semantic_cache_circuit_open_total 6" in text
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


def test_check_import_and_check_gpu_paths(monkeypatch):
    assert SystemHealthManager._check_import("sys") is True
    assert SystemHealthManager._check_import("module_does_not_exist_123") is False

    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(lambda _name: False))
    manager = SystemHealthManager(use_gpu=True)
    manager._torch_available = False
    assert manager._check_gpu() is False

    manager._torch_available = True
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert manager._check_gpu() is True

    class BrokenTorch:
        class cuda:
            @staticmethod
            def is_available():
                raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "torch", BrokenTorch())
    assert manager._check_gpu() is False


def test_init_nvml_sets_state_and_handles_fallback(monkeypatch):
    manager = _build_manager(monkeypatch)
    manager._nvml_initialized = False
    fake_pynvml = types.SimpleNamespace(nvmlInit=lambda: None)
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)
    manager._init_nvml()
    assert manager._nvml_initialized is True

    manager2 = _build_manager(monkeypatch)
    manager2._nvml_initialized = False

    class FailingNvml:
        @staticmethod
        def nvmlInit():
            raise RuntimeError("nvml blocked")

    monkeypatch.setitem(sys.modules, "pynvml", FailingNvml())
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no file")))
    manager2._init_nvml()
    assert manager2._nvml_initialized is False


def test_cpu_and_memory_paths_with_psutil(monkeypatch):
    manager = _build_manager(monkeypatch)
    manager._psutil_available = True

    class FakePsutil:
        @staticmethod
        def cpu_percent(interval):
            return 42.5 if interval == 0.0 else interval

        @staticmethod
        def virtual_memory():
            return types.SimpleNamespace(total=2e9, used=1e9, available=1e9, percent=50)

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil())
    assert manager.get_cpu_usage() == 42.5
    assert manager.get_cpu_usage(interval=-3) == 42.5
    assert manager.get_memory_info()["percent"] == 50

    class BrokenPsutil:
        @staticmethod
        def cpu_percent(interval):
            raise RuntimeError("cpu fail")

        @staticmethod
        def virtual_memory():
            raise RuntimeError("vm fail")

    monkeypatch.setitem(sys.modules, "psutil", BrokenPsutil())
    assert manager.get_cpu_usage() is None
    assert manager.get_memory_info() == {}


def test_get_gpu_info_and_driver_version_variants(monkeypatch):
    manager = _build_manager(monkeypatch, use_gpu=True)
    manager._gpu_available = True
    manager._nvml_initialized = False
    monkeypatch.setattr(manager, "_get_driver_version", lambda: "550.10")

    class FakeTorch:
        version = types.SimpleNamespace(cuda="12.1")

        class cuda:
            @staticmethod
            def device_count():
                return 1

            @staticmethod
            def get_device_properties(_idx):
                return types.SimpleNamespace(name="RTX", major=8, minor=6, total_memory=10_000_000_000)

            @staticmethod
            def memory_allocated(_idx):
                return 2_000_000_000

            @staticmethod
            def memory_reserved(_idx):
                return 3_000_000_000

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    info = manager.get_gpu_info()
    assert info["available"] is True
    assert info["devices"][0]["compute_capability"] == "8.6"

    manager._nvml_initialized = True
    fake_pynvml = types.SimpleNamespace(
        NVML_TEMPERATURE_GPU=0,
        nvmlDeviceGetHandleByIndex=lambda _i: object(),
        nvmlDeviceGetTemperature=lambda _h, _k: 70,
        nvmlDeviceGetUtilizationRates=lambda _h: types.SimpleNamespace(gpu=90, memory=80),
        nvmlSystemGetDriverVersion=lambda: "560.01",
    )
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)
    assert manager.get_gpu_info()["devices"][0]["temperature_c"] == 70
    manager3 = _build_manager(monkeypatch, use_gpu=True)
    manager3._nvml_initialized = True
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)
    assert manager3._get_driver_version() == "560.01"

    class BadPynvml:
        @staticmethod
        def nvmlSystemGetDriverVersion():
            raise RuntimeError("no driver")

    manager3._nvml_initialized = True
    monkeypatch.setitem(sys.modules, "pynvml", BadPynvml())
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_a, **_k: types.SimpleNamespace(stdout="535.54\n", returncode=0),
    )
    assert manager3._get_driver_version() == "535.54"

    monkeypatch.setattr(
        "subprocess.run",
        lambda *_a, **_k: types.SimpleNamespace(stdout="\n", returncode=1),
    )
    assert manager3._get_driver_version() == "N/A"


def test_optimize_gpu_memory_gpu_paths_and_ollama(monkeypatch):
    manager = _build_manager(monkeypatch, use_gpu=True)
    manager._gpu_available = True
    state = {"reserved": 500_000_000}

    class FakeCuda:
        @staticmethod
        def memory_reserved():
            return state["reserved"]

        @staticmethod
        def empty_cache():
            state["reserved"] = 100_000_000

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=FakeCuda()))
    monkeypatch.setattr("gc.collect", lambda: 0)
    output = manager.optimize_gpu_memory()
    assert "400.0 MB" in output

    class BadCuda:
        @staticmethod
        def memory_reserved():
            raise RuntimeError("cuda err")

        @staticmethod
        def empty_cache():
            raise RuntimeError("cuda err")

    with pytest.raises(RuntimeError, match="cuda err"):
        BadCuda.empty_cache()
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=BadCuda()))
    output2 = manager.optimize_gpu_memory()
    assert "GPU cache hatası" in output2

    calls = {}

    class FakeRequests:
        @staticmethod
        def get(url, timeout):
            calls["url"] = url
            calls["timeout"] = timeout
            return types.SimpleNamespace(status_code=200)

    manager.cfg = SimpleNamespace(OLLAMA_URL="http://ollama.test/api/", OLLAMA_TIMEOUT=0)
    monkeypatch.setitem(sys.modules, "requests", FakeRequests())
    assert manager.check_ollama() is True
    assert calls["url"].endswith("/tags")
    assert calls["timeout"] == 1


def test_update_summary_report_close_repr_and_del(monkeypatch):
    manager = _build_manager(monkeypatch)
    manager._prometheus_gauges = {"cpu_percent": object()}
    manager.update_prometheus_metrics({})
    manager.update_prometheus_metrics({"cpu_percent": "bad"})

    cfg = SimpleNamespace(ENABLE_DEPENDENCY_HEALTHCHECKS=False)
    manager2 = _build_manager(monkeypatch, cfg=cfg)
    monkeypatch.setattr(manager2, "get_cpu_usage", lambda interval=None: 10.0)
    monkeypatch.setattr(manager2, "get_memory_info", lambda: {"percent": 20.0, "used_gb": 1.0, "total_gb": 2.0})
    monkeypatch.setattr(manager2, "check_ollama", lambda: True)
    monkeypatch.setattr(
        manager2,
        "get_gpu_info",
        lambda: {
            "available": True,
            "cuda_version": "12.2",
            "driver_version": "550.1",
            "devices": [
                {
                    "id": 0,
                    "name": "RTX",
                    "compute_capability": "8.6",
                    "allocated_gb": 2.0,
                    "total_vram_gb": 8.0,
                    "free_gb": 6.0,
                    "temperature_c": 65,
                    "utilization_pct": 50,
                }
            ],
        },
    )
    summary = manager2.get_health_summary()
    assert summary["status"] == "healthy"
    assert "dependencies" not in summary
    report = manager2.full_report()
    assert "CUDA      : 12.2" in report
    assert "%50 GPU" in report

    manager2._nvml_initialized = True
    monkeypatch.setitem(sys.modules, "pynvml", types.SimpleNamespace(nvmlShutdown=lambda: None))
    manager2.close()
    assert manager2._nvml_initialized is False

    manager2._nvml_initialized = True
    monkeypatch.setitem(
        sys.modules,
        "pynvml",
        types.SimpleNamespace(nvmlShutdown=lambda: (_ for _ in ()).throw(RuntimeError("x"))),
    )
    manager2.close()
    assert manager2._nvml_initialized is False
    assert "SystemHealthManager" in repr(manager2)
    manager2.__del__()


def test_init_calls_nvml_when_gpu_and_pynvml_available(monkeypatch):
    calls = {"init": 0}
    monkeypatch.setattr(
        SystemHealthManager,
        "_check_import",
        staticmethod(lambda name: name in {"torch", "psutil", "pynvml"}),
    )
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: True)
    monkeypatch.setattr(
        SystemHealthManager,
        "_init_nvml",
        lambda self: calls.__setitem__("init", calls["init"] + 1),
    )
    _ = SystemHealthManager(use_gpu=True)
    assert calls["init"] == 1


def test_init_nvml_wsl2_logging_branch(monkeypatch):
    manager = _build_manager(monkeypatch)
    manager._nvml_initialized = False

    class FailingNvml:
        @staticmethod
        def nvmlInit():
            raise RuntimeError("blocked")

    monkeypatch.setitem(sys.modules, "pynvml", FailingNvml())

    class FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return "5.15.90-microsoft-standard-WSL2"

    monkeypatch.setattr("builtins.open", lambda *_a, **_k: FakeFile())
    manager._init_nvml()
    assert manager._nvml_initialized is False


def test_psutil_unavailable_and_gpu_info_error_paths(monkeypatch):
    manager = _build_manager(monkeypatch)
    manager._psutil_available = False
    assert manager.get_cpu_usage() is None
    assert manager.get_memory_info() == {}

    manager._gpu_available = False
    assert manager.get_gpu_info()["available"] is False

    manager._gpu_available = True

    class BrokenTorch:
        class cuda:
            @staticmethod
            def device_count():
                raise RuntimeError("torch fail")

    monkeypatch.setitem(sys.modules, "torch", BrokenTorch())
    info = manager.get_gpu_info()
    assert info["available"] is False
    assert "torch fail" in info["error"]


def test_driver_version_generic_error_and_ollama_exception(monkeypatch):
    manager = _build_manager(monkeypatch)
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("oops")))
    assert manager._get_driver_version() == "N/A"

    class BrokenRequests:
        @staticmethod
        def get(*_a, **_k):
            raise RuntimeError("down")

    monkeypatch.setitem(sys.modules, "requests", BrokenRequests())
    assert manager.check_ollama() is False


def test_update_prometheus_metrics_init_exception_and_empty_short_circuit(monkeypatch):
    manager = _build_manager(monkeypatch)
    monkeypatch.setattr(manager, "_check_import", lambda _name: True)
    monkeypatch.setitem(
        sys.modules,
        "prometheus_client",
        types.SimpleNamespace(Gauge=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("gauge fail"))),
    )
    manager.update_prometheus_metrics({"cpu_percent": 1})
    assert manager._prometheus_gauges == {}

    # _prometheus_gauges boş dict olduğunda erken dönüş.
    manager.update_prometheus_metrics({"ram_percent": 2})
    assert manager._prometheus_gauges == {}


def test_get_dependency_health_and_database_disabled(monkeypatch):
    manager = _build_manager(monkeypatch, cfg=SimpleNamespace(DATABASE_URL="", REDIS_URL=""))
    deps = manager.get_dependency_health()
    assert deps["redis"]["mode"] == "disabled"
    assert deps["database"]["mode"] == "disabled"


def test_full_report_gpu_line_optional_fields(monkeypatch):
    manager = _build_manager(monkeypatch)
    monkeypatch.setattr(manager, "get_cpu_usage", lambda interval=None: 20.0)
    monkeypatch.setattr(manager, "get_memory_info", lambda: {"percent": 10.0, "used_gb": 1.0, "total_gb": 4.0})
    monkeypatch.setattr(manager, "check_ollama", lambda: True)
    metrics = {}
    monkeypatch.setattr(manager, "update_prometheus_metrics", lambda data: metrics.update(data))

    # Sadece temperature var, utilization yok
    monkeypatch.setattr(
        manager,
        "get_gpu_info",
        lambda: {
            "available": True,
            "cuda_version": "12.0",
            "driver_version": "550",
            "devices": [{"id": 0, "name": "RTX", "compute_capability": "8.0", "allocated_gb": 1.0, "total_vram_gb": 8.0, "free_gb": 7.0, "temperature_c": 61}],
        },
    )
    report = manager.full_report()
    assert "61°C" in report
    assert "% GPU" not in report

    # Sadece utilization var, temperature yok
    monkeypatch.setattr(
        manager,
        "get_gpu_info",
        lambda: {
            "available": True,
            "cuda_version": "12.0",
            "driver_version": "550",
            "devices": [{"id": 0, "name": "RTX", "compute_capability": "8.0", "allocated_gb": 1.0, "total_vram_gb": 8.0, "free_gb": 7.0, "utilization_pct": 77}],
        },
    )
    report2 = manager.full_report()
    assert "%77 GPU" in report2
    assert metrics["gpu_utilization_pct"] == 77


def test_system_health_manager_isolated(monkeypatch):
    health_cfg = SimpleNamespace(
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
        REDIS_URL="",
        DATABASE_URL="",
        HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
    )
    health = SystemHealthManager(cfg=health_cfg)
    monkeypatch.setattr(health, "get_cpu_usage", lambda interval=None: 12.5)
    monkeypatch.setattr(health, "get_memory_info", lambda: {"percent": 34.0})
    monkeypatch.setattr(health, "get_gpu_info", lambda: {"available": False})
    monkeypatch.setattr(health, "check_ollama", lambda: True)
    summary = health.get_health_summary()
    assert summary["status"] in {"healthy", "degraded"}
    assert "dependencies" in summary


def test_check_ollama_non_200_and_timeout(monkeypatch, mock_requests):
    manager = _build_manager(monkeypatch, cfg=SimpleNamespace(OLLAMA_URL="http://ollama.local/api", OLLAMA_TIMEOUT=1))

    class _Resp:
        status_code = 503

    mock_requests(get_impl=lambda *_a, **_k: _Resp())
    assert manager.check_ollama() is False

    def _raise_timeout(*_args, **_kwargs):
        raise TimeoutError("request timeout")

    mock_requests(get_impl=_raise_timeout)
    assert manager.check_ollama() is False
