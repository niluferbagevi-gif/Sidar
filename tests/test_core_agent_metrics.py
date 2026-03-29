"""
core/agent_metrics.py için birim testleri.
_DelegationHistogram, AgentMetricsCollector ve get_agent_metrics_collector
singleton davranışını kapsar.
"""
from __future__ import annotations

import math
import sys
import threading


def _get_agent_metrics():
    if "core.agent_metrics" in sys.modules:
        del sys.modules["core.agent_metrics"]
    import core.agent_metrics as am
    # Singleton'ı sıfırla
    am._COLLECTOR = None
    return am


# ══════════════════════════════════════════════════════════════
# _DelegationHistogram
# ══════════════════════════════════════════════════════════════

class TestDelegationHistogram:
    def _new(self):
        am = _get_agent_metrics()
        return am._DelegationHistogram()

    def test_initial_snapshot_zeros(self):
        h = self._new()
        snap = h.snapshot()
        assert snap["count"] == 0
        assert snap["sum"] == 0.0
        assert all(c == 0 for c in snap["counts"])

    def test_observe_increments_total(self):
        h = self._new()
        h.observe(0.5)
        assert h.snapshot()["count"] == 1

    def test_observe_accumulates_sum(self):
        h = self._new()
        h.observe(1.0)
        h.observe(2.0)
        assert abs(h.snapshot()["sum"] - 3.0) < 1e-9

    def test_observe_bucket_assignment_small(self):
        h = self._new()
        h.observe(0.05)  # <= 0.1 bucket (index 0)
        snap = h.snapshot()
        assert snap["counts"][0] == 1  # [0.1] bucket

    def test_observe_bucket_assignment_medium(self):
        am = _get_agent_metrics()
        h = am._DelegationHistogram()
        h.observe(1.5)  # 1.5 <= 2.5, but > 1.0; bucket index 4 (2.5)
        snap = h.snapshot()
        # All buckets >= 2.5 should have count 1
        buckets = am._BUCKETS
        for i, bound in enumerate(buckets):
            if bound >= 2.5:
                assert snap["counts"][i] == 1
            elif bound < 1.5:
                assert snap["counts"][i] == 0

    def test_observe_inf_bucket_always_counts(self):
        am = _get_agent_metrics()
        h = am._DelegationHistogram()
        h.observe(999.0)
        snap = h.snapshot()
        # +Inf bucket (last) should be 1
        assert snap["counts"][-1] == 1

    def test_multiple_observations_cumulative_buckets(self):
        am = _get_agent_metrics()
        h = am._DelegationHistogram()
        h.observe(0.1)
        h.observe(0.5)
        snap = h.snapshot()
        assert snap["count"] == 2
        # +Inf bucket should have both
        assert snap["counts"][-1] == 2

    def test_snapshot_returns_copy_of_counts(self):
        h = self._new()
        h.observe(1.0)
        snap1 = h.snapshot()
        snap2 = h.snapshot()
        assert snap1["counts"] is not snap2["counts"]  # defensive copy


# ══════════════════════════════════════════════════════════════
# AgentMetricsCollector.record
# ══════════════════════════════════════════════════════════════

class TestAgentMetricsCollectorRecord:
    def setup_method(self):
        self.am = _get_agent_metrics()
        self.collector = self.am.AgentMetricsCollector()

    def test_record_creates_histogram(self):
        self.collector.record("coder", "code", "success", 1.0)
        assert ("coder", "code", "success") in self.collector._histograms

    def test_record_increments_counter(self):
        self.collector.record("coder", "code", "success", 1.0)
        self.collector.record("coder", "code", "success", 0.5)
        assert self.collector._counters[("coder", "code", "success")] == 2

    def test_record_separate_keys_independent(self):
        self.collector.record("coder", "code", "success", 1.0)
        self.collector.record("reviewer", "review", "error", 2.0)
        assert self.collector._counters[("coder", "code", "success")] == 1
        assert self.collector._counters[("reviewer", "review", "error")] == 1

    def test_record_histogram_sum(self):
        self.collector.record("agent", "task", "ok", 1.5)
        self.collector.record("agent", "task", "ok", 2.5)
        hist = self.collector._histograms[("agent", "task", "ok")]
        assert abs(hist.snapshot()["sum"] - 4.0) < 1e-9


# ══════════════════════════════════════════════════════════════
# AgentMetricsCollector.record_step
# ══════════════════════════════════════════════════════════════

class TestAgentMetricsCollectorRecordStep:
    def setup_method(self):
        am = _get_agent_metrics()
        self.collector = am.AgentMetricsCollector()

    def test_record_step_creates_step_histogram(self):
        self.collector.record_step("supervisor", "tool_call", "rag", "success", 0.2)
        assert ("supervisor", "tool_call", "rag", "success") in self.collector._step_histograms

    def test_record_step_increments_step_counter(self):
        self.collector.record_step("supervisor", "tool_call", "rag", "success", 0.2)
        self.collector.record_step("supervisor", "tool_call", "rag", "success", 0.3)
        assert self.collector._step_counters[("supervisor", "tool_call", "rag", "success")] == 2


# ══════════════════════════════════════════════════════════════
# AgentMetricsCollector.render_prometheus
# ══════════════════════════════════════════════════════════════

class TestRenderPrometheus:
    def setup_method(self):
        am = _get_agent_metrics()
        self.am = am
        self.collector = am.AgentMetricsCollector()

    def test_empty_collector_produces_help_and_type_lines(self):
        output = self.collector.render_prometheus()
        assert "# HELP sidar_agent_delegation_duration_seconds" in output
        assert "# TYPE sidar_agent_delegation_duration_seconds histogram" in output
        assert "# HELP sidar_agent_delegation_total" in output
        assert "# HELP sidar_agent_step_duration_seconds" in output
        assert "# HELP sidar_agent_step_total" in output

    def test_output_ends_with_newline(self):
        output = self.collector.render_prometheus()
        assert output.endswith("\n")

    def test_delegation_bucket_lines_present_after_record(self):
        self.collector.record("coder", "code", "success", 0.5)
        output = self.collector.render_prometheus()
        assert 'sidar_agent_delegation_duration_seconds_bucket' in output
        assert 'receiver="coder"' in output
        assert 'intent="code"' in output
        assert 'status="success"' in output

    def test_delegation_sum_and_count_lines_present(self):
        self.collector.record("coder", "code", "success", 1.5)
        output = self.collector.render_prometheus()
        assert 'sidar_agent_delegation_duration_seconds_sum' in output
        assert 'sidar_agent_delegation_duration_seconds_count' in output

    def test_inf_bucket_renders_as_plus_inf(self):
        self.collector.record("a", "b", "ok", 100.0)
        output = self.collector.render_prometheus()
        assert 'le="+Inf"' in output

    def test_step_metrics_appear_after_record_step(self):
        self.collector.record_step("supervisor", "decide", "tool", "ok", 0.1)
        output = self.collector.render_prometheus()
        assert 'sidar_agent_step_duration_seconds_bucket' in output
        assert 'agent="supervisor"' in output

    def test_counter_line_present(self):
        self.collector.record("coder", "code", "success", 0.5)
        output = self.collector.render_prometheus()
        assert 'sidar_agent_delegation_total' in output

    def test_bucket_count_equals_number_of_buckets(self):
        self.collector.record("a", "b", "ok", 0.1)
        output = self.collector.render_prometheus()
        bucket_lines = [l for l in output.splitlines()
                        if l.startswith("sidar_agent_delegation_duration_seconds_bucket")]
        assert len(bucket_lines) == len(self.am._BUCKETS)


# ══════════════════════════════════════════════════════════════
# get_agent_metrics_collector singleton
# ══════════════════════════════════════════════════════════════

class TestGetAgentMetricsCollector:
    def test_returns_instance(self):
        am = _get_agent_metrics()
        collector = am.get_agent_metrics_collector()
        assert isinstance(collector, am.AgentMetricsCollector)

    def test_same_instance_on_repeated_calls(self):
        am = _get_agent_metrics()
        c1 = am.get_agent_metrics_collector()
        c2 = am.get_agent_metrics_collector()
        assert c1 is c2

    def test_thread_safe_singleton(self):
        am = _get_agent_metrics()
        results = []
        def _get():
            results.append(am.get_agent_metrics_collector())

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)

    def test_inner_double_check_branch_when_collector_set_inside_lock(self):
        am = _get_agent_metrics()

        class _InjectingLock:
            def __enter__(self):
                # Kilide girildiğinde singleton'ın başka bir thread tarafından
                # set edildiği senaryoyu simüle eder.
                am._COLLECTOR = am.AgentMetricsCollector()

            def __exit__(self, exc_type, exc, tb):
                return False

        am._COLLECTOR_LOCK = _InjectingLock()
        collector = am.get_agent_metrics_collector()
        assert collector is am._COLLECTOR
