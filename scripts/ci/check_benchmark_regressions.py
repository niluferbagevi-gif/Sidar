"""Compare pytest-benchmark artifacts with workload-aware regression limits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

IO_BOUND_BENCHMARKS = ("test_multi_user_session_message_workload_scales_with_concurrency",)


def parse_limit(value: str) -> float:
    """Parse the supported pytest-benchmark ``mean:N%`` syntax."""
    metric, separator, percent = value.partition(":")
    if metric != "mean" or not separator or not percent.endswith("%"):
        raise argparse.ArgumentTypeError("eşik 'mean:N%' biçiminde olmalıdır")
    try:
        result = float(percent[:-1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("eşik yüzdesi sayısal olmalıdır") from exc
    if result < 0:
        raise argparse.ArgumentTypeError("eşik yüzdesi negatif olamaz")
    return result


def _benchmarks(payload: dict[str, Any]) -> dict[str, tuple[float, str]]:
    return {
        str(item.get("fullname") or item["name"]): (
            float(item["stats"]["mean"]),
            str(item.get("extra_info", {}).get("workload_class", "")),
        )
        for item in payload.get("benchmarks", [])
        if item.get("fullname") or item.get("name")
    }


def find_regressions(
    baseline: dict[str, Any], current: dict[str, Any], *, default_limit: float, io_limit: float
) -> list[str]:
    """Return mean regressions, with a wider limit for noisy I/O workloads."""
    baseline_means = {name: mean for name, (mean, _) in _benchmarks(baseline).items()}
    failures = []
    for name, (current_mean, workload_class) in _benchmarks(current).items():
        baseline_mean = baseline_means.get(name)
        if baseline_mean is None or baseline_mean <= 0:
            continue
        change = ((current_mean / baseline_mean) - 1) * 100
        # `workload_class` yeni baseline'ların açık kontratıdır. İsim fallback'i,
        # metadata içermeyen daha eski ve hâlâ geçerli baseline artefaktları içindir.
        is_io_bound = workload_class == "io_bound" or any(
            token in name for token in IO_BOUND_BENCHMARKS
        )
        limit = io_limit if is_io_bound else default_limit
        if change > limit:
            failures.append(f"{name}: mean %{change:.2f} arttı (eşik %{limit:g})")
    return failures


def main() -> int:
    """Run the workload-aware, fail-closed comparison."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--default-limit", type=parse_limit, default=10.0)
    parser.add_argument("--io-limit", type=parse_limit, default=35.0)
    args = parser.parse_args()
    failures = find_regressions(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.current.read_text(encoding="utf-8")),
        default_limit=args.default_limit,
        io_limit=args.io_limit,
    )
    if failures:
        print("\n".join(f"❌ {failure}" for failure in failures))
        return 1
    print("✅ İş yükü duyarlı benchmark regresyon kapısı geçti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
