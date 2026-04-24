#!/usr/bin/env bash
set -euo pipefail

JUNIT_PATH="${1:-gpu-inference-quality-gate.junit.xml}"

export RUN_GPU_STRESS="${RUN_GPU_STRESS:-1}"

# Baseline referansı (2026-04):
# - TTFT ~93ms
# - Single inference latency ~120ms
# Gate bütçeleri jitter payı bırakarak bunun üstünde tutulur.
export GPU_BENCH_TTFT_BUDGET="${GPU_BENCH_TTFT_BUDGET:-0.2}"        # 200ms
export GPU_BENCH_LATENCY_BUDGET="${GPU_BENCH_LATENCY_BUDGET:-0.25}" # 250ms
export GPU_BENCH_WARMUP_ROUNDS="${GPU_BENCH_WARMUP_ROUNDS:-5}"
export GPU_BENCH_ROUNDS="${GPU_BENCH_ROUNDS:-3}"
export GPU_BENCH_NUM_PREDICT="${GPU_BENCH_NUM_PREDICT:-128}"

uv run pytest -q \
  tests/performance/test_gpu_benchmark.py::test_gpu_time_to_first_token \
  tests/performance/test_gpu_benchmark.py::test_gpu_single_inference_latency \
  --benchmark-disable-gc \
  --junitxml="${JUNIT_PATH}"

python - <<'PY' "${JUNIT_PATH}"
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

junit_path = sys.argv[1]
root = ET.parse(junit_path).getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
if suite is None:
    raise SystemExit("Junit raporu okunamadı: testsuite düğümü yok.")

skipped = int(suite.attrib.get("skipped", "0"))
failures = int(suite.attrib.get("failures", "0"))
errors = int(suite.attrib.get("errors", "0"))

if failures or errors:
    raise SystemExit(
        "GPU inference quality gate başarısız: "
        "TTFT/latency assertion veya runtime hatası var."
    )
if skipped:
    raise SystemExit(
        "GPU inference quality gate başarısız: test skip edildi "
        "(GPU/Ollama/ortam hazır değil)."
    )
print("GPU inference quality gate geçti: TTFT + latency testleri başarılı.")
PY
