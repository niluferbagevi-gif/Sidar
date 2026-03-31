"""
managers/system_health.py için birim testleri.
render_llm_metrics_prometheus, SystemHealthManager._check_import, constructor.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import Mock


def _get_sh():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        pass

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "managers.system_health" in sys.modules:
        del sys.modules["managers.system_health"]
    import managers.system_health as sh
    return sh


# ══════════════════════════════════════════════════════════════
# render_llm_metrics_prometheus
# ══════════════════════════════════════════════════════════════

class TestRenderLlmMetricsPrometheus:
    def test_returns_string(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus({})
        assert isinstance(result, str)

    def test_ends_with_newline(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus({})
        assert result.endswith("\n")

    def test_contains_help_lines(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus({})
        assert "# HELP" in result

    def test_empty_snapshot_zero_values(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus({})
        assert "sidar_llm_calls_total 0" in result
        assert "sidar_llm_cost_total_usd 0.0" in result

    def test_totals_reflected(self):
        sh = _get_sh()
        snapshot = {"totals": {"calls": 42, "cost_usd": 1.5, "total_tokens": 1000, "failures": 2}}
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert "sidar_llm_calls_total 42" in result
        assert "sidar_llm_cost_total_usd 1.5" in result
        assert "sidar_llm_tokens_total 1000" in result
        assert "sidar_llm_failures_total 2" in result

    def test_cache_metrics_reflected(self):
        sh = _get_sh()
        snapshot = {"cache": {"hits": 10, "misses": 5, "hit_rate": 0.667}}
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert "sidar_semantic_cache_hits_total 10" in result
        assert "sidar_semantic_cache_misses_total 5" in result

    def test_legacy_cache_aliases_present(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus({})
        assert "sidar_cache_hits_total" in result
        assert "sidar_cache_misses_total" in result

    def test_by_provider_labels(self):
        sh = _get_sh()
        snapshot = {
            "by_provider": {
                "anthropic": {"calls": 5, "cost_usd": 0.1, "total_tokens": 200, "failures": 0, "latency_ms_avg": 300.0}
            }
        }
        result = sh.render_llm_metrics_prometheus(snapshot)
        assert 'provider="anthropic"' in result
        assert "sidar_llm_calls_total" in result

    def test_none_snapshot_handled(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus(None)
        assert isinstance(result, str)

    def test_non_dict_snapshot_handled(self):
        sh = _get_sh()
        result = sh.render_llm_metrics_prometheus("invalid")  # type: ignore
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# SystemHealthManager._check_import
# ══════════════════════════════════════════════════════════════

class TestCheckImport:
    def test_existing_module_returns_true(self):
        sh = _get_sh()
        assert sh.SystemHealthManager._check_import("sys") is True
        assert sh.SystemHealthManager._check_import("os") is True

    def test_missing_module_returns_false(self):
        sh = _get_sh()
        assert sh.SystemHealthManager._check_import("nonexistent_module_xyz_abc") is False


# ══════════════════════════════════════════════════════════════
# SystemHealthManager constructor
# ══════════════════════════════════════════════════════════════

class TestSystemHealthManagerInit:
    def test_cpu_sample_interval_clamped(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(cpu_sample_interval=999.0)
        assert mgr.cpu_sample_interval <= 2.0

    def test_cpu_sample_interval_min(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(cpu_sample_interval=-5.0)
        assert mgr.cpu_sample_interval == 0.0

    def test_use_gpu_false_disables_gpu(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager(use_gpu=False)
        assert mgr._gpu_available is False

    def test_repr_or_type(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        assert isinstance(mgr, sh.SystemHealthManager)


class TestSystemHealthDependencyIsolation:
    def test_check_redis_disabled_when_url_missing(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.REDIS_URL = ""
        status = mgr.check_redis()
        assert status["healthy"] is True
        assert status["mode"] == "disabled"

    def test_check_database_sqlite_missing_file_reports_failure(self, tmp_path):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        db_file = tmp_path / "missing.db"
        mgr.cfg.DATABASE_URL = f"sqlite:///{db_file}"
        status = mgr.check_database()
        assert status["mode"] == "sqlite"
        assert status["healthy"] is False

    def test_check_database_tcp_failure_isolated(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.DATABASE_URL = "postgresql://user:pass@db.example.com:5432/sidar"
        monkeypatch.setattr(mgr, "_tcp_dependency_health", lambda *_a, **_k: {"healthy": False, "error": "refused"})
        status = mgr.check_database()
        assert status["healthy"] is False
        assert status["mode"] == "postgresql"

    def test_check_redis_uses_url_host_and_port(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.REDIS_URL = "redis://cache.internal:6380/0"

        captured = {}

        def _fake_tcp(host, port, *, label):
            captured.update({"host": host, "port": port, "label": label})
            return {"healthy": True, "target": f"{host}:{port}", "kind": label}

        monkeypatch.setattr(mgr, "_tcp_dependency_health", _fake_tcp)
        status = mgr.check_redis()

        assert captured == {"host": "cache.internal", "port": 6380, "label": "redis"}
        assert status["mode"] == "tcp"


class TestSystemHealthHighLoadScenarios:
    def test_get_health_summary_reports_degraded_when_dependency_unhealthy(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.ENABLE_DEPENDENCY_HEALTHCHECKS = True
        monkeypatch.setattr(
            mgr,
            "get_dependency_health",
            lambda: {
                "redis": {"healthy": True},
                "database": {"healthy": False, "error": "connection refused"},
            },
        )
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *_a, **_k: 98.5)
        monkeypatch.setattr(mgr, "get_memory_info", lambda: {"percent": 97.2})
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False})
        monkeypatch.setattr(mgr, "check_ollama", lambda: True)

        summary = mgr.get_health_summary()
        assert summary["status"] == "degraded"
        assert summary["cpu_percent"] == 98.5
        assert summary["ram_percent"] == 97.2

    def test_full_report_contains_high_cpu_and_ram_values(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        monkeypatch.setattr(mgr, "get_cpu_usage", lambda *_a, **_k: 99.0)
        monkeypatch.setattr(
            mgr,
            "get_memory_info",
            lambda: {"total_gb": 64.0, "used_gb": 63.0, "available_gb": 1.0, "percent": 98.0},
        )
        monkeypatch.setattr(mgr, "check_ollama", lambda: False)
        monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False, "reason": "CUDA unavailable"})

        report = mgr.full_report()
        assert "CPU       : %99.0 kullanımda" in report
        assert "RAM       : 63.0/64.0 GB (%98 kullanımda)" in report


class TestSystemHealthExternalFailureScenarios:
    def test_check_ollama_returns_false_when_http_500(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()

        class _Resp:
            status_code = 500

        fake_requests = types.SimpleNamespace(get=lambda *_a, **_k: _Resp())
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        assert mgr.check_ollama() is False

    def test_check_ollama_returns_false_when_request_times_out(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()

        def _raise_timeout(*_a, **_k):
            raise TimeoutError("network timeout")

        fake_requests = types.SimpleNamespace(get=_raise_timeout)
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        assert mgr.check_ollama() is False

    def test_tcp_dependency_health_returns_unhealthy_on_connection_error(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()

        def _raise_connect_error(*_a, **_k):
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(sh.socket, "create_connection", _raise_connect_error)
        status = mgr._tcp_dependency_health("api.local", 443, label="redis")

        assert status["healthy"] is False
        assert status["kind"] == "redis"
        assert "connection refused" in status["error"]

class TestSystemHealthAdditionalBranches:
    def test_check_database_disabled_when_url_missing(self):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.DATABASE_URL = ""
        status = mgr.check_database()
        assert status["healthy"] is True
        assert status["mode"] == "disabled"

    def test_check_database_sqlite_existing_file_is_healthy(self, tmp_path):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        db_file = tmp_path / "existing.db"
        db_file.write_text("ok", encoding="utf-8")
        mgr.cfg.DATABASE_URL = f"sqlite:///{db_file}"
        status = mgr.check_database()
        assert status["mode"] == "sqlite"
        assert status["healthy"] is True

    def test_check_redis_defaults_to_localhost_when_host_missing(self, monkeypatch):
        sh = _get_sh()
        mgr = sh.SystemHealthManager()
        mgr.cfg.REDIS_URL = "redis:///0"

        captured = {}

        def _fake_tcp(host, port, *, label):
            captured.update({"host": host, "port": port, "label": label})
            return {"healthy": True, "target": f"{host}:{port}", "kind": label}

        monkeypatch.setattr(mgr, "_tcp_dependency_health", _fake_tcp)
        status = mgr.check_redis()

        assert captured == {"host": "localhost", "port": 6379, "label": "redis"}
        assert status["mode"] == "tcp"

    def test_init_nvml_wsl2_osrelease_unreadable_falls_back_false(self, monkeypatch):
        sh = _get_sh()

        class _FakePynvml:
            @staticmethod
            def nvmlInit():
                raise Exception("NVML error")

        monkeypatch.setitem(sys.modules, "pynvml", _FakePynvml)
        monkeypatch.setattr(sh.SystemHealthManager, "_check_import", lambda *_a, **_k: True)
        monkeypatch.setattr(sh.SystemHealthManager, "_check_gpu", lambda *_a, **_k: True)
        monkeypatch.setattr("builtins.open", Mock(side_effect=FileNotFoundError("missing osrelease")))

        mgr = sh.SystemHealthManager(use_gpu=True)
        assert mgr._nvml_initialized is False

# ===== MERGED FROM tests/test_managers_system_health_extra.py =====

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

class Extra_TestRenderByUser:
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

class Extra_TestCheckGpu:
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

class Extra_TestInitNvml:
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

class Extra_TestGetCpuUsage:
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

class Extra_TestGetMemoryInfo:
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

class Extra_TestGetGpuInfo:
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
        assert info["cuda_version"] == "11.8"

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

class Extra_TestGetDriverVersion:
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

class Extra_TestOptimizeGpuMemory:
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

class Extra_TestUpdatePrometheusMetrics:
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

class Extra_TestGetHealthSummary:
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

class Extra_TestGetDependencyHealth:
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

class Extra_TestFullReport:
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

class Extra_TestClose:
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

class Extra_TestCheckOllama:
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

class Extra_TestTcpDependencyHealth:
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
        mgr.cfg.HEALTHCHECK_CONNECT_TIMEOUT_MS = 10  # below minimum (50ms)
        captured = {}

        class _FakeConn:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _fake_create(addr, timeout):
            captured["timeout"] = timeout
            return _FakeConn()

        monkeypatch.setattr(sh.socket, "create_connection", _fake_create)
        mgr._tcp_dependency_health("host", 5432, label="database")
        # max(50, 10) = 50ms = 0.05s
        assert captured["timeout"] == pytest.approx(0.05)


import pytest
