"""Verify that the pytest-benchmark regression gate fails on a known slowdown.

This script is intentionally synthetic: it creates an isolated temporary
benchmark, saves a fast baseline, reruns the same benchmark with a deterministic
sleep, and expects ``--benchmark-compare-fail`` to return a non-zero exit code.
It does not touch the repository's real ``.benchmarks`` directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_MODULE = '''\
from __future__ import annotations

import os
import time


def _workload() -> int:
    delay = float(os.getenv("SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS", "0"))
    if delay > 0:
        time.sleep(delay)
    return sum(range(32))


def test_synthetic_benchmark_regression_gate(benchmark):
    assert benchmark(_workload) == 496
'''


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _print_result(title: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"\n=== {title} (exit={result.returncode}) ===")
    print(result.stdout.rstrip() or "<no output>")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sidar-benchmark-gate-") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        test_file = tmp_dir / "test_synthetic_benchmark_gate.py"
        storage_dir = tmp_dir / ".benchmarks"
        test_file.write_text(TEST_MODULE, encoding="utf-8")

        common_cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(test_file),
            "--benchmark-only",
            "--benchmark-min-rounds=3",
            "--benchmark-max-time=0.03",
            "--benchmark-warmup=off",
            "--benchmark-disable-gc",
            f"--benchmark-storage={storage_dir}",
        ]

        baseline_env = os.environ.copy()
        baseline_env["SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS"] = "0"
        baseline = _run(
            [*common_cmd, "--benchmark-save=baseline"],
            cwd=tmp_dir,
            env=baseline_env,
        )
        _print_result("baseline capture", baseline)
        if baseline.returncode != 0:
            print("❌ Synthetic benchmark baseline üretilemedi; regresyon kapısı doğrulanamadı.")
            return baseline.returncode or 1

        baseline_files = sorted(storage_dir.rglob("*_baseline.json"))
        if not baseline_files:
            print(f"❌ Baseline JSON bulunamadı: {storage_dir}")
            return 1
        baseline_file = baseline_files[-1]
        print(f"ℹ️ Synthetic baseline: {baseline_file}")

        regression_env = os.environ.copy()
        regression_env["SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS"] = "0.003"
        regression = _run(
            [
                *common_cmd,
                f"--benchmark-compare={baseline_file}",
                "--benchmark-compare-fail=mean:50%",
            ],
            cwd=tmp_dir,
            env=regression_env,
        )
        _print_result("intentional slowdown compare", regression)
        if regression.returncode == 0:
            print(
                "❌ Benchmark regresyon kapısı beklenen yapay yavaşlamayı yakalamadı "
                "(--benchmark-compare-fail=mean:50%)."
            )
            return 1

        output = regression.stdout.lower()
        if "benchmark" not in output or "regression" not in output:
            print("❌ Benchmark compare çıktısı regresyon sinyali içermiyor; kapı semantiği belirsiz.")
            return 1

        print("✅ Benchmark regresyon kapısı yapay yavaşlamada beklendiği gibi fail-closed çalışıyor.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
