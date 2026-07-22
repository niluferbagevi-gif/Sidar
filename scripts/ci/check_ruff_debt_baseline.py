"""Enforce the temporary Ruff E501, docstring, and ASYNC240 debt baseline."""

from __future__ import annotations

import argparse
import json
import re
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


def _tightenable_counts(
    current: dict[str, int], baseline: dict[str, int]
) -> dict[str, tuple[int, int]]:
    """Return rules whose committed baseline is looser than the measured debt."""
    return {
        code: (current[code], baseline[code])
        for code in RUFF_DEBT_CODES
        if current[code] < baseline[code]
    }


def _replace_inline_table_value(table_body: str, code: str, value: int) -> str:
    """Replace a single `CODE = number` entry inside the inline TOML baseline table."""
    pattern = rf"({re.escape(code)}\s*=\s*)\d+"
    updated, count = re.subn(pattern, rf"\g<1>{value}", table_body, count=1)
    if count != 1:
        raise ValueError(f"Missing inline baseline key: {code}")
    return updated


_PINNED_E501_ASSERT_RE = re.compile(r'(assert debt\["e501_debt_baseline"\] == )(\d+)')


def _read_pinned_e501_baseline(test_path: Path) -> int:
    """Read the E501 baseline literal pinned in the dependency-profile-plan test.

    That test loads pyproject.toml itself and asserts a hardcoded number so any
    baseline change shows up as a deliberate diff; this literal must stay in
    lockstep with --pyproject's e501_debt_baseline or the pin goes stale.
    """
    content = test_path.read_text(encoding="utf-8")
    match = _PINNED_E501_ASSERT_RE.search(content)
    if match is None:
        raise ValueError(f"Missing pinned e501_debt_baseline assertion in {test_path}")
    return int(match.group(2))


def _write_pinned_e501_baseline(test_path: Path, value: int) -> None:
    """Rewrite the E501 baseline literal pinned in the dependency-profile-plan test."""
    content = test_path.read_text(encoding="utf-8")
    updated, count = _PINNED_E501_ASSERT_RE.subn(rf"\g<1>{value}", content, count=1)
    if count != 1:
        raise ValueError(f"Missing pinned e501_debt_baseline assertion in {test_path}")
    test_path.write_text(updated, encoding="utf-8")


def _write_tightened_baseline(
    pyproject_path: Path, current: dict[str, int], baseline: dict[str, int]
) -> None:
    """Persist `min(current, baseline)` back into the Ruff debt pyproject block."""
    content = pyproject_path.read_text(encoding="utf-8")
    e501_target = min(current["E501"], baseline["E501"])
    content, e501_count = re.subn(
        r"(^e501_debt_baseline\s*=\s*)\d+",
        rf"\g<1>{e501_target}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if e501_count != 1:
        raise ValueError("Missing e501_debt_baseline entry")

    table_match = re.search(
        r"(^docstring_async_debt_baseline\s*=\s*\{)(.*?)(\}\s*$)",
        content,
        flags=re.MULTILINE,
    )
    if table_match is None:
        raise ValueError("Missing docstring_async_debt_baseline inline table")

    table_body = table_match.group(2)
    for code in RUFF_DEBT_CODES:
        if code == "E501":
            continue
        table_body = _replace_inline_table_value(
            table_body, code, min(current[code], baseline[code])
        )
    content = content[: table_match.start(2)] + table_body + content[table_match.end(2) :]
    pyproject_path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Check that transitional Ruff debt counts do not exceed the baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        default=str(ROOT / "pyproject.toml"),
        help="Path to the pyproject.toml file containing the Ruff debt baseline.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the committed baseline to min(current, baseline) and exit.",
    )
    parser.add_argument(
        "--allow-stale-baseline",
        action="store_true",
        help="Do not fail when current debt is lower than the committed baseline.",
    )
    parser.add_argument(
        "--dependency-profile-test",
        default=str(ROOT / "tests/unit/test_dependency_profile_plan.py"),
        help=(
            "Path to the test pinning e501_debt_baseline as a literal, kept in "
            "sync with --pyproject."
        ),
    )
    args = parser.parse_args(argv)

    baseline = _load_baseline(Path(args.pyproject))
    missing = sorted(set(RUFF_DEBT_CODES) - set(baseline))
    if missing:
        print(f"Missing Ruff debt baseline entries: {', '.join(missing)}", file=sys.stderr)
        return 2

    dependency_profile_test = Path(args.dependency_profile_test)
    pinned_e501_baseline = _read_pinned_e501_baseline(dependency_profile_test)
    if not args.update and pinned_e501_baseline != baseline["E501"]:
        print(
            f"{dependency_profile_test} pins e501_debt_baseline={pinned_e501_baseline}, "
            f"which no longer matches {args.pyproject} (e501_debt_baseline="
            f"{baseline['E501']}).",
            file=sys.stderr,
        )
        print(
            "Run: uv run python scripts/ci/check_ruff_debt_baseline.py --update",
            file=sys.stderr,
        )
        return 1

    current = _count_diagnostics(_run_ruff_json(RUFF_DEBT_CODES))
    if args.update:
        _write_tightened_baseline(Path(args.pyproject), current, baseline)
        updated_baseline = _load_baseline(Path(args.pyproject))
        _write_pinned_e501_baseline(dependency_profile_test, updated_baseline["E501"])
        print(f"Ruff debt baseline ratcheted to: {_format_counts(updated_baseline)}")
        return 0

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

    stale_baselines = _tightenable_counts(current, baseline)
    if stale_baselines and not args.allow_stale_baseline:
        print("Ruff E501/docstring/ASYNC240 debt baseline can be tightened:", file=sys.stderr)
        for code, (actual, expected) in stale_baselines.items():
            print(f"- {code}: {actual} < {expected}", file=sys.stderr)
        print(f"Current counts: {_format_counts(current)}", file=sys.stderr)
        print(f"Baseline counts: {_format_counts(baseline)}", file=sys.stderr)
        print(
            "Run: uv run python scripts/ci/check_ruff_debt_baseline.py --update",
            file=sys.stderr,
        )
        return 1

    print(f"Ruff E501/docstring/ASYNC240 debt matches ratchet baseline: {_format_counts(current)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
