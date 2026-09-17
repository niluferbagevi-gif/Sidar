from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.validate_test_summary import main, validate_summary


def _summary(
    *,
    production_ready: bool,
    status: str,
    validation_class: str,
    release_blocking: bool,
    exit_code: int,
) -> dict[str, object]:
    return {
        "code_quality_ready": production_ready,
        "integration_ready": production_ready,
        "production_compose_boot": "passed" if production_ready else "not_run",
        "benchmark_compare": "compared_enforced" if production_ready else "not_run",
        "benchmark_baseline": {
            "file": ".benchmarks/Linux-CPython-3.11/baseline.json" if production_ready else None,
            "compare_required": production_ready,
            "compare_enforced": production_ready,
        },
        "local_readiness_passed": production_ready,
        "release_evidence_complete": False,
        "release_ready": False,
        "production_ready": production_ready,
        "production_readiness": "passed" if production_ready else "not_run",
        "production_readiness_detail": {
            "status": status,
            "reason": "test fixture",
            "required_command": "make production-readiness",
            "equivalent_direct_command": (
                "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
                "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
            ),
            "validation_class": validation_class,
            "release_blocking": release_blocking,
            "release_gate_exit_code": exit_code,
        },
    }


def test_release_mode_accepts_production_ready_summary() -> None:
    summary = _summary(
        production_ready=True,
        status="passed",
        validation_class="production_readiness",
        release_blocking=False,
        exit_code=0,
    )

    assert validate_summary(summary, "release") == []


def test_release_mode_rejects_development_summary() -> None:
    summary = _summary(
        production_ready=False,
        status="development_only",
        validation_class="development_full",
        release_blocking=True,
        exit_code=10,
    )

    errors = validate_summary(summary, "release")

    assert "release mode production_ready=true bekler" in errors
    assert "release mode validation_class=production_readiness bekler" in errors
    assert "release mode release_gate_exit_code=0 bekler" in errors
    assert "release/merge öncesi zorunlu komut: make production-readiness" in errors
    assert any("SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all" in e for e in errors)


def test_release_mode_rejects_seeded_but_not_compared_benchmark() -> None:
    summary = _summary(
        production_ready=True,
        status="passed",
        validation_class="production_readiness",
        release_blocking=False,
        exit_code=0,
    )
    summary["benchmark_compare"] = "seeded_not_compared"

    errors = validate_summary(summary, "release")

    assert "release mode benchmark_compare=compared_enforced bekler" in errors


def test_summary_rejects_release_ready_without_complete_evidence() -> None:
    summary = _summary(
        production_ready=False,
        status="development_only",
        validation_class="development_full",
        release_blocking=True,
        exit_code=10,
    )
    summary["release_ready"] = True

    errors = validate_summary(summary, "development")

    assert "release_ready=true için release_evidence_complete=true olmalıdır" in errors


def test_development_mode_validates_schema_without_requiring_release() -> None:
    summary = _summary(
        production_ready=False,
        status="development_only",
        validation_class="development_full",
        release_blocking=True,
        exit_code=10,
    )

    assert validate_summary(summary, "development") == []


def test_cli_fails_release_mode_when_production_ready_false(tmp_path: Path, capsys) -> None:
    summary_path = tmp_path / "test-summary.json"
    summary_path.write_text(
        json.dumps(
            _summary(
                production_ready=False,
                status="development_only",
                validation_class="development_full",
                release_blocking=True,
                exit_code=10,
            )
        ),
        encoding="utf-8",
    )

    assert main(["--mode", "release", "--summary", str(summary_path)]) == 1
    captured = capsys.readouterr()
    assert "production_ready=true" in captured.err
    assert "make production-readiness" in captured.err
    assert "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all" in captured.err


def test_cli_passes_release_mode_when_production_ready_true(tmp_path: Path, capsys) -> None:
    summary_path = tmp_path / "test-summary.json"
    summary_path.write_text(
        json.dumps(
            _summary(
                production_ready=True,
                status="passed",
                validation_class="production_readiness",
                release_blocking=False,
                exit_code=0,
            )
        ),
        encoding="utf-8",
    )

    assert main(["--mode", "release", "--summary", str(summary_path)]) == 0
    captured = capsys.readouterr()
    assert "test-summary doğrulandı" in captured.out
