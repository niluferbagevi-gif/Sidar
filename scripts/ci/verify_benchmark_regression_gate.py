"""Verify that pytest-benchmark's compare-fail gate catches a known slowdown.

The script creates an isolated synthetic benchmark suite, records a fast baseline,
then reruns the same benchmark with an intentionally slower workload. It succeeds
only when the second pytest-benchmark run fails because --benchmark-compare-fail
raises a regression alarm.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

_FAST_DELAY_SECONDS = "0.001"
_SLOW_DELAY_SECONDS = "0.030"
_COMPARE_FAIL_THRESHOLD = "mean:50%"


def _write_synthetic_benchmark(workdir: Path) -> Path:
    test_file = workdir / "test_synthetic_benchmark_regression.py"
    test_file.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os
            import time


            def test_synthetic_benchmark_regression(benchmark):
                delay_seconds = float(os.environ["SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS"])

                def workload() -> None:
                    time.sleep(delay_seconds)

                benchmark.pedantic(workload, rounds=5, iterations=1, warmup_rounds=1)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return test_file


def _run_pytest(workdir: Path, delay_seconds: str, *extra_args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SIDAR_SYNTHETIC_BENCH_DELAY_SECONDS": delay_seconds,
    }
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "test_synthetic_benchmark_regression.py",
        "--benchmark-disable-gc",
        "--benchmark-warmup=off",
        "--benchmark-min-rounds=1",
        *extra_args,
    ]
    return subprocess.run(command, cwd=workdir, env=env, text=True, capture_output=True, check=False)


def _print_run(label: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"=== {label} (exit={result.returncode}) ===")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sidar-benchmark-gate-") as tmp:
        workdir = Path(tmp)
        _write_synthetic_benchmark(workdir)

        baseline = _run_pytest(
            workdir,
            _FAST_DELAY_SECONDS,
            "--benchmark-save=baseline",
        )
        _print_run("baseline", baseline)
        if baseline.returncode != 0:
            print("❌ Sentetik benchmark baseline kaydı oluşturulamadı.", file=sys.stderr)
            return baseline.returncode or 1

        baseline_files = sorted((workdir / ".benchmarks").glob("**/*_baseline.json"))
        if not baseline_files:
            print("❌ Sentetik benchmark baseline dosyası bulunamadı.", file=sys.stderr)
            return 1
        baseline_file = baseline_files[-1]

        regression = _run_pytest(
            workdir,
            _SLOW_DELAY_SECONDS,
            f"--benchmark-compare={baseline_file}",
            f"--benchmark-compare-fail={_COMPARE_FAIL_THRESHOLD}",
        )
        _print_run("intentional-regression", regression)
        if regression.returncode == 0:
            print(
                "❌ Benchmark regresyon kapısı yapay yavaşlamayı yakalayamadı; "
                "--benchmark-compare-fail sessiz kalıyor.",
                file=sys.stderr,
            )
            return 1

        combined_output = f"{regression.stdout}\n{regression.stderr}".lower()
        if (
            "performance regression" not in combined_output
            and "performance has regressed" not in combined_output
            and "regression" not in combined_output
        ):
            print(
                "❌ Yavaş koşu başarısız oldu ancak çıktı regresyon alarmı içermiyor.",
                file=sys.stderr,
            )
            return 1

    print(
        "✅ Benchmark regresyon kapısı doğrulandı: kayıtlı baseline'a göre yapay yavaşlama "
        "--benchmark-compare-fail ile fail üretti."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
