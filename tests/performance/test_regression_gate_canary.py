"""Canary benchmark used solely to verify the pytest-benchmark regression gate.

Bu dosya, `scripts/ci/verify_benchmark_regression_gate.sh` betiği tarafından
opt-in olarak çalıştırılır. Normal `run_tests.sh` akışında modül seviyesinde
skip edilir ki gerçek `baseline` ölçümlerini kirletmesin.

Davranış:
- ``SIDAR_BENCH_GATE_CANARY`` ortam değişkeni ``1`` değilse tüm testler skip
  edilir; dolayısıyla varsayılan benchmark koşusunda görünmez.
- ``SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS`` set edilirse, canary ölçülen işin
  başına deterministik bir ``time.sleep`` enjekte eder. Bu sayede doğrulayıcı
  script önce temiz bir baseline kaydedip ardından yapay yavaşlatma ile aynı
  testi çalıştırarak ``--benchmark-compare-fail`` kapısının gerçekten
  tetiklendiğini doğrulayabilir.
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(
        os.environ.get("SIDAR_BENCH_GATE_CANARY") != "1",
        reason="Regression gate canary yalnızca SIDAR_BENCH_GATE_CANARY=1 iken çalışır.",
    ),
]

pytest.importorskip("pytest_benchmark")


def _injected_slowdown_seconds() -> float:
    raw = os.environ.get("SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS", "0")
    try:
        millis = float(raw)
    except ValueError:
        return 0.0
    return max(millis, 0.0) / 1000.0


def _canary_workload(slowdown_s: float) -> int:
    if slowdown_s > 0:
        time.sleep(slowdown_s)
    total = 0
    for index in range(2_000):
        total += (index * index) % 9973
    return total


def test_regression_gate_canary(benchmark) -> None:
    slowdown_s = _injected_slowdown_seconds()
    result = benchmark(_canary_workload, slowdown_s)
    assert result > 0
    benchmark.extra_info["injected_slowdown_ms"] = round(slowdown_s * 1000, 3)
