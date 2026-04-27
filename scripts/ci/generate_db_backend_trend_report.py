from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BackendStats:
    backend: str
    mean_ms: float
    stddev_ms: float
    max_ms: float


def _to_ms(value: Any) -> float:
    try:
        return float(value) * 1000.0
    except (TypeError, ValueError):
        return 0.0


def _detect_backend(item: dict[str, Any]) -> str | None:
    name = str(item.get("name", "")).lower()
    fullname = str(item.get("fullname", "")).lower()
    params = item.get("params")
    joined = " ".join(
        part
        for part in [
            name,
            fullname,
            json.dumps(params, ensure_ascii=False).lower() if params is not None else "",
        ]
        if part
    )
    if "postgresql" in joined:
        return "postgresql"
    if "sqlite" in joined:
        return "sqlite"
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: python scripts/ci/generate_db_backend_trend_report.py <benchmark.json> <out_dir>"
        )
        return 2

    bench_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(bench_path.read_text(encoding="utf-8"))
    benchmarks = payload.get("benchmarks", [])
    rows: list[BackendStats] = []

    for item in benchmarks:
        if not isinstance(item, dict):
            continue
        backend = _detect_backend(item)
        if backend is None:
            continue
        stats = item.get("stats", {})
        if not isinstance(stats, dict):
            continue
        rows.append(
            BackendStats(
                backend=backend,
                mean_ms=round(_to_ms(stats.get("mean")), 3),
                stddev_ms=round(_to_ms(stats.get("stddev")), 3),
                max_ms=round(_to_ms(stats.get("max")), 3),
            )
        )

    if not rows:
        print("SQLite/PostgreSQL benchmark satırı bulunamadı.")
        return 1

    summary = {
        row.backend: {"mean_ms": row.mean_ms, "stddev_ms": row.stddev_ms, "max_ms": row.max_ms}
        for row in rows
    }
    (out_dir / "db_backend_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    def _bar(value: float, scale: float = 10.0) -> str:
        size = max(1, int(round(value / scale)))
        return "█" * min(size, 60)

    sqlite = summary.get("sqlite")
    pg = summary.get("postgresql")

    lines = [
        "# SQLite vs PostgreSQL Benchmark Trend (Release Artifact)",
        "",
        "| Backend | Mean (ms) | StdDev (ms) | Max (ms) |",
        "|---|---:|---:|---:|",
    ]
    for row in sorted(rows, key=lambda x: x.backend):
        lines.append(
            f"| {row.backend} | {row.mean_ms:.3f} | {row.stddev_ms:.3f} | {row.max_ms:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Visual trend (bar, mean latency)",
            "",
            f"- sqlite:      {_bar(sqlite['mean_ms']) if sqlite else 'n/a'} ({sqlite['mean_ms']:.3f} ms)"
            if sqlite
            else "- sqlite: n/a",
            f"- postgresql:  {_bar(pg['mean_ms']) if pg else 'n/a'} ({pg['mean_ms']:.3f} ms)"
            if pg
            else "- postgresql: n/a",
            "",
            "> Not: Bu rapor release artifact olarak saklanır ve release'ler arası trend karşılaştırması için kullanılır.",
        ]
    )

    (out_dir / "trend.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
