"""
Runtime tests for managers/system_health.py — targets uncovered branches:
  _check_import ImportError, _check_gpu exception, _init_nvml WSL2/non-WSL2,
  get_cpu_usage psutil unavailable/exception, get_memory_info psutil unavailable/exception,
  get_gpu_info pynvml exception and generic exception, _get_driver_version fallbacks,
  optimize_gpu_memory gpu_error path, check_ollama exception,
  update_prometheus_metrics empty/None/exception paths,
  get_health_summary, full_report psutil-unavailable + GPU-available paths,
  close() with nvml, __del__, __repr__.
"""
import sys
import types
import threading
import importlib
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─── Module loader ──────────────────────────────────────────────────────────

def _stub_config():
    """Inject a minimal config stub so system_health.py can import it."""
    if "config" in sys.modules:
        return  # already available
    cfg_mod = types.ModuleType("config")
    class _Cfg:
        OLLAMA_URL = "http://localhost:11434/api"
        OLLAMA_TIMEOUT = 5
    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod


def _load_shm_module():
    _stub_config()
    spec = importlib.util.spec_from_file_location(
        "shm_rt", Path("managers/system_health.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHM = _load_shm_module()
SystemHealthManager = SHM.SystemHealthManager


# ─── Helper ──────────────────────────────────────────────────────────────────

def _make_mgr(**kwargs):
    """Create a bare SystemHealthManager without real hardware checks."""
    mgr = SystemHealthManager.__new__(SystemHealthManager)
    mgr._lock = threading.RLock()
    mgr.cpu_sample_interval = 0.0
    mgr.use_gpu = kwargs.get("use_gpu", False)
    mgr._torch_available = kwargs.get("torch", False)
    mgr._psutil_available = kwargs.get("psutil", False)
    mgr._pynvml_available = kwargs.get("pynvml", False)
    mgr._gpu_available = kwargs.get("gpu", False)
    mgr._nvml_initialized = kwargs.get("nvml_init", False)
    mgr._prometheus_gauges = kwargs.get("prometheus_gauges", None)
    mgr.cfg = types.SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=5,
    )
    return mgr


# ─── _check_import ──────────────────────────────────────────────────────────

def test_check_import_importerror_returns_false():
    """Covers lines 73-74: ImportError in _check_import."""
    result = SystemHealthManager._check_import("__nonexistent_module_xyz__")
    assert result is False


def test_check_import_existing_module_returns_true():
    result = SystemHealthManager._check_import("os")
    assert result is True


# ─── _check_gpu ─────────────────────────────────────────────────────────────

def test_check_gpu_exception_returns_false():
    """Covers lines 82-83: generic exception in _check_gpu."""
    mgr = _make_mgr(use_gpu=True, torch=True)

    def raising_cuda():
        raise RuntimeError("gpu check fail")

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=raising_cuda)

    with patch.dict(sys.modules, {"torch": fake_torch}):
        result = mgr._check_gpu()
    assert result is False


def test_check_gpu_returns_false_when_use_gpu_false():
    mgr = _make_mgr(use_gpu=False, torch=True)
    result = mgr._check_gpu()
    assert result is False


# ─── _init_nvml ─────────────────────────────────────────────────────────────

def test_init_nvml_exception_non_wsl2_path():
    """Covers lines 91-106: pynvml exception, /proc not accessible (not WSL2)."""
    mgr = _make_mgr(pynvml=True, gpu=True)
    mgr._nvml_initialized = False

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlInit = lambda: (_ for _ in ()).throw(RuntimeError("nvml init fail"))

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        with patch("builtins.open", side_effect=OSError("no proc")):
            mgr._init_nvml()

    assert mgr._nvml_initialized is False


def test_init_nvml_exception_wsl2_path():
    """Covers WSL2 detection branch in _init_nvml (lines 98-105)."""
    import io
    mgr = _make_mgr(pynvml=True, gpu=True)
    mgr._nvml_initialized = False

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlInit = lambda: (_ for _ in ()).throw(RuntimeError("blocked"))

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        with patch("builtins.open", return_value=io.StringIO("5.15.0-microsoft-standard")):
            mgr._init_nvml()

    assert mgr._nvml_initialized is False


def test_init_nvml_exception_osrelease_read_also_fails():
    """Covers inner except (line 96-97): /proc osrelease read also raises."""
    import builtins
    mgr = _make_mgr(pynvml=True, gpu=True)
    mgr._nvml_initialized = False

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlInit = lambda: (_ for _ in ()).throw(RuntimeError("fail"))

    original_open = builtins.open

    def mock_open(path, *args, **kwargs):
        if "osrelease" in str(path):
            raise OSError("no access")
        return original_open(path, *args, **kwargs)

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        with patch("builtins.open", side_effect=mock_open):
            mgr._init_nvml()

    assert mgr._nvml_initialized is False


# ─── get_cpu_usage ──────────────────────────────────────────────────────────

def test_get_cpu_usage_psutil_unavailable_returns_none():
    """Covers line 119: psutil not available."""
    mgr = _make_mgr(psutil=False)
    result = mgr.get_cpu_usage()
    assert result is None


def test_get_cpu_usage_exception_returns_none():
    """Covers lines 124-125: exception in psutil.cpu_percent."""
    mgr = _make_mgr(psutil=True)

    fake_psutil = types.ModuleType("psutil")
    fake_psutil.cpu_percent = lambda interval: (_ for _ in ()).throw(RuntimeError("cpu fail"))

    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = mgr.get_cpu_usage()
    assert result is None


def test_get_cpu_usage_with_custom_interval():
    """get_cpu_usage passes the interval parameter correctly."""
    mgr = _make_mgr(psutil=True)

    intervals = []
    fake_psutil = types.ModuleType("psutil")
    fake_psutil.cpu_percent = lambda interval: intervals.append(interval) or 45.0

    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = mgr.get_cpu_usage(interval=0.1)
    assert result == 45.0
    assert intervals[0] == 0.1


# ─── get_memory_info ────────────────────────────────────────────────────────

def test_get_memory_info_psutil_unavailable_returns_empty():
    """Covers line 130: psutil not available."""
    mgr = _make_mgr(psutil=False)
    result = mgr.get_memory_info()
    assert result == {}


def test_get_memory_info_exception_returns_empty():
    """Covers lines 140-141: exception in psutil.virtual_memory."""
    mgr = _make_mgr(psutil=True)

    fake_psutil = types.ModuleType("psutil")
    fake_psutil.virtual_memory = lambda: (_ for _ in ()).throw(RuntimeError("mem fail"))

    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = mgr.get_memory_info()
    assert result == {}


# ─── get_gpu_info ───────────────────────────────────────────────────────────

def test_get_gpu_info_pynvml_query_exception():
    """Covers lines 193-195: pynvml GPU query exception inside device loop."""
    mgr = _make_mgr(gpu=True, torch=True, nvml_init=True)

    props = types.SimpleNamespace(
        name="TestGPU", major=8, minor=0,
        total_memory=8_000_000_000,
    )
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(
        device_count=lambda: 1,
        get_device_properties=lambda i: props,
        memory_allocated=lambda i: 1_000_000_000,
        memory_reserved=lambda i: 2_000_000_000,
    )
    fake_torch.version = types.SimpleNamespace(cuda="12.1")

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlDeviceGetHandleByIndex = lambda i: (_ for _ in ()).throw(RuntimeError("pynvml query fail"))

    with patch.dict(sys.modules, {"torch": fake_torch, "pynvml": fake_pynvml}):
        mgr._get_driver_version = lambda: "555.00"
        result = mgr.get_gpu_info()

    assert result["available"] is True
    assert len(result["devices"]) == 1
    # temperature_c should NOT be set since pynvml raised
    assert "temperature_c" not in result["devices"][0]


def test_get_gpu_info_generic_exception_returns_error():
    """Covers lines 206-207: generic exception from torch operations."""
    mgr = _make_mgr(gpu=True, torch=True, nvml_init=False)

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(
        device_count=lambda: (_ for _ in ()).throw(RuntimeError("torch device_count fail"))
    )
    fake_torch.version = types.SimpleNamespace(cuda="12.1")

    with patch.dict(sys.modules, {"torch": fake_torch}):
        result = mgr.get_gpu_info()

    assert result["available"] is False
    assert "error" in result


def test_get_gpu_info_not_available():
    """get_gpu_info returns not available reason when GPU disabled."""
    mgr = _make_mgr(gpu=False)
    result = mgr.get_gpu_info()
    assert result["available"] is False
    assert "reason" in result


# ─── _get_driver_version ────────────────────────────────────────────────────

def test_get_driver_version_nvml_exception_then_smi_success():
    """Covers lines 215-216: pynvml driver version raises, falls back to nvidia-smi."""
    mgr = _make_mgr(nvml_init=True)

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlSystemGetDriverVersion = lambda: (_ for _ in ()).throw(RuntimeError("driver fail"))

    fake_result = types.SimpleNamespace(stdout="535.86.10\n", returncode=0)

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        with patch("subprocess.run", return_value=fake_result):
            result = mgr._get_driver_version()

    assert result == "535.86.10"


def test_get_driver_version_nvidia_smi_filenotfounderror():
    """Covers lines 231-232: nvidia-smi not found."""
    mgr = _make_mgr(nvml_init=False)

    with patch("subprocess.run", side_effect=FileNotFoundError("no nvidia-smi")):
        result = mgr._get_driver_version()

    assert result == "N/A"


def test_get_driver_version_nvidia_smi_generic_exception():
    """Covers lines 233-234: nvidia-smi generic exception."""
    mgr = _make_mgr(nvml_init=False)

    with patch("subprocess.run", side_effect=OSError("subprocess fail")):
        result = mgr._get_driver_version()

    assert result == "N/A"


def test_get_driver_version_nvidia_smi_empty_output():
    """Covers lines 227-230: nvidia-smi returns empty stdout."""
    mgr = _make_mgr(nvml_init=False)

    fake_result = types.SimpleNamespace(stdout="   \n", returncode=0)
    with patch("subprocess.run", return_value=fake_result):
        result = mgr._get_driver_version()

    assert result == "N/A"


def test_get_driver_version_no_nvml_no_smi_returns_na():
    """When neither pynvml nor nvidia-smi is available → N/A."""
    mgr = _make_mgr(nvml_init=False)

    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = mgr._get_driver_version()

    assert result == "N/A"


# ─── optimize_gpu_memory ────────────────────────────────────────────────────

def test_optimize_gpu_memory_gpu_error_appears_in_output():
    """Covers lines 259-261, 268: GPU cache clear exception → gpu_error in output."""
    mgr = _make_mgr(gpu=True, torch=True)

    fake_torch = types.ModuleType("torch")
    call_count = [0]

    def bad_memory_reserved():
        call_count[0] += 1
        raise RuntimeError("cuda reserve fail")

    fake_torch.cuda = types.SimpleNamespace(
        memory_reserved=bad_memory_reserved,
        empty_cache=lambda: None,
    )

    with patch.dict(sys.modules, {"torch": fake_torch}):
        result = mgr.optimize_gpu_memory()

    assert "GPU cache hatası" in result
    assert "Python GC çalıştırıldı" in result


def test_optimize_gpu_memory_no_gpu_returns_zero_freed():
    """When GPU not available → freed_mb=0, GC runs."""
    mgr = _make_mgr(gpu=False)
    result = mgr.optimize_gpu_memory()
    assert "0.0 MB" in result
    assert "Python GC çalıştırıldı" in result


def test_optimize_gpu_memory_success_reports_freed_bytes():
    """When GPU cache clears successfully, reports freed MB."""
    mgr = _make_mgr(gpu=True, torch=True)

    fake_torch = types.ModuleType("torch")
    call_count = [0]

    def memory_reserved():
        call_count[0] += 1
        if call_count[0] == 1:
            return 500_000_000  # before: 500 MB
        return 200_000_000  # after: 200 MB

    fake_torch.cuda = types.SimpleNamespace(
        memory_reserved=memory_reserved,
        empty_cache=lambda: None,
    )

    with patch.dict(sys.modules, {"torch": fake_torch}):
        result = mgr.optimize_gpu_memory()

    assert "300.0 MB" in result


# ─── check_ollama ───────────────────────────────────────────────────────────

def test_check_ollama_exception_returns_false():
    """Covers lines 280-281: exception during requests.get."""
    mgr = _make_mgr()

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("refused"))

    with patch.dict(sys.modules, {"requests": fake_requests}):
        result = mgr.check_ollama()

    assert result is False


def test_check_ollama_200_returns_true():
    """check_ollama returns True on HTTP 200."""
    mgr = _make_mgr()

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *a, **kw: types.SimpleNamespace(status_code=200)

    with patch.dict(sys.modules, {"requests": fake_requests}):
        result = mgr.check_ollama()

    assert result is True


def test_check_ollama_non_200_returns_false():
    """check_ollama returns False on non-200 status."""
    mgr = _make_mgr()

    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *a, **kw: types.SimpleNamespace(status_code=503)

    with patch.dict(sys.modules, {"requests": fake_requests}):
        result = mgr.check_ollama()

    assert result is False


# ─── update_prometheus_metrics ──────────────────────────────────────────────

def test_update_prometheus_metrics_empty_dict_early_return():
    """Covers line 286: empty metrics_dict returns immediately."""
    mgr = _make_mgr()
    mgr._prometheus_gauges = None

    mgr.update_prometheus_metrics({})
    # Nothing should have been initialized
    assert mgr._prometheus_gauges is None


def test_update_prometheus_metrics_none_value_skipped():
    """Covers lines 322-323: None val → continue."""
    mgr = _make_mgr()

    mock_gauge = MagicMock()
    mgr._prometheus_gauges = {
        "cpu_percent": mock_gauge,
        "ram_percent": mock_gauge,
        "gpu_util_percent": mock_gauge,
        "gpu_temp_c": mock_gauge,
    }

    # cpu_percent=None → skip; ram_percent=50.0 → set called once
    mgr.update_prometheus_metrics({"cpu_percent": None, "ram_percent": 50.0})
    assert mock_gauge.set.call_count == 1


def test_update_prometheus_metrics_gauge_set_exception_continues():
    """Covers lines 326-327: gauge.set() raises → continue."""
    mgr = _make_mgr()

    bad_gauge = MagicMock()
    bad_gauge.set = MagicMock(side_effect=RuntimeError("gauge fail"))

    mgr._prometheus_gauges = {
        "cpu_percent": bad_gauge,
        "ram_percent": bad_gauge,
        "gpu_util_percent": bad_gauge,
        "gpu_temp_c": bad_gauge,
    }

    # Should not raise
    mgr.update_prometheus_metrics({"cpu_percent": 55.0, "ram_percent": 40.0})
    assert bad_gauge.set.call_count >= 1


def test_update_prometheus_metrics_initializes_on_first_call():
    """Covers Prometheus Gauge init block."""
    mgr = _make_mgr()
    mgr._prometheus_gauges = None

    mock_gauge_instance = MagicMock()
    mock_gauge_cls = MagicMock(return_value=mock_gauge_instance)
    fake_prom = types.ModuleType("prometheus_client")
    fake_prom.Gauge = mock_gauge_cls

    with patch.dict(sys.modules, {"prometheus_client": fake_prom}):
        mgr.update_prometheus_metrics({"cpu_percent": 10.0})

    assert mgr._prometheus_gauges is not None


def test_update_prometheus_metrics_import_failure_empty_dict():
    """Covers lines 308-309: prometheus_client import fails → empty dict."""
    mgr = _make_mgr()
    mgr._prometheus_gauges = None

    with patch.dict(sys.modules, {"prometheus_client": None}):
        mgr.update_prometheus_metrics({"cpu_percent": 10.0})

    assert mgr._prometheus_gauges == {}


# ─── get_health_summary ─────────────────────────────────────────────────────

def test_get_health_summary_covers_all_fields():
    """Covers lines 335-339."""
    mgr = _make_mgr()
    mgr.get_cpu_usage = lambda: 42.0
    mgr.get_memory_info = lambda: {"percent": 55.0}
    mgr.get_gpu_info = lambda: {"available": False, "reason": "no GPU"}
    mgr.check_ollama = lambda: False

    result = mgr.get_health_summary()
    assert result["status"] == "healthy"
    assert result["cpu_percent"] == 42.0
    assert result["ram_percent"] == 55.0
    assert result["gpu_available"] is False
    assert result["ollama_online"] is False
    assert "python_version" in result
    assert "os" in result


def test_get_health_summary_cpu_none_uses_zero():
    """get_health_summary uses 0.0 when cpu is None."""
    mgr = _make_mgr()
    mgr.get_cpu_usage = lambda: None
    mgr.get_memory_info = lambda: {}
    mgr.get_gpu_info = lambda: {"available": False}
    mgr.check_ollama = lambda: False

    result = mgr.get_health_summary()
    assert result["cpu_percent"] == 0.0
    assert result["ram_percent"] == 0.0


# ─── full_report ─────────────────────────────────────────────────────────────

def test_full_report_psutil_unavailable_shows_message():
    """Covers line 362: cpu is None → 'psutil kurulu değil'."""
    mgr = _make_mgr()
    mgr.get_cpu_usage = lambda: None
    mgr.get_memory_info = lambda: {}
    mgr.get_gpu_info = lambda: {"available": False, "reason": "no GPU"}
    mgr.check_ollama = lambda: False
    mgr.update_prometheus_metrics = lambda x: None

    report = mgr.full_report()
    assert "psutil kurulu değil" in report


def test_full_report_gpu_with_temperature_and_utilization():
    """Covers lines 379-394: GPU with temp and util keys."""
    mgr = _make_mgr()

    gpu_data = {
        "available": True,
        "cuda_version": "12.1",
        "driver_version": "535.00",
        "devices": [{
            "id": 0, "name": "RTX 4090",
            "compute_capability": "8.9",
            "total_vram_gb": 24.0, "allocated_gb": 4.5,
            "reserved_gb": 5.0, "free_gb": 19.0,
            "temperature_c": 65, "utilization_pct": 80,
        }],
    }

    mgr.get_cpu_usage = lambda: 30.0
    mgr.get_memory_info = lambda: {"percent": 40.0, "used_gb": 8.0, "total_gb": 32.0}
    mgr.get_gpu_info = lambda: gpu_data
    mgr.check_ollama = lambda: True
    mgr.update_prometheus_metrics = lambda x: None

    report = mgr.full_report()
    assert "65°C" in report
    assert "%80 GPU" in report
    assert "RTX 4090" in report


def test_full_report_gpu_without_temperature():
    """Covers lines 383-394: GPU present but no temperature key."""
    mgr = _make_mgr()

    gpu_data = {
        "available": True,
        "cuda_version": "12.1",
        "driver_version": "535.00",
        "devices": [{
            "id": 0, "name": "GTX 1080",
            "compute_capability": "6.1",
            "total_vram_gb": 8.0, "allocated_gb": 2.0,
            "reserved_gb": 2.5, "free_gb": 5.5,
        }],
    }

    mgr.get_cpu_usage = lambda: 20.0
    mgr.get_memory_info = lambda: {"percent": 30.0, "used_gb": 4.0, "total_gb": 16.0}
    mgr.get_gpu_info = lambda: gpu_data
    mgr.check_ollama = lambda: False
    mgr.update_prometheus_metrics = lambda x: None

    report = mgr.full_report()
    assert "GTX 1080" in report
    assert "°C" not in report


# ─── close ──────────────────────────────────────────────────────────────────

def test_close_with_nvml_initialized():
    """Covers lines 417-426: close() when _nvml_initialized=True."""
    mgr = _make_mgr(nvml_init=True)

    shutdown_called = []
    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlShutdown = lambda: shutdown_called.append(True)

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        mgr.close()

    assert shutdown_called
    assert mgr._nvml_initialized is False


def test_close_nvml_shutdown_exception_sets_flag_to_false():
    """Covers except clause in close(): shutdown raises → finally still sets flag."""
    mgr = _make_mgr(nvml_init=True)

    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlShutdown = lambda: (_ for _ in ()).throw(RuntimeError("shutdown fail"))

    with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
        mgr.close()  # Should not raise

    assert mgr._nvml_initialized is False


def test_close_idempotent_when_not_initialized():
    """close() is a no-op when _nvml_initialized=False."""
    mgr = _make_mgr(nvml_init=False)
    mgr.close()  # Should not raise
    assert mgr._nvml_initialized is False


# ─── __del__ ────────────────────────────────────────────────────────────────

def test_del_calls_close():
    """Covers line 430: __del__ calls self.close()."""
    mgr = _make_mgr(nvml_init=False)
    close_called = []
    mgr.close = lambda: close_called.append(True)
    mgr.__del__()
    assert close_called


# ─── __repr__ ───────────────────────────────────────────────────────────────

def test_repr_format():
    """Covers line 433: __repr__ returns formatted string."""
    mgr = _make_mgr(gpu=True, torch=True, nvml_init=False)
    r = repr(mgr)
    assert "SystemHealthManager" in r
    assert "gpu=True" in r
    assert "torch=True" in r

# ─── degraded status when a dependency is unhealthy (line 454->456) ─────────

def test_get_health_summary_sets_degraded_when_dependency_is_unhealthy():
    """Covers branch 454->456: summary status becomes 'degraded' on unhealthy dep."""
    mgr = _make_mgr()
    mgr.cfg = types.SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=5,
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
    )
    mgr.get_cpu_usage = lambda: 10.0
    mgr.get_memory_info = lambda: {"percent": 20.0}
    mgr.get_gpu_info = lambda: {"available": False}
    mgr.check_ollama = lambda: False
    mgr.get_dependency_health = lambda: {
        "redis": {"healthy": True, "latency_ms": 1.0},
        "postgres": {"healthy": False, "latency_ms": None},
    }

    summary = mgr.get_health_summary()

    assert summary["status"] == "degraded"
    assert "dependencies" in summary
    assert summary["dependencies"]["postgres"]["healthy"] is False