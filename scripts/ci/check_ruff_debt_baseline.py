"""Enforce the temporary Ruff E501, docstring, and ASYNC240 debt baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUFF_DEBT_CODES = (
    "E501",
    "D200",
    "D202",
    "D205",
    "D209",
    "D212",
    "D403",
    "D415",
    "D417",
    "ASYNC240",
)


def _load_baseline(pyproject_path: Path) -> dict[str, int]:
    """Load the machine-readable Ruff debt ceiling from pyproject metadata."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    ruff_debt = data["tool"]["sidar"]["ruff_debt"]
    raw_baseline = {
        "E501": ruff_debt["e501_debt_baseline"],
        **ruff_debt["docstring_async_debt_baseline"],
    }
    return {str(code): int(limit) for code, limit in raw_baseline.items()}


def _run_ruff_json(codes: tuple[str, ...]) -> list[dict[str, Any]]:
    """Run Ruff for ignored campaign rules and return JSON diagnostics."""
    command = [
        "uv",
        "run",
        "ruff",
        "check",
        ".",
        "--select",
        ",".join(codes),
        "--output-format",
        "json",
    ]
    completed = subprocess.run(  # nosec B603  # command list is internally constructed, shell=False.
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)
    if not completed.stdout.strip():
        return []
    return list(json.loads(completed.stdout))


def _count_diagnostics(diagnostics: list[dict[str, Any]]) -> dict[str, int]:
    """Count Ruff diagnostics by rule code."""
    counts = Counter(str(item.get("code", "")) for item in diagnostics)
    return {code: counts.get(code, 0) for code in RUFF_DEBT_CODES}


def _format_counts(counts: dict[str, int]) -> str:
    """Format rule counts for human-readable CI output."""
    return ", ".join(f"{code}={counts.get(code, 0)}" for code in RUFF_DEBT_CODES)


def main(argv: list[str] | None = None) -> int:
    """Check that transitional Ruff debt counts do not exceed the baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        default=str(ROOT / "pyproject.toml"),
        help="Path to the pyproject.toml file containing the Ruff debt baseline.",
    )
    args = parser.parse_args(argv)

    baseline = _load_baseline(Path(args.pyproject))
    missing = sorted(set(RUFF_DEBT_CODES) - set(baseline))
    if missing:
        print(f"Missing Ruff debt baseline entries: {', '.join(missing)}", file=sys.stderr)
        return 2

    current = _count_diagnostics(_run_ruff_json(RUFF_DEBT_CODES))
    regressions = {
        code: (current[code], baseline[code])
        for code in RUFF_DEBT_CODES
        if current[code] > baseline[code]
    }
    if regressions:
        print("Ruff E501/docstring/ASYNC240 debt baseline grew:", file=sys.stderr)
        for code, (actual, expected) in regressions.items():
            print(f"- {code}: {actual} > {expected}", file=sys.stderr)
        print(f"Current counts: {_format_counts(current)}", file=sys.stderr)
        print(f"Baseline counts: {_format_counts(baseline)}", file=sys.stderr)
        return 1

    print(f"Ruff E501/docstring/ASYNC240 debt within baseline: {_format_counts(current)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
