from __future__ import annotations

from pathlib import Path

import pytest

from scripts import auto_remediate_tests as auto


def test_parse_failure_output_extracts_targets_and_root_cause() -> None:
    output = "\n".join(
        [
            "tests/unit/core/test_x.py::test_case FAILED",
            "AssertionError: expected 1 got 0",
            "ImportError in core/ci_remediation.py",
        ]
    )

    parsed = auto.parse_failure_output(output)

    assert parsed.failure_summary.startswith("tests/unit/core/test_x.py")
    assert parsed.root_cause_hint.startswith("tests/unit/core/test_x.py")
    assert "tests/unit/core/test_x.py" in parsed.suspected_targets
    assert any("Assertion" in hint for hint in parsed.diagnostic_hints)


def test_build_remediation_payload_contains_loop_metadata() -> None:
    parsed = auto.FailureParse(
        failure_summary="AssertionError: boom",
        root_cause_hint="AssertionError: boom",
        suspected_targets=["tests/unit/x.py", "core/y.py"],
        diagnostic_hints=["h1"],
    )

    payload = auto.build_remediation_payload(
        parsed,
        attempt=2,
        max_attempts=4,
        command="./run_tests.sh",
        output_excerpt="AssertionError: boom",
    )

    assert payload["attempt"] == 2
    assert payload["max_attempts"] == 4
    assert payload["test_command"] == "./run_tests.sh"
    assert payload["remediation_loop"]["status"] in {"planned", "needs_diagnosis"}
    assert payload["root_cause_summary"]


def test_run_self_heal_loop_succeeds_after_fixer(tmp_path: Path) -> None:
    marker = tmp_path / "fixed.txt"
    test_command = (
        "python -c \"from pathlib import Path; "
        f"p=Path(r'{marker}'); "
        "import sys; "
        "sys.exit(0 if p.exists() else 1)\""
    )
    fixer_command = f"python -c \"from pathlib import Path; Path(r'{marker}').write_text('ok')\""

    code = auto.run_self_heal_loop(
        test_command=test_command,
        fixer_command_template=fixer_command,
        max_attempts=3,
        workdir=tmp_path,
        timeout=10,
        payload_dir=tmp_path / "artifacts",
    )

    assert code == 0
    assert marker.exists()
    assert (tmp_path / "artifacts" / "remediation_attempt_1.json").exists()


def test_main_rejects_invalid_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "auto_remediate_tests.py",
            "--max-attempts",
            "0",
        ],
    )

    with pytest.raises(SystemExit, match="--max-attempts en az 1"):
        auto.main()
