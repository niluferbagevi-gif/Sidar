"""
managers/system_health.py — ek birim testleri (coverage artırımı).

Hedeflenen satırlar:
  123-126  : by_user Prometheus etiketleri
  186-187  : _check_gpu Exception dalı
  195-210  : _init_nvml hata yolları (WSL2 ve normal)
  222-229  : get_cpu_usage (psutil yok / psutil hata)
  233-245  : get_memory_info (psutil yok / psutil hata)
  261-311  : get_gpu_info (GPU yok / cihaz döngüsü / exception)
  315-339  : _get_driver_version (nvml initialized / fallback / smi bulunamadı)
  351-374  : optimize_gpu_memory (GPU var/yok / exception)
  390-431  : update_prometheus_metrics (ilk kurulum / gauge set)
  451-469  : get_health_summary (dependency healthcheck / degraded)
  520-552  : full_report (CPU yok / GPU var / GPU sıcaklık+kullanım satırları)
  575-588  : close / __del__
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch, mock_open


# ──────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────────────────────────────────────────

def _get_sh():
    """Her testte temiz bir managers.system_health modülü döndürür."""
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        OLLAMA_URL = "http://localhost:11434/api"
        OLLAMA_TIMEOUT = 5
        HEALTHCHECK_CONNECT_TIMEOUT_MS = 250
        REDIS_URL = ""
        DATABASE_URL = ""
        ENABLE_DEPENDENCY_HEALTHCHECKS = False

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    for mod in list(sys.modules):
        if mod in ("managers.system_health",):
            del sys.modules[mod]
    import managers.system_health as sh
    return sh


def _make_manager(**kwargs):
    """use_gpu=False ile basit bir SystemHealthManager örneği."""
    sh = _get_sh()
    mgr = sh.SystemHealthManager(use_gpu=False, **kwargs)
    return mgr, sh


# ══════════════════════════════════════════════════════════════
# render_llm_metrics_prometheus — by_user satırları (123-126)
# ══════════════════════════════════════════════════════════════

class TestRenderByUser:
    def test_by_user_labels_appear_in_output(self):
        sh = _get_sh()
        snapshot = {
            "by_user": {
                "user_42": {"calls": 3, "cost_usd": 0.05, "total_tokens": 150},
            }
        }
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert 'user_id="user_42"' in result
        assert "sidar_llm_user_calls_total" in result
        assert "sidar_llm_user_cost_total_usd" in result
        assert "sidar_llm_user_tokens_total" in result

    def test_multiple_users_all_present(self):
        sh = _get_sh()
        snapshot = {
            "by_user": {
                "alice": {"calls": 1, "cost_usd": 0.01, "total_tokens": 50},
                "bob": {"calls": 2, "cost_usd": 0.02, "total_tokens": 100},
            }
        }
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert 'user_id="alice"' in result
        assert 'user_id="bob"' in result

    def test_none_user_id_becomes_anonymous(self):
        sh = _get_sh()
        snapshot = {
            "by_user": {
                None: {"calls": 1, "cost_usd": 0.0, "total_tokens": 0},
            }
        }
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert 'user_id="anonymous"' in result

    def test_by_user_empty_dict(self):
        sh = _get_sh()
        snapshot = {"by_user": {}}
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert isinstance(result, str)
        assert "sidar_llm_calls_total 0" in result


# ══════════════════════════════════════════════════════════════
# _check_gpu — exception dalı (186-187)
# ══════════════════════════════════════════════════════════════

class TestCheckGpu:
    def test_check_gpu_returns_false_when_torch_raises(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        # torch kullanılabilir gibi görünüyor ama cuda.is_available() raise ediyor
        mgr._torch_available = True
        mgr.use_gpu = True

        torch_stub = types.ModuleType("torch")
        torch_stub.cuda = types.SimpleNamespace(is_available=lambda: (_ for _ in ()).throw(RuntimeError("no cuda")))
        # Daha temiz yol: callable ile exception fırlat
        def _raise():
            raise RuntimeError("no cuda")
        torch_stub.cuda = types.SimpleNamespace(is_available=_raise)
        with patch.dict(sys.modules, {"torch": torch_stub}):
            result = mgr._check_gpu()
        assert result is False

    def test_check_gpu_returns_false_when_use_gpu_false(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        assert mgr._gpu_available is False

    def test_check_gpu_false_when_torch_unavailable(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr._torch_available = False
        mgr.use_gpu = True
        result = mgr._check_gpu()
        assert result is False


# ══════════════════════════════════════════════════════════════
# _init_nvml — hata yolları (195-210)
# ══════════════════════════════════════════════════════════════

class TestInitNvml:
    def test_init_nvml_success(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr._nvml_initialized = False

        pynvml_stub = types.ModuleType("pynvml")
        pynvml_stub.nvmlInit = lambda: None
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            mgr._init_nvml()
        assert mgr._nvml_initialized is True

    def test_init_nvml_failure_non_wsl2(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr._nvml_initialized = False

        pynvml_stub = types.ModuleType("pynvml")
        def _raise():
            raise RuntimeError("nvml init failed")
        pynvml_stub.nvmlInit = _raise
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            # /proc/sys/kernel/osrelease okuma — microsoft içermiyor
            with patch("builtins.open", mock_open(read_data="Linux 6.1.0")):
                mgr._init_nvml()
        assert mgr._nvml_initialized is False

    def test_init_nvml_failure_wsl2(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr._nvml_initialized = False

        pynvml_stub = types.ModuleType("pynvml")
        def _raise():
            raise RuntimeError("nvml init failed")
        pynvml_stub.nvmlInit = _raise
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            with patch("builtins.open", mock_open(read_data="5.15.90.1-microsoft-standard-WSL2")):
                mgr._init_nvml()
        assert mgr._nvml_initialized is False

    def test_init_nvml_failure_proc_unreadable(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr._nvml_initialized = False

        pynvml_stub = types.ModuleType("pynvml")
        def _raise():
            raise RuntimeError("nvml init failed")
        pynvml_stub.nvmlInit = _raise
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            with patch("builtins.open", side_effect=OSError("not found")):
                mgr._init_nvml()
        assert mgr._nvml_initialized is False


# ══════════════════════════════════════════════════════════════
# get_cpu_usage (222-229)
# ══════════════════════════════════════════════════════════════

class TestGetCpuUsage:
    def test_returns_none_when_psutil_unavailable(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = False
        assert mgr.get_cpu_usage() is None

    def test_returns_float_when_psutil_available(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        psutil_stub = types.ModuleType("psutil")
        psutil_stub.cpu_percent = lambda interval=0.0: 42.5
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            result = mgr.get_cpu_usage()
        assert result == 42.5

    def test_returns_none_when_psutil_raises(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        psutil_stub = types.ModuleType("psutil")
        def _raise(**kwargs):
            raise RuntimeError("sensor error")
        psutil_stub.cpu_percent = _raise
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            result = mgr.get_cpu_usage()
        assert result is None

    def test_explicit_interval_overrides_default(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        called_with = {}
        psutil_stub = types.ModuleType("psutil")
        def _cpu(interval=0.0):
            called_with["interval"] = interval
            return 10.0
        psutil_stub.cpu_percent = _cpu
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            mgr.get_cpu_usage(interval=0.5)
        assert called_with["interval"] == 0.5

    def test_negative_interval_clamped_to_zero(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        called_with = {}
        psutil_stub = types.ModuleType("psutil")
        def _cpu(interval=0.0):
            called_with["interval"] = interval
            return 10.0
        psutil_stub.cpu_percent = _cpu
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            mgr.get_cpu_usage(interval=-1.0)
        assert called_with["interval"] == 0.0


# ══════════════════════════════════════════════════════════════
# get_memory_info (233-245)
# ══════════════════════════════════════════════════════════════

class TestGetMemoryInfo:
    def test_returns_empty_when_psutil_unavailable(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = False
        assert mgr.get_memory_info() == {}

    def test_returns_dict_with_keys_when_psutil_available(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        vm = types.SimpleNamespace(total=16e9, used=8e9, available=8e9, percent=50.0)
        psutil_stub = types.ModuleType("psutil")
        psutil_stub.virtual_memory = lambda: vm
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            result = mgr.get_memory_info()
        assert result["total_gb"] == 16.0
        assert result["percent"] == 50.0
        assert "used_gb" in result
        assert "available_gb" in result

    def test_returns_empty_when_psutil_raises(self):
        mgr, _ = _make_manager()
        mgr._psutil_available = True
        psutil_stub = types.ModuleType("psutil")
        psutil_stub.virtual_memory = lambda: (_ for _ in ()).throw(RuntimeError("err"))
        # Cleaner:
        def _raise():
            raise RuntimeError("memory read error")
        psutil_stub.virtual_memory = _raise
        with patch.dict(sys.modules, {"psutil": psutil_stub}):
            result = mgr.get_memory_info()
        assert result == {}


# ══════════════════════════════════════════════════════════════
# get_gpu_info (261-311)
# ══════════════════════════════════════════════════════════════

class TestGetGpuInfo:
    def test_returns_unavailable_when_gpu_not_available(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = False
        info = mgr.get_gpu_info()
        assert info["available"] is False
        assert "reason" in info

    def test_returns_device_list_when_gpu_available(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = True
        mgr._nvml_initialized = False

        props = types.SimpleNamespace(
            total_memory=8e9,
            name="TestGPU",
            major=8,
            minor=6,
        )
        torch_stub = types.ModuleType("torch")
        torch_stub.cuda = types.SimpleNamespace(
            device_count=lambda: 1,
            get_device_properties=lambda i: props,
            memory_allocated=lambda i: 1e9,
            memory_reserved=lambda i: 2e9,
        )
        torch_stub.version = types.SimpleNamespace(cuda="11.8")
        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch.object(mgr, "_get_driver_version", return_value="525.89"):
                info = mgr.get_gpu_info()

        assert info["available"] is True
        assert info["device_count"] == 1
        assert len(info["devices"]) == 1
        dev = info["devices"][0]
        assert dev["name"] == "TestGPU"
        assert dev["compute_capability"] == "8.6"
        assert dev["total_vram_gb"] == 8.0
        assert dev["cuda_version"] == "11.8"

    def test_returns_error_on_torch_exception(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = True

        torch_stub = types.ModuleType("torch")
        def _raise():
            raise RuntimeError("CUDA init failure")
        torch_stub.cuda = types.SimpleNamespace(device_count=_raise)
        with patch.dict(sys.modules, {"torch": torch_stub}):
            info = mgr.get_gpu_info()

        assert info["available"] is False
        assert "error" in info

    def test_gpu_info_free_gb_calculation(self):
        """free_gb = total_vram - reserved"""
        mgr, _ = _make_manager()
        mgr._gpu_available = True
        mgr._nvml_initialized = False

        props = types.SimpleNamespace(
            total_memory=10e9, name="FakeGPU", major=7, minor=5
        )
        torch_stub = types.ModuleType("torch")
        torch_stub.cuda = types.SimpleNamespace(
            device_count=lambda: 1,
            get_device_properties=lambda i: props,
            memory_allocated=lambda i: 3e9,
            memory_reserved=lambda i: 4e9,
        )
        torch_stub.version = types.SimpleNamespace(cuda="12.0")
        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch.object(mgr, "_get_driver_version", return_value="N/A"):
                info = mgr.get_gpu_info()

        dev = info["devices"][0]
        # free_gb = total - reserved = 10 - 4 = 6
        assert dev["free_gb"] == 6.0


# ══════════════════════════════════════════════════════════════
# _get_driver_version (315-339)
# ══════════════════════════════════════════════════════════════

class TestGetDriverVersion:
    def test_returns_version_from_nvml(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = True
        pynvml_stub = types.ModuleType("pynvml")
        pynvml_stub.nvmlSystemGetDriverVersion = lambda: "525.89.02"
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            result = mgr._get_driver_version()
        assert result == "525.89.02"

    def test_falls_back_to_nvidia_smi_when_nvml_raises(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = True
        pynvml_stub = types.ModuleType("pynvml")
        def _raise():
            raise RuntimeError("nvml error")
        pynvml_stub.nvmlSystemGetDriverVersion = _raise
        fake_result = types.SimpleNamespace(
            stdout="525.89.02\n",
            returncode=0,
        )
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            with patch("subprocess.run", return_value=fake_result):
                result = mgr._get_driver_version()
        assert result == "525.89.02"

    def test_returns_na_when_nvidia_smi_empty_output(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = False
        fake_result = types.SimpleNamespace(stdout="", returncode=0)
        with patch("subprocess.run", return_value=fake_result):
            result = mgr._get_driver_version()
        assert result == "N/A"

    def test_returns_na_when_nvidia_smi_not_found(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = False
        with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
            result = mgr._get_driver_version()
        assert result == "N/A"

    def test_returns_na_when_nvidia_smi_raises_generic(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = False
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            result = mgr._get_driver_version()
        assert result == "N/A"

    def test_returns_driver_version_from_nvidia_smi_when_not_nvml_initialized(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = False
        fake_result = types.SimpleNamespace(stdout="535.104.05\n", returncode=0)
        with patch("subprocess.run", return_value=fake_result):
            result = mgr._get_driver_version()
        assert result == "535.104.05"


# ══════════════════════════════════════════════════════════════
# optimize_gpu_memory (351-374)
# ══════════════════════════════════════════════════════════════

class TestOptimizeGpuMemory:
    def test_runs_without_gpu(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = False
        result = mgr.optimize_gpu_memory()
        assert "GPU VRAM" in result
        assert "GC" in result or "gc" in result.lower() or "Python" in result

    def test_runs_with_gpu(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = True

        torch_stub = types.ModuleType("torch")
        call_log = []
        def _reserved():
            val = 500.0 if not call_log else 200.0
            call_log.append(val)
            return val * 1e6
        torch_stub.cuda = types.SimpleNamespace(
            memory_reserved=_reserved,
            empty_cache=lambda: None,
        )
        with patch.dict(sys.modules, {"torch": torch_stub}):
            result = mgr.optimize_gpu_memory()
        assert "GPU VRAM" in result
        assert "Python GC" in result

    def test_handles_gpu_exception_gc_still_runs(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = True

        torch_stub = types.ModuleType("torch")
        def _raise():
            raise RuntimeError("cuda error")
        torch_stub.cuda = types.SimpleNamespace(
            memory_reserved=_raise,
            empty_cache=lambda: None,
        )
        with patch.dict(sys.modules, {"torch": torch_stub}):
            result = mgr.optimize_gpu_memory()
        # GC çalışmalı ve GPU cache hatası mesajda görünmeli
        assert "Python GC" in result
        assert "GPU cache hatası" in result

    def test_freed_mb_is_positive_or_zero(self):
        mgr, _ = _make_manager()
        mgr._gpu_available = True

        call_count = [0]
        def _reserved():
            call_count[0] += 1
            return 800e6 if call_count[0] == 1 else 600e6
        torch_stub = types.ModuleType("torch")
        torch_stub.cuda = types.SimpleNamespace(
            memory_reserved=_reserved,
            empty_cache=lambda: None,
        )
        with patch.dict(sys.modules, {"torch": torch_stub}):
            result = mgr.optimize_gpu_memory()
        # 200 MB boşaltıldı
        assert "200.0 MB" in result


# ══════════════════════════════════════════════════════════════
# update_prometheus_metrics (387-431)
# ══════════════════════════════════════════════════════════════

class TestUpdatePrometheusMetrics:
    def test_empty_dict_returns_early(self):
        mgr, _ = _make_manager()
        # Should not raise anything
        mgr.update_prometheus_metrics({})

    def test_sets_gauge_values(self):
        mgr, _ = _make_manager()
        gauge_mock = MagicMock()
        mgr._prometheus_gauges = {
            "cpu_percent": gauge_mock,
            "ram_percent": gauge_mock,
            "gpu_util_percent": gauge_mock,
            "gpu_temp_c": gauge_mock,
        }
        mgr.update_prometheus_metrics({
            "cpu_percent": 55.0,
            "ram_percent": 70.0,
            "gpu_utilization_pct": 30.0,
            "gpu_temperature_c": 65.0,
        })
        assert gauge_mock.set.call_count == 4

    def test_skips_none_values(self):
        mgr, _ = _make_manager()
        gauge_mock = MagicMock()
        mgr._prometheus_gauges = {
            "cpu_percent": gauge_mock,
            "ram_percent": gauge_mock,
            "gpu_util_percent": gauge_mock,
            "gpu_temp_c": gauge_mock,
        }
        mgr.update_prometheus_metrics({
            "cpu_percent": 55.0,
            # ram_percent eksik → None → skip
        })
        # Sadece cpu_percent için set çağrılmalı
        assert gauge_mock.set.call_count == 1

    def test_creates_prometheus_gauges_when_none(self):
        mgr, _ = _make_manager()
        mgr._prometheus_gauges = None

        gauge_instance = MagicMock()
        gauge_cls = MagicMock(return_value=gauge_instance)
        prometheus_stub = types.ModuleType("prometheus_client")
        prometheus_stub.Gauge = gauge_cls

        with patch.dict(sys.modules, {"prometheus_client": prometheus_stub}):
            mgr.update_prometheus_metrics({"cpu_percent": 10.0})
        # Gauge sınıfı çağrılmalı
        assert gauge_cls.called

    def test_handles_prometheus_client_not_available(self):
        mgr, _ = _make_manager()
        mgr._prometheus_gauges = None

        with patch.dict(sys.modules, {"prometheus_client": None}):
            # ImportError yerine None → __import__ hatası veya None modülü
            # Direkt ImportError simüle edelim
            original = sys.modules.pop("prometheus_client", None)
            try:
                # prometheus_client bulunamıyor
                mgr.update_prometheus_metrics({"cpu_percent": 10.0})
            finally:
                if original is not None:
                    sys.modules["prometheus_client"] = original

    def test_handles_gauge_set_exception(self):
        mgr, _ = _make_manager()
        broken_gauge = MagicMock()
        broken_gauge.set.side_effect = Exception("gauge error")
        mgr._prometheus_gauges = {
            "cpu_percent": broken_gauge,
            "ram_percent": MagicMock(),
            "gpu_util_percent": MagicMock(),
            "gpu_temp_c": MagicMock(),
        }
        # Should not raise — continues on exception
        mgr.update_prometheus_metrics({"cpu_percent": 50.0})

    def test_empty_prometheus_gauges_dict_returns_early(self):
        mgr, _ = _make_manager()
        mgr._prometheus_gauges = {}  # boş dict → early return
        # should not raise
        mgr.update_prometheus_metrics({"cpu_percent": 50.0})


# ══════════════════════════════════════════════════════════════
# get_health_summary (437-456)
# ══════════════════════════════════════════════════════════════

class TestGetHealthSummary:
    def test_returns_healthy_status_by_default(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 10.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {"percent": 30.0})
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False})
        monkeypatch.setattr(mgr, "check_ollama", lambda: True)

        summary = mgr.get_health_summary()
        assert summary["status"] == "healthy"
        assert summary["cpu_percent"] == 10.0
        assert summary["ram_percent"] == 30.0

    def test_includes_dependencies_when_enabled(self, monkeypatch):
        mgr, _ = _make_manager()
        mgr.cfg.ENABLE_DEPENDENCY_HEALTHCHECKS = True
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 5.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {"percent": 20.0})
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False})
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_dependency_health", lambda: {
            "redis": {"healthy": True},
            "database": {"healthy": True},
        })

        summary = mgr.get_health_summary()
        assert "dependencies" in summary
        assert summary["status"] == "healthy"

    def test_cpu_none_defaults_to_zero(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: None)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {})
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False})
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)

        summary = mgr.get_health_summary()
        assert summary["cpu_percent"] == 0.0
        assert summary["ram_percent"] == 0.0


# ══════════════════════════════════════════════════════════════
# get_dependency_health (458-463)
# ══════════════════════════════════════════════════════════════

class TestGetDependencyHealth:
    def test_returns_redis_and_database_keys(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "check_redis", lambda: {"healthy": True, "kind": "redis"})
        monkeypatch.setattr(mgr, "check_database", lambda: {"healthy": True, "kind": "database"})
        deps = mgr.get_dependency_health()
        assert "redis" in deps
        assert "database" in deps


# ══════════════════════════════════════════════════════════════
# full_report (507-567)
# ══════════════════════════════════════════════════════════════

class TestFullReport:
    def test_cpu_none_shows_psutil_missing_message(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: None)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {})
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False, "reason": "Yok"})
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "psutil kurulu değil" in report

    def test_gpu_available_with_devices_shows_in_report(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 25.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {
            "total_gb": 32.0, "used_gb": 10.0, "available_gb": 22.0, "percent": 31.25
        })
        monkeypatch.setattr(mgr, "check_ollama", lambda: True)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {
            "available": True,
            "cuda_version": "11.8",
            "driver_version": "525.89",
            "devices": [{
                "id": 0,
                "name": "RTX 3090",
                "compute_capability": "8.6",
                "total_vram_gb": 24.0,
                "allocated_gb": 5.0,
                "reserved_gb": 6.0,
                "free_gb": 18.0,
            }]
        })
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "RTX 3090" in report
        assert "CUDA" in report
        assert "525.89" in report

    def test_gpu_devices_with_temperature_and_utilization(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 50.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {
            "total_gb": 16.0, "used_gb": 8.0, "available_gb": 8.0, "percent": 50.0
        })
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {
            "available": True,
            "cuda_version": "12.0",
            "driver_version": "535.0",
            "devices": [{
                "id": 0,
                "name": "A100",
                "compute_capability": "8.0",
                "total_vram_gb": 80.0,
                "allocated_gb": 40.0,
                "reserved_gb": 45.0,
                "free_gb": 35.0,
                "temperature_c": 72,
                "utilization_pct": 85,
            }]
        })
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "72°C" in report
        assert "%85 GPU" in report

    def test_gpu_unavailable_shows_reason(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 10.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {
            "total_gb": 8.0, "used_gb": 2.0, "available_gb": 6.0, "percent": 25.0
        })
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {
            "available": False, "reason": "CUDA bulunamadı"
        })
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "CUDA bulunamadı" in report

    def test_ollama_online_shown_in_report(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 5.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {
            "total_gb": 8.0, "used_gb": 1.0, "available_gb": 7.0, "percent": 12.5
        })
        monkeypatch.setattr(mgr, "check_ollama", lambda: True)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False, "reason": "Yok"})
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "Çevrimiçi" in report

    def test_ollama_offline_shown_in_report(self, monkeypatch):
        mgr, _ = _make_manager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *a, **k: 5.0)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {})
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False, "reason": "Yok"})
        monkeypatch.setattr(mgr, "update_prometheus_metrics", lambda d: None)

        report = mgr.full_report()
        assert "Çevrimdışı" in report


# ══════════════════════════════════════════════════════════════
# close / __del__ (573-588)
# ══════════════════════════════════════════════════════════════

class TestClose:
    def test_close_shuts_down_nvml(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = True
        shutdown_called = []
        pynvml_stub = types.ModuleType("pynvml")
        pynvml_stub.nvmlShutdown = lambda: shutdown_called.append(True)
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            mgr.close()
        assert shutdown_called
        assert mgr._nvml_initialized is False

    def test_close_is_noop_when_not_initialized(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = False
        # Should not raise
        mgr.close()
        assert mgr._nvml_initialized is False

    def test_close_is_idempotent(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = True
        pynvml_stub = types.ModuleType("pynvml")
        pynvml_stub.nvmlShutdown = lambda: None
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            mgr.close()
            mgr.close()  # ikinci çağrı güvenli olmalı
        assert mgr._nvml_initialized is False

    def test_close_handles_nvml_exception(self):
        mgr, _ = _make_manager()
        mgr._nvml_initialized = True
        pynvml_stub = types.ModuleType("pynvml")
        def _raise():
            raise RuntimeError("nvml shutdown error")
        pynvml_stub.nvmlShutdown = _raise
        with patch.dict(sys.modules, {"pynvml": pynvml_stub}):
            mgr.close()  # should not raise
        assert mgr._nvml_initialized is False

    def test_del_calls_close(self):
        mgr, _ = _make_manager()
        close_called = []
        original_close = mgr.close
        mgr.close = lambda: close_called.append(True)
        mgr.__del__()
        assert close_called

    def test_repr_contains_gpu_info(self):
        mgr, _ = _make_manager()
        r = repr(mgr)
        assert "SystemHealthManager" in r
        assert "gpu=" in r


# ══════════════════════════════════════════════════════════════
# check_ollama (376-385)
# ══════════════════════════════════════════════════════════════

class TestCheckOllama:
    def test_returns_true_when_status_200(self):
        mgr, _ = _make_manager()

        class _Resp:
            status_code = 200

        fake_requests = types.SimpleNamespace(get=lambda *a, **k: _Resp())
        with patch.dict(sys.modules, {"requests": fake_requests}):
            result = mgr.check_ollama()
        assert result is True

    def test_returns_false_when_status_503(self):
        mgr, _ = _make_manager()

        class _Resp:
            status_code = 503

        fake_requests = types.SimpleNamespace(get=lambda *a, **k: _Resp())
        with patch.dict(sys.modules, {"requests": fake_requests}):
            result = mgr.check_ollama()
        assert result is False

    def test_returns_false_on_any_exception(self):
        mgr, _ = _make_manager()
        fake_requests = types.SimpleNamespace(
            get=lambda *a, **k: (_ for _ in ()).throw(ConnectionError("refused"))
        )
        def _raise(*a, **k):
            raise ConnectionError("refused")
        fake_requests = types.SimpleNamespace(get=_raise)
        with patch.dict(sys.modules, {"requests": fake_requests}):
            result = mgr.check_ollama()
        assert result is False


# ══════════════════════════════════════════════════════════════
# _tcp_dependency_health (465-471)
# ══════════════════════════════════════════════════════════════

class TestTcpDependencyHealth:
    def test_returns_healthy_on_success(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)

        class _FakeConn:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(sh.socket, "create_connection", lambda *a, **k: _FakeConn())
        result = mgr._tcp_dependency_health("localhost", 6379, label="redis")
        assert result["healthy"] is True
        assert result["kind"] == "redis"

    def test_uses_timeout_from_config(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr.cfg.HEALTHCHECK_CONNECT_TIMEOUT_MS = 500
        captured = {}

        class _FakeConn:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _fake_create(addr, timeout):
            captured["timeout"] = timeout
            return _FakeConn()

        monkeypatch.setattr(sh.socket, "create_connection", _fake_create)
        mgr._tcp_dependency_health("host", 5432, label="database")
        assert captured["timeout"] == pytest.approx(0.5)

    def test_minimum_timeout_50ms(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        mgr.cfg.HEALTHCHECK_CONNECT_TIMEOUT_MS = 0  # below minimum
        captured = {}

        class _FakeConn:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _fake_create(addr, timeout):
            captured["timeout"] = timeout
            return _FakeConn()

        monkeypatch.setattr(sh.socket, "create_connection", _fake_create)
        mgr._tcp_dependency_health("host", 5432, label="database")
        # minimum 50ms = 0.05s
        assert captured["timeout"] == pytest.approx(0.05)


import pytest
