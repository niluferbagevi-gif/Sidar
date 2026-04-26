from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_coverage_ratio(path: Path) -> float:
    root = ET.parse(path).getroot()
    line_rate = root.attrib.get("line-rate")
    if line_rate is None:
        raise RuntimeError("coverage.xml içinde 'line-rate' alanı bulunamadı.")
    return float(line_rate)


def _extract_benchmark_summary(path: Path) -> tuple[float, int]:
    payload = _load_json(path, default={})
    benchmarks = payload.get("benchmarks", [])
    if not isinstance(benchmarks, list) or not benchmarks:
        raise RuntimeError("benchmark JSON içinde ölçüm bulunamadı.")

    means: list[float] = []
    for item in benchmarks:
        stats = item.get("stats", {})
        if not isinstance(stats, dict):
            continue
        mean = stats.get("mean")
        if mean is None:
            continue
        means.append(float(mean))

    if not means:
        raise RuntimeError("benchmark JSON içinde 'stats.mean' alanı bulunamadı.")
    return statistics.mean(means), len(means)


def _pct_delta(current: float, baseline: float) -> float:
    return ((current - baseline) / baseline) * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark JSON ve coverage.xml için trend kalite kapısı")
    parser.add_argument("--benchmark-json", required=True)
    parser.add_argument("--coverage-xml", required=True)
    parser.add_argument("--history-json", required=True)
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--max-regression-pct", type=float, default=15.0)
    args = parser.parse_args()

    benchmark_json = Path(args.benchmark_json)
    coverage_xml = Path(args.coverage_xml)
    history_json = Path(args.history_json)
    window = max(1, int(args.window))
    max_regression_pct = max(0.1, float(args.max_regression_pct))

    if not benchmark_json.exists():
        print(f"Benchmark JSON bulunamadı: {benchmark_json}")
        return 2
    if not coverage_xml.exists():
        print(f"Coverage XML bulunamadı: {coverage_xml}")
        return 2

    benchmark_mean_s, benchmark_count = _extract_benchmark_summary(benchmark_json)
    coverage_ratio = _extract_coverage_ratio(coverage_xml)

    history = _load_json(history_json, default={"runs": []})
    runs = history.setdefault("runs", [])

    failed = False
    recent = runs[-window:]
    if recent:
        bench_baseline = statistics.median(float(item["benchmark_mean_seconds"]) for item in recent)
        cov_baseline = statistics.median(float(item["coverage_line_rate"]) for item in recent)

        bench_delta = _pct_delta(benchmark_mean_s, bench_baseline)
        cov_delta = _pct_delta(coverage_ratio, cov_baseline)

        print(
            "[trend] benchmark_mean_seconds "
            f"current={benchmark_mean_s:.6f} baseline={bench_baseline:.6f} delta={bench_delta:+.2f}%"
        )
        print(
            "[trend] coverage_line_rate "
            f"current={coverage_ratio:.6f} baseline={cov_baseline:.6f} delta={cov_delta:+.2f}%"
        )

        if bench_delta > max_regression_pct:
            print(
                "[ALARM] Benchmark mean süresi geçmiş medyana göre "
                f"{bench_delta:+.2f}% kötüleşti (eşik +{max_regression_pct:.2f}%)."
            )
            failed = True
        if cov_delta < -max_regression_pct:
            print(
                "[ALARM] Coverage oranı geçmiş medyana göre "
                f"{cov_delta:+.2f}% düştü (eşik -{max_regression_pct:.2f}%)."
            )
            failed = True
    else:
        print("[trend] Geçmiş veri yok; mevcut run baseline olarak kaydediliyor.")

    runs.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "benchmark_mean_seconds": benchmark_mean_s,
            "benchmark_count": benchmark_count,
            "coverage_line_rate": coverage_ratio,
            "benchmark_json": str(benchmark_json),
            "coverage_xml": str(coverage_xml),
        }
    )
    history["runs"] = runs[-500:]
    history_json.parent.mkdir(parents=True, exist_ok=True)
    history_json.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
