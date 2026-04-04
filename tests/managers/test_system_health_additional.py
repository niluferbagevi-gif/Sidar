from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from managers.system_health import SystemHealthManager, render_llm_metrics_prometheus


@pytest.fixture
def base_manager(monkeypatch: pytest.MonkeyPatch) -> SystemHealthManager:
    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(lambda _name: False))
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: False)
    return SystemHealthManager(use_gpu=False, cfg=SimpleNamespace())


def test_render_llm_metrics_prometheus_provider_and_user_labels() -> None:
    text = render_llm_metrics_prometheus(
        {
            "totals": {},
            "by_provider": {"open\"ai": {"calls": 2, "cost_usd": 1.2, "total_tokens": 10, "failures": 1, "latency_ms_avg": 9.5}},
            "by_user": {"u\"1": {"calls": 3, "cost_usd": 2.5, "total_tokens": 99}},
        }
    )

    assert 'sidar_llm_calls_total{provider="open"ai"} 2' in text
    assert 'sidar_llm_user_calls_total{user_id="u"1"} 3' in text


def test_check_import_and_check_gpu_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert SystemHealthManager._check_import("sys") is True
    assert SystemHealthManager._check_import("definitely_missing_module_xyz") is False

    mgr = SystemHealthManager.__new__(SystemHealthManager)
    mgr._lock = __import__("threading").RLock()
    mgr._nvml_initialized = False
    mgr.use_gpu = True
    mgr._torch_available = True

    torch_mod = ModuleType("torch")
    torch_mod.cuda = SimpleNamespace(is_available=lambda: True)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    assert mgr._check_gpu() is True

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert mgr._check_gpu() is False


def test_init_triggers_nvml_and_interval_clamping(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_check_import(name: str) -> bool:
        return name in {"torch", "pynvml"}

    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(fake_check_import))
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: True)
    monkeypatch.setattr(SystemHealthManager, "_init_nvml", lambda self: calls.append("nvml"))

    mgr = SystemHealthManager(use_gpu=True, cpu_sample_interval=9.0, cfg=SimpleNamespace())

    assert mgr.cpu_sample_interval == 2.0
    assert calls == ["nvml"]


def test_init_nvml_success_and_failure_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SystemHealthManager.__new__(SystemHealthManager)
    mgr._lock = __import__("threading").RLock()
    mgr._nvml_initialized = False

    mod = ModuleType("pynvml")
    mod.nvmlInit = lambda: None
    monkeypatch.setitem(sys.modules, "pynvml", mod)
    mgr._init_nvml()
    assert mgr._nvml_initialized is True

    def boom() -> None:
        raise RuntimeError("no nvml")

    mod.nvmlInit = boom
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no proc")))
    mgr._nvml_initialized = False
    mgr._init_nvml()
    assert mgr._nvml_initialized is False


def test_cpu_and_memory_info_paths(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    base_manager._psutil_available = False
    assert base_manager.get_cpu_usage() is None
    assert base_manager.get_memory_info() == {}

    class FakePsutil:
        @staticmethod
        def cpu_percent(interval: float) -> float:
            if interval < 0:
                raise RuntimeError("bad")
            return 33.3

        @staticmethod
        def virtual_memory() -> object:
            return SimpleNamespace(total=16e9, used=6e9, available=10e9, percent=37.5)

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    base_manager._psutil_available = True
    assert base_manager.get_cpu_usage(interval=-5) == 33.3
    assert base_manager.get_memory_info()["percent"] == 37.5

    monkeypatch.setattr(FakePsutil, "virtual_memory", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("x"))))
    assert base_manager.get_memory_info() == {}


def test_gpu_info_success_and_error(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    assert base_manager.get_gpu_info()["available"] is False

    base_manager._gpu_available = True
    base_manager._nvml_initialized = False
    base_manager._get_driver_version = lambda: "555.1"

    class FakeCuda:
        @staticmethod
        def device_count() -> int:
            return 1

        @staticmethod
        def get_device_properties(_i: int) -> object:
            return SimpleNamespace(total_memory=8e9, name="Fake GPU", major=8, minor=9)

        @staticmethod
        def memory_allocated(_i: int) -> float:
            return 2e9

        @staticmethod
        def memory_reserved(_i: int) -> float:
            return 3e9

    torch_mod = ModuleType("torch")
    torch_mod.cuda = FakeCuda
    torch_mod.version = SimpleNamespace(cuda="12.1")
    monkeypatch.setitem(sys.modules, "torch", torch_mod)

    info = base_manager.get_gpu_info()
    assert info["available"] is True
    assert info["devices"][0]["free_gb"] == 5.0

    monkeypatch.setattr(FakeCuda, "device_count", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("gpu fail"))))
    assert base_manager.get_gpu_info()["available"] is False


def test_get_driver_version_all_fallbacks(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    base_manager._nvml_initialized = True

    pynvml = ModuleType("pynvml")
    pynvml.nvmlSystemGetDriverVersion = lambda: "550.40"
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)
    assert base_manager._get_driver_version() == "550.40"

    def bad_driver() -> str:
        raise RuntimeError("bad")

    pynvml.nvmlSystemGetDriverVersion = bad_driver
    monkeypatch.setattr(
        "managers.system_health.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(stdout="\n", returncode=1),
    )
    assert base_manager._get_driver_version() == "N/A"

    monkeypatch.setattr("managers.system_health.subprocess.run", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
    assert base_manager._get_driver_version() == "N/A"


def test_optimize_gpu_memory_and_gc(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    calls = {"gc": 0}
    monkeypatch.setattr("managers.system_health.gc.collect", lambda: calls.__setitem__("gc", calls["gc"] + 1))

    base_manager._gpu_available = True

    class FakeCuda:
        values = [120e6, 40e6]

        @classmethod
        def memory_reserved(cls) -> float:
            return cls.values.pop(0)

        @staticmethod
        def empty_cache() -> None:
            return None

    torch_mod = ModuleType("torch")
    torch_mod.cuda = FakeCuda
    monkeypatch.setitem(sys.modules, "torch", torch_mod)

    report = base_manager.optimize_gpu_memory()
    assert "80.0 MB" in report
    assert calls["gc"] == 1

    monkeypatch.setattr(FakeCuda, "empty_cache", staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("cache err"))))
    FakeCuda.values = [10e6]
    report2 = base_manager.optimize_gpu_memory()
    assert "GPU cache hatası" in report2


def test_check_ollama_and_prometheus_paths(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    requests_mod = ModuleType("requests")
    requests_mod.get = lambda *_a, **_k: SimpleNamespace(status_code=200)
    monkeypatch.setitem(sys.modules, "requests", requests_mod)

    base_manager.cfg = SimpleNamespace(OLLAMA_URL="http://x/api/", OLLAMA_TIMEOUT=0)
    assert base_manager.check_ollama() is True

    requests_mod.get = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down"))
    assert base_manager.check_ollama() is False

    class Gauge:
        def __init__(self, *_a, **_k):
            self.values: list[float] = []

        def set(self, v: float) -> None:
            if v < 0:
                raise RuntimeError("bad metric")
            self.values.append(v)

    prom = ModuleType("prometheus_client")
    prom.Gauge = Gauge
    monkeypatch.setitem(sys.modules, "prometheus_client", prom)

    base_manager._prometheus_gauges = None
    base_manager.update_prometheus_metrics({"cpu_percent": 5, "ram_percent": 7, "gpu_utilization_pct": -1, "gpu_temperature_c": 66})
    assert isinstance(base_manager._prometheus_gauges, dict)

    base_manager._prometheus_gauges = None
    monkeypatch.delitem(sys.modules, "prometheus_client", raising=False)
    base_manager.update_prometheus_metrics({"cpu_percent": 5})
    assert base_manager._prometheus_gauges == {}
    base_manager.update_prometheus_metrics({})


def test_dependency_health_report_and_close(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, base_manager: SystemHealthManager) -> None:
    base_manager.cfg = SimpleNamespace(
        HEALTHCHECK_CONNECT_TIMEOUT_MS=25,
        REDIS_URL="redis://cache.internal",
        DATABASE_URL=f"sqlite:///{tmp_path / 'ok.db'}",
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
    )
    (tmp_path / "ok.db").write_text("x", encoding="utf-8")

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("managers.system_health.socket.create_connection", lambda *_a, **_k: _Ctx())
    redis_state = base_manager.check_redis()
    assert redis_state["mode"] == "tcp"
    assert redis_state["target"].endswith(":6379")

    deps = base_manager.get_dependency_health()
    assert "database" in deps
    assert base_manager.check_database()["healthy"] is True

    base_manager._nvml_initialized = True
    pynvml = ModuleType("pynvml")
    pynvml.nvmlShutdown = lambda: (_ for _ in ()).throw(RuntimeError("shutdown"))
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)
    base_manager.close()
    assert base_manager._nvml_initialized is False


def test_full_report_gpu_and_del(monkeypatch: pytest.MonkeyPatch, base_manager: SystemHealthManager) -> None:
    base_manager.get_cpu_usage = lambda *_a, **_k: None
    base_manager.get_memory_info = lambda: {}
    base_manager.check_ollama = lambda: False
    base_manager.get_gpu_info = lambda: {
        "available": True,
        "cuda_version": "12.4",
        "driver_version": "550",
        "devices": [
            {
                "id": 0,
                "name": "A100",
                "compute_capability": "8.0",
                "allocated_gb": 1.0,
                "total_vram_gb": 4.0,
                "free_gb": 3.0,
                "temperature_c": 70,
                "utilization_pct": 55,
            }
        ],
    }
    captured = {}
    base_manager.update_prometheus_metrics = lambda payload: captured.update(payload)

    report = base_manager.full_report()
    assert "CPU       : psutil kurulu değil" in report
    assert "GPU 0" in report
    assert captured["gpu_temperature_c"] == 70

    called = {"close": 0}
    base_manager.close = lambda: called.__setitem__("close", called["close"] + 1)
    base_manager.__del__()
    assert called["close"] == 1
