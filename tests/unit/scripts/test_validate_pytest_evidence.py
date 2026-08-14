"""Tests for commit-bound pytest CI evidence validation."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.validate_pytest_evidence import main, validate_evidence


def _artifacts(
    tmp_path: Path, *, tests: int = 2, aggregate: str = "passed"
) -> tuple[Path, Path, Path]:
    summary = tmp_path / "test-summary.json"
    summary.write_text(json.dumps({"aggregate": aggregate}), encoding="utf-8")
    junit = tmp_path / "pytest"
    junit.mkdir()
    cases = "".join(f'<testcase name="test_{index}" />' for index in range(tests))
    (junit / "backend-unit.xml").write_text(
        f'<testsuite tests="{tests}">{cases}</testsuite>', encoding="utf-8"
    )
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": 100.0}}), encoding="utf-8")
    return summary, junit, coverage


def test_validate_evidence_binds_nonzero_pytest_and_coverage_to_commit(tmp_path: Path) -> None:
    summary, junit, coverage = _artifacts(tmp_path)

    errors, evidence = validate_evidence(
        summary_path=summary,
        junit_dir=junit,
        coverage_path=coverage,
        commit_sha="abc123",
    )

    assert errors == []
    assert evidence == {
        "schema_version": 1,
        "commit_sha": "abc123",
        "pytest_executed": True,
        "junit_report_count": 1,
        "pytest_test_count": 2,
        "coverage_percent": 100.0,
        "summary_aggregate": "passed",
        "valid": True,
    }


def test_validate_evidence_rejects_missing_or_skipped_pytest(tmp_path: Path) -> None:
    summary, junit, coverage = _artifacts(tmp_path, tests=0, aggregate="failed")

    errors, evidence = validate_evidence(
        summary_path=summary,
        junit_dir=junit,
        coverage_path=coverage,
        commit_sha="",
    )

    assert evidence["valid"] is False
    assert evidence["pytest_executed"] is False
    assert "backend pytest JUnit kanıtı yok veya sıfır test içeriyor" in errors
    assert "test summary aggregate=passed değil" in errors
    assert "CI commit SHA boş" in errors


def test_cli_always_writes_invalid_attestation_for_diagnostics(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"

    assert main(["--output", str(output), "--commit-sha", "deadbeef"]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["valid"] is False
