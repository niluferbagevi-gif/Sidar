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
