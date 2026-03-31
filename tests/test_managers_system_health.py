"""
managers/system_health.py için birim testleri.
render_llm_metrics_prometheus, SystemHealthManager._check_import, constructor.
"""
from __future__ import annotations

import sys
import types


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
