from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _extract_value(stats: dict[str, Any], candidates: list[str]) -> float | None:
    for key in candidates:
        raw = stats.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _ms(raw_seconds: float | None) -> float | None:
    if raw_seconds is None:
        return None
    return raw_seconds * 1000.0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/ci/check_auth_benchmark_thresholds.py <benchmark.json>")
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Benchmark JSON bulunamadı: {path}")
        return 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    benchmarks = payload.get("benchmarks", [])
    if not isinstance(benchmarks, list) or not benchmarks:
        print("Benchmark kaydı boş.")
        return 2

    p95_budget_ms = float(os.getenv("AUTH_BENCH_P95_BUDGET_MS", "950"))
    p99_budget_ms = float(os.getenv("AUTH_BENCH_P99_BUDGET_MS", "1200"))

    failed = False
    for item in benchmarks:
        name = str(item.get("name", "unknown"))
        if "password_" not in name:
            continue
        stats = item.get("stats", {})
        if not isinstance(stats, dict):
            continue

        p95_ms = _ms(_extract_value(stats, ["q95", "q_95", "p95"]))
        p99_ms = _ms(_extract_value(stats, ["q99", "q_99", "p99"]))
        stddev_ms = _ms(_extract_value(stats, ["stddev"]))
        max_ms = _ms(_extract_value(stats, ["max"]))

        print(
            f"[auth-bench] {name}: "
            f"p95={p95_ms if p95_ms is not None else 'n/a'}ms, "
            f"p99={p99_ms if p99_ms is not None else 'n/a'}ms, "
            f"stddev={stddev_ms if stddev_ms is not None else 'n/a'}ms, "
            f"max={max_ms if max_ms is not None else 'n/a'}ms"
        )

        if p95_ms is not None and p95_ms > p95_budget_ms:
            print(f"[ALARM] {name} p95 bütçeyi aştı: {p95_ms:.2f}ms > {p95_budget_ms:.2f}ms")
            failed = True
        if p99_ms is not None and p99_ms > p99_budget_ms:
            print(f"[ALARM] {name} p99 bütçeyi aştı: {p99_ms:.2f}ms > {p99_budget_ms:.2f}ms")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
