"""
tests/test_core_metrics.py
==========================
core/agent_metrics.py, core/cache_metrics.py, core/llm_metrics.py modüllerinin
birim testleri.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# YARDIMCI
# ─────────────────────────────────────────────────────────────────────────────

def _fresh(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


# ═════════════════════════════════════════════════════════════════════════════
#  core/agent_metrics.py
# ═════════════════════════════════════════════════════════════════════════════

class TestDelegationHistogram:
    """_DelegationHistogram iç sınıf testleri."""

    def setup_method(self):
        mod = _fresh("core.agent_metrics")
        self.Hist = mod._DelegationHistogram
        self.BUCKETS = mod._BUCKETS

    def test_bos_histogram_snapshot(self):
        h = self.Hist()
        snap = h.snapshot()
        assert snap["count"] == 0
        assert snap["sum"] == 0.0
        assert len(snap["counts"]) == len(self.BUCKETS)

    def test_observe_arttirir(self):
        h = self.Hist()
        h.observe(0.3)
        snap = h.snapshot()
        assert snap["count"] == 1
        assert snap["sum"] == pytest.approx(0.3)

    def test_bucket_dagitimi(self):
        h = self.Hist()
        h.observe(0.1)   # ≤0.1 bucket'a düşmeli
        snap = h.snapshot()
        # İlk bucket (0.1) dahil tüm üstündeki bucket'lar artmalı
        assert snap["counts"][0] >= 1

    def test_cok_gozlem(self):
        h = self.Hist()
        for i in range(10):
            h.observe(float(i))
        snap = h.snapshot()
        assert snap["count"] == 10

    def test_inf_bucket_yakalanir(self):
        h = self.Hist()
        import math
        h.observe(1000.0)  # çok büyük → +Inf bucket
        snap = h.snapshot()
        assert snap["counts"][-1] >= 1

    def test_thread_safety(self):
        h = self.Hist()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    h.observe(0.1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert h.snapshot()["count"] == 250


class TestAgentMetricsCollector:
    """AgentMetricsCollector testleri."""

    def setup_method(self):
        mod = _fresh("core.agent_metrics")
        self.Collector = mod.AgentMetricsCollector

    def test_bos_prometheus_ciktisi(self):
        c = self.Collector()
        output = c.render_prometheus()
        assert "sidar_agent_delegation_duration_seconds" in output
        assert "sidar_agent_delegation_total" in output
        assert "sidar_agent_step_duration_seconds" in output
        assert "sidar_agent_step_total" in output

    def test_record_kaydeder(self):
        c = self.Collector()
        c.record("coder", "code", "success", 1.2)
        assert ("coder", "code", "success") in c._counters
        assert c._counters[("coder", "code", "success")] == 1

    def test_record_birden_fazla(self):
        c = self.Collector()
        c.record("qa", "test", "success", 0.5)
        c.record("qa", "test", "success", 0.8)
        assert c._counters[("qa", "test", "success")] == 2

    def test_record_step_kaydeder(self):
        c = self.Collector()
        c.record_step("coder", "think", "tool", "ok", 0.3)
        assert ("coder", "think", "tool", "ok") in c._step_counters
        assert c._step_counters[("coder", "think", "tool", "ok")] == 1

    def test_render_prometheus_veriyle(self):
        c = self.Collector()
        c.record("reviewer", "review", "error", 2.5)
        c.record_step("qa", "run", "test", "pass", 0.9)
        output = c.render_prometheus()
        assert 'receiver="reviewer"' in output
        assert 'agent="qa"' in output
        assert "+Inf" in output

    def test_prometheus_counter_satirlari(self):
        c = self.Collector()
        c.record("sup", "delegate", "ok", 0.1)
        output = c.render_prometheus()
        assert "sidar_agent_delegation_total" in output

    def test_prometheus_step_counter_satirlari(self):
        c = self.Collector()
        c.record_step("a", "s", "t", "x", 0.1)
        output = c.render_prometheus()
        assert "sidar_agent_step_total" in output


class TestGetAgentMetricsCollector:
    """Singleton get_agent_metrics_collector() testleri."""

    def setup_method(self):
        mod = _fresh("core.agent_metrics")
        # _COLLECTOR'u sıfırla
        mod._COLLECTOR = None
        self.mod = mod

    def test_singleton_ayni_nesneyi_doner(self):
        a = self.mod.get_agent_metrics_collector()
        b = self.mod.get_agent_metrics_collector()
        assert a is b

    def test_donus_tipi(self):
        c = self.mod.get_agent_metrics_collector()
        assert isinstance(c, self.mod.AgentMetricsCollector)


# ═════════════════════════════════════════════════════════════════════════════
#  core/cache_metrics.py
# ═════════════════════════════════════════════════════════════════════════════

class TestCacheMetricsClass:
    """_CacheMetrics iç sınıf testleri."""

    def setup_method(self):
        mod = _fresh("core.cache_metrics")
        self.CM = mod._CacheMetrics

    def test_baslangic_degerleri(self):
        cm = self.CM()
        snap = cm.snapshot()
        assert snap["hits"] == 0
        assert snap["misses"] == 0
        assert snap["skips"] == 0
        assert snap["hit_rate"] == 0.0

    def test_record_hit(self):
        cm = self.CM()
        cm.record_hit()
        cm.record_hit()
        assert cm.snapshot()["hits"] == 2

    def test_record_miss(self):
        cm = self.CM()
        cm.record_miss()
        assert cm.snapshot()["misses"] == 1

    def test_record_skip(self):
        cm = self.CM()
        cm.record_skip()
        assert cm.snapshot()["skips"] == 1

    def test_hit_rate_hesaplama(self):
        cm = self.CM()
        cm.record_hit()
        cm.record_hit()
        cm.record_miss()
        snap = cm.snapshot()
        assert snap["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_record_eviction(self):
        cm = self.CM()
        cm.record_eviction(3)
        assert cm.snapshot()["evictions"] == 3

    def test_record_eviction_negatif_sayilmaz(self):
        cm = self.CM()
        cm.record_eviction(-5)
        assert cm.snapshot()["evictions"] == 0

    def test_record_redis_error(self):
        cm = self.CM()
        cm.record_redis_error(2)
        assert cm.snapshot()["redis_errors"] == 2

    def test_set_items(self):
        cm = self.CM()
        cm.set_items(10)
        assert cm.snapshot()["items"] == 10

    def test_set_items_negatif_sifirlanir(self):
        cm = self.CM()
        cm.set_items(-3)
        assert cm.snapshot()["items"] == 0

    def test_observe_redis_latency(self):
        cm = self.CM()
        cm.observe_redis_latency(12.5)
        assert cm.snapshot()["redis_latency_ms"] == pytest.approx(12.5)

    def test_observe_latency_negatif_sifirlanir(self):
        cm = self.CM()
        cm.observe_redis_latency(-1.0)
        assert cm.snapshot()["redis_latency_ms"] == pytest.approx(0.0)

    def test_snapshot_total_lookups(self):
        cm = self.CM()
        cm.record_hit()
        cm.record_miss()
        snap = cm.snapshot()
        assert snap["total_lookups"] == 2

    def test_thread_safety(self):
        cm = self.CM()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    cm.record_hit()
                    cm.record_miss()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        snap = cm.snapshot()
        assert snap["hits"] == 500
        assert snap["misses"] == 500


class TestCacheMetricsFunctions:
    """Modül-seviyesi cache_metrics fonksiyonları testleri."""

    def setup_method(self):
        self.mod = _fresh("core.cache_metrics")
        # İç singleton'u sıfırla
        self.mod._cache_metrics = self.mod._CacheMetrics()
        self.mod._prometheus_metric_cache.clear()

    def test_record_cache_hit(self):
        self.mod.record_cache_hit()
        assert self.mod.get_cache_metrics()["hits"] == 1

    def test_record_cache_miss(self):
        self.mod.record_cache_miss()
        assert self.mod.get_cache_metrics()["misses"] == 1

    def test_record_cache_skip(self):
        self.mod.record_cache_skip()
        assert self.mod.get_cache_metrics()["skips"] == 1

    def test_record_cache_eviction(self):
        self.mod.record_cache_eviction(5)
        assert self.mod.get_cache_metrics()["evictions"] == 5

    def test_record_cache_redis_error(self):
        self.mod.record_cache_redis_error(2)
        assert self.mod.get_cache_metrics()["redis_errors"] == 2

    def test_set_cache_items(self):
        self.mod.set_cache_items(20)
        assert self.mod.get_cache_metrics()["items"] == 20

    def test_observe_cache_redis_latency(self):
        self.mod.observe_cache_redis_latency(5.0)
        assert self.mod.get_cache_metrics()["redis_latency_ms"] == pytest.approx(5.0)

    def test_get_cache_metrics_bos(self):
        snap = self.mod.get_cache_metrics()
        assert "hits" in snap
        assert "misses" in snap
        assert "hit_rate" in snap


class TestPrometheusMetricHelper:
    """_get_prometheus_metric / _inc_prometheus_counter / _set_prometheus_gauge testleri."""

    def setup_method(self):
        self.mod = _fresh("core.cache_metrics")
        self.mod._prometheus_metric_cache.clear()

    def test_prometheus_client_yoksa_none_doner(self):
        with patch.dict(sys.modules, {"prometheus_client": None}):
            result = self.mod._get_prometheus_metric("test_metric", "desc", "counter")
        assert result is None

    def test_prometheus_counter_artirilir(self):
        mock_counter = MagicMock()
        mock_prometheus = MagicMock()
        mock_prometheus.REGISTRY = None
        mock_prometheus.Counter.return_value = mock_counter
        with patch.dict(sys.modules, {"prometheus_client": mock_prometheus}):
            self.mod._prometheus_metric_cache.clear()
            self.mod._inc_prometheus_counter("new_metric_x", "desc", 3)
        mock_counter.inc.assert_called_once_with(3)

    def test_inc_sifir_veya_negatif_cagirmaz(self):
        mock_counter = MagicMock()
        mock_prometheus = MagicMock()
        mock_prometheus.REGISTRY = None
        mock_prometheus.Counter.return_value = mock_counter
        with patch.dict(sys.modules, {"prometheus_client": mock_prometheus}):
            self.mod._prometheus_metric_cache.clear()
            self.mod._inc_prometheus_counter("zero_metric", "desc", 0)
        mock_counter.inc.assert_not_called()

    def test_set_gauge_cagrilir(self):
        mock_gauge = MagicMock()
        mock_prometheus = MagicMock()
        mock_prometheus.REGISTRY = None
        mock_prometheus.Gauge.return_value = mock_gauge
        with patch.dict(sys.modules, {"prometheus_client": mock_prometheus}):
            self.mod._prometheus_metric_cache.clear()
            self.mod._set_prometheus_gauge("gauge_metric_y", "desc", 42.0)
        mock_gauge.set.assert_called_once_with(42.0)

    def test_var_olan_collector_kullanilir(self):
        mock_prometheus = MagicMock()
        existing = MagicMock()
        mock_prometheus.REGISTRY = MagicMock()
        mock_prometheus.REGISTRY._names_to_collectors = {"cached_m": existing}
        with patch.dict(sys.modules, {"prometheus_client": mock_prometheus}):
            self.mod._prometheus_metric_cache.clear()
            result = self.mod._get_prometheus_metric("cached_m", "desc", "counter")
        assert result is existing


# ═════════════════════════════════════════════════════════════════════════════
#  core/llm_metrics.py
# ═════════════════════════════════════════════════════════════════════════════

class TestEnvFloat:
    """_env_float() yardımcı fonksiyon testleri."""

    def setup_method(self):
        self.mod = _fresh("core.llm_metrics")

    def test_gecerli_float(self, monkeypatch):
        monkeypatch.setenv("TEST_LLM_FLOAT", "3.5")
        assert self.mod._env_float("TEST_LLM_FLOAT", 1.0) == pytest.approx(3.5)

    def test_tanimlanmamis_key_varsayilan_doner(self, monkeypatch):
        monkeypatch.delenv("TEST_LLM_FLOAT_X", raising=False)
        assert self.mod._env_float("TEST_LLM_FLOAT_X", 9.9) == pytest.approx(9.9)

    def test_gecersiz_deger_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_LLM_FLOAT_BAD", "not_a_float")
        assert self.mod._env_float("TEST_LLM_FLOAT_BAD", 2.0) == pytest.approx(2.0)

    def test_bos_deger_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_LLM_FLOAT_EMPTY", "")
        assert self.mod._env_float("TEST_LLM_FLOAT_EMPTY", 5.0) == pytest.approx(5.0)

    def test_inf_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_LLM_FLOAT_INF", "inf")
        assert self.mod._env_float("TEST_LLM_FLOAT_INF", 1.0) == pytest.approx(1.0)

    def test_nan_varsayilan_doner(self, monkeypatch):
        monkeypatch.setenv("TEST_LLM_FLOAT_NAN", "nan")
        assert self.mod._env_float("TEST_LLM_FLOAT_NAN", 1.0) == pytest.approx(1.0)


class TestLLMMetricEvent:
    """LLMMetricEvent dataclass testleri."""

    def setup_method(self):
        self.mod = _fresh("core.llm_metrics")

    def test_olusturma(self):
        e = self.mod.LLMMetricEvent(
            timestamp=1000.0,
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=200.0,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            success=True,
            rate_limited=False,
        )
        assert e.provider == "openai"
        assert e.total_tokens == 150
        assert e.judge_score is None
        assert e.hallucination_risk is None

    def test_asdict_calisir(self):
        e = self.mod.LLMMetricEvent(
            timestamp=1.0, provider="x", model="y",
            latency_ms=1.0, prompt_tokens=0, completion_tokens=0,
            total_tokens=0, cost_usd=0.0, success=True, rate_limited=False,
        )
        d = asdict(e)
        assert "provider" in d
        assert "judge_score" in d


class TestLLMMetricsUserContext:
    """ContextVar tabanlı user_id yönetimi testleri."""

    def setup_method(self):
        self.mod = _fresh("core.llm_metrics")

    def test_bos_baslangic(self):
        assert self.mod.get_current_metrics_user_id() == ""

    def test_set_ve_get(self):
        token = self.mod.set_current_metrics_user_id("user123")
        try:
            assert self.mod.get_current_metrics_user_id() == "user123"
        finally:
            self.mod.reset_current_metrics_user_id(token)

    def test_reset_sonrasi_bos(self):
        token = self.mod.set_current_metrics_user_id("abc")
        self.mod.reset_current_metrics_user_id(token)
        assert self.mod.get_current_metrics_user_id() == ""


class TestLLMMetricsCollector:
    """LLMMetricsCollector sınıf testleri."""

    def setup_method(self):
        self.mod = _fresh("core.llm_metrics")
        self.Collector = self.mod.LLMMetricsCollector

    def test_maliyet_tahmini_bilinen_model(self):
        cost = self.Collector.estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 0)
        assert cost == pytest.approx(0.15, abs=1e-6)

    def test_maliyet_tahmini_bilinmeyen_model(self):
        cost = self.Collector.estimate_cost_usd("unknown", "model", 100, 100)
        assert cost == 0.0

    def test_record_basit(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=100.0,
                 prompt_tokens=10, completion_tokens=5)
        snap = c.snapshot()
        assert snap["totals"]["calls"] == 1

    def test_record_hata_rate_limited(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=0.0,
                 error="HTTP 429 rate limit exceeded", success=False)
        snap = c.snapshot()
        assert snap["totals"]["failures"] == 1
        assert snap["totals"]["rate_limited"] == 1

    def test_record_judge_alanlari(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=50.0,
                 judge_score=0.85, hallucination_risk=0.1)
        events = list(c._events)
        assert events[0].judge_score == pytest.approx(0.85)
        assert events[0].hallucination_risk == pytest.approx(0.1)

    def test_record_user_id_context(self):
        c = self.Collector()
        token = self.mod.set_current_metrics_user_id("u999")
        try:
            c.record(provider="anthropic", model="claude-3-5-sonnet-latest", latency_ms=200.0)
        finally:
            self.mod.reset_current_metrics_user_id(token)
        events = list(c._events)
        assert events[0].user_id == "u999"

    def test_snapshot_bos(self):
        c = self.Collector()
        snap = c.snapshot()
        assert snap["totals"]["calls"] == 0
        assert snap["window_events"] == 0
        assert "by_provider" in snap
        assert "by_user" in snap
        assert "recent" in snap
        assert "cache" in snap
        assert "budget" in snap

    def test_snapshot_by_provider(self):
        c = self.Collector()
        c.record(provider="gemini", model="gemini-2.5-flash", latency_ms=300.0,
                 prompt_tokens=50, completion_tokens=20)
        snap = c.snapshot()
        assert "gemini" in snap["by_provider"]
        row = snap["by_provider"]["gemini"]
        assert row["calls"] == 1
        assert row["prompt_tokens"] == 50

    def test_snapshot_by_user(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=100.0,
                 user_id="alice", prompt_tokens=10, completion_tokens=5)
        snap = c.snapshot()
        assert "alice" in snap["by_user"]

    def test_snapshot_recent_limit(self):
        c = self.Collector()
        for i in range(25):
            c.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0)
        snap = c.snapshot()
        assert len(snap["recent"]) <= 20

    def test_max_events_sınırı(self):
        c = self.Collector(max_events=5)
        for i in range(10):
            c.record(provider="openai", model="gpt-4o-mini", latency_ms=1.0)
        assert len(c._events) == 5

    def test_usage_sink_cagrilir(self):
        c = self.Collector()
        sink = MagicMock(return_value=None)
        c.set_usage_sink(sink)
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0)
        sink.assert_called_once()

    def test_usage_sink_hata_yutulur(self):
        c = self.Collector()
        c.set_usage_sink(lambda e: (_ for _ in ()).throw(RuntimeError("fail")))
        # Hata fırlatılmamalı
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0)

    def test_snapshot_budget_hesaplama(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0,
                 cost_usd=0.001)
        snap = c.snapshot()
        budget = snap["budget"]
        assert "daily_limit_usd" in budget
        assert "total_remaining_usd" in budget

    def test_record_maliyet_none_ise_hesaplanir(self):
        c = self.Collector()
        c.record(provider="openai", model="gpt-4o-mini", latency_ms=10.0,
                 prompt_tokens=1_000_000, completion_tokens=0, cost_usd=None)
        events = list(c._events)
        assert events[0].cost_usd == pytest.approx(0.15, abs=1e-6)


class TestGetLLMMetricsCollector:
    """get_llm_metrics_collector() singleton testleri."""

    def setup_method(self):
        self.mod = _fresh("core.llm_metrics")

    def test_singleton_ayni_nesne(self):
        a = self.mod.get_llm_metrics_collector()
        b = self.mod.get_llm_metrics_collector()
        assert a is b

    def test_donus_tipi(self):
        c = self.mod.get_llm_metrics_collector()
        assert isinstance(c, self.mod.LLMMetricsCollector)