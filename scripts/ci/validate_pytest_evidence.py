#!/usr/bin/env python3
"""Fail closed unless the current CI run produced real pytest/coverage evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


def validate_evidence(
    *, summary_path: Path, junit_dir: Path, coverage_path: Path, commit_sha: str
) -> tuple[list[str], dict[str, Any]]:
    """Validate evidence files and return errors plus a normalized attestation."""
    errors: list[str] = []
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        summary = {}
        errors.append(f"test summary okunamadı: {exc}")

    test_count = 0
    report_count = 0
    for report in sorted(junit_dir.glob("backend-*.xml")):
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError, DefusedXmlException) as exc:
            errors.append(f"JUnit okunamadı ({report}): {exc}")
            continue
        report_count += 1
        test_count += sum(1 for _ in root.iter("testcase"))
    if report_count == 0 or test_count == 0:
        errors.append("backend pytest JUnit kanıtı yok veya sıfır test içeriyor")

    try:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage_percent = float(coverage["totals"]["percent_covered"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        coverage_percent = 0.0
        errors.append(f"coverage JSON kanıtı okunamadı: {exc}")

    if summary.get("aggregate") != "passed":
        errors.append("test summary aggregate=passed değil")
    if not commit_sha.strip():
        errors.append("CI commit SHA boş")

    attestation = {
        "schema_version": 1,
        "commit_sha": commit_sha.strip(),
        "pytest_executed": test_count > 0,
        "junit_report_count": report_count,
        "pytest_test_count": test_count,
        "coverage_percent": coverage_percent,
        "summary_aggregate": summary.get("aggregate", "missing"),
        "valid": not errors,
    }
    return errors, attestation


def main(argv: list[str] | None = None) -> int:
    """Validate artifacts and write a commit-bound CI attestation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=Path("artifacts/test-summary.json"))
    parser.add_argument("--junit-dir", type=Path, default=Path("artifacts/pytest"))
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/pytest-evidence.json"))
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", ""))
    args = parser.parse_args(argv)

    errors, attestation = validate_evidence(
        summary_path=args.summary,
        junit_dir=args.junit_dir,
        coverage_path=args.coverage,
        commit_sha=args.commit_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    if errors:
        print("Pytest CI evidence invalid:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print(
        f"Pytest CI evidence valid: commit={attestation['commit_sha']} "
        f"tests={attestation['pytest_test_count']} coverage={attestation['coverage_percent']:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
