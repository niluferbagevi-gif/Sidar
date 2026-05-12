"""Progressively ratchet the repository coverage quality gate.

The local and CI coverage gate is stored in ``.coveragerc`` under
``[report] fail_under``.  This helper reads the latest coverage.py JSON report
and raises that gate to the highest configured step that has already been
reached, without ever lowering the existing threshold.
"""

from __future__ import annotations

import argparse
import json
import math
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RatchetResult:
    """Outcome of a coverage gate ratchet attempt."""

    current_gate: float
    measured_coverage: float
    target_gate: float
    updated: bool


def _parse_percentage(value: Any, *, field_name: str) -> float:
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        percentage = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} sayısal bir yüzde olmalı: {value!r}") from exc
    if not math.isfinite(percentage) or percentage < 0:
        raise ValueError(f"{field_name} negatif/sonsuz olamaz: {value!r}")
    return min(100.0, percentage)


def read_fail_under(coveragerc_path: Path) -> float:
    """Read ``[report] fail_under`` from a coverage.py config file."""

    cfg = ConfigParser()
    cfg.read(coveragerc_path, encoding="utf-8")
    return _parse_percentage(cfg.get("report", "fail_under", fallback="0"), field_name="fail_under")


def read_total_coverage(coverage_json_path: Path) -> float:
    """Read total coverage percentage from coverage.py JSON output."""

    data = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    totals = data.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("coverage.json içinde totals alanı bulunamadı.")

    if "percent_covered" in totals:
        return _parse_percentage(totals["percent_covered"], field_name="totals.percent_covered")
    if "percent_covered_display" in totals:
        return _parse_percentage(
            totals["percent_covered_display"], field_name="totals.percent_covered_display"
        )
    raise ValueError("coverage.json totals içinde percent_covered alanı bulunamadı.")


def compute_next_gate(
    measured_coverage: float,
    current_gate: float,
    *,
    step: float = 5.0,
    min_gate: float = 5.0,
    max_gate: float = 100.0,
) -> float:
    """Return the next non-decreasing coverage gate for a measured percentage."""

    step = _parse_percentage(step, field_name="step")
    min_gate = _parse_percentage(min_gate, field_name="min_gate")
    max_gate = _parse_percentage(max_gate, field_name="max_gate")
    measured_coverage = _parse_percentage(measured_coverage, field_name="measured_coverage")
    current_gate = _parse_percentage(current_gate, field_name="current_gate")

    if step <= 0:
        raise ValueError("step sıfırdan büyük olmalı.")
    if min_gate > max_gate:
        raise ValueError("min_gate, max_gate değerinden büyük olamaz.")

    reached_step = math.floor(measured_coverage / step) * step
    target = max(current_gate, min_gate, reached_step)
    return round(min(max_gate, target), 2)


def _format_gate(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def write_fail_under(coveragerc_path: Path, new_gate: float) -> None:
    """Update only the ``fail_under`` line while preserving the rest of the file."""

    lines = coveragerc_path.read_text(encoding="utf-8").splitlines(keepends=True)
    formatted = _format_gate(new_gate)
    in_report = False
    inserted = False
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_report and not inserted:
                output.append(f"fail_under = {formatted}\n")
                inserted = True
            in_report = stripped.lower() == "[report]"

        if in_report and stripped.lower().startswith("fail_under") and "=" in stripped:
            prefix = line[: len(line) - len(line.lstrip())]
            newline = "\n" if line.endswith("\n") else ""
            output.append(f"{prefix}fail_under = {formatted}{newline}")
            inserted = True
            continue
        output.append(line)

    if in_report and not inserted:
        output.append(f"fail_under = {formatted}\n")
        inserted = True
    if not inserted:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.extend(["[report]\n", f"fail_under = {formatted}\n"])

    coveragerc_path.write_text("".join(output), encoding="utf-8")


def ratchet_coverage_gate(
    *,
    coveragerc_path: Path,
    coverage_json_path: Path,
    step: float = 5.0,
    min_gate: float = 5.0,
    max_gate: float = 100.0,
) -> RatchetResult:
    """Raise ``fail_under`` to the reached step if coverage improved enough."""

    current_gate = read_fail_under(coveragerc_path)
    measured_coverage = read_total_coverage(coverage_json_path)
    target_gate = compute_next_gate(
        measured_coverage,
        current_gate,
        step=step,
        min_gate=min_gate,
        max_gate=max_gate,
    )
    updated = target_gate > current_gate
    if updated:
        write_fail_under(coveragerc_path, target_gate)
    return RatchetResult(
        current_gate=current_gate,
        measured_coverage=measured_coverage,
        target_gate=target_gate,
        updated=updated,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coverage gate ratcheting helper for Sidar.")
    parser.add_argument("--coveragerc", default=".coveragerc", type=Path)
    parser.add_argument("--coverage-json", default="coverage.json", type=Path)
    parser.add_argument("--step", default=5.0, type=float)
    parser.add_argument("--min-gate", default=5.0, type=float)
    parser.add_argument("--max-gate", default=100.0, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = ratchet_coverage_gate(
        coveragerc_path=args.coveragerc,
        coverage_json_path=args.coverage_json,
        step=args.step,
        min_gate=args.min_gate,
        max_gate=args.max_gate,
    )
    if result.updated:
        print(
            "Coverage gate ratcheted: "
            f"%{_format_gate(result.current_gate)} -> %{_format_gate(result.target_gate)} "
            f"(measured=%{result.measured_coverage:.2f})"
        )
    else:
        print(
            "Coverage gate unchanged: "
            f"%{_format_gate(result.current_gate)} "
            f"(measured=%{result.measured_coverage:.2f}, reached=%{_format_gate(result.target_gate)})"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
