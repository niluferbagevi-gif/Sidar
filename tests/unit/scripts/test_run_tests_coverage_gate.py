from __future__ import annotations

from pathlib import Path

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    return RUN_TESTS.read_text(encoding="utf-8")


def test_run_tests_defers_coverage_fail_under_until_combined_report() -> None:
    script = _script()

    assert "--cov-fail-under=0" in script
    assert 'coverage report --fail-under="${COVERAGE_FAIL_UNDER}"' in script
    assert "final coverage report --fail-under" in script


def test_run_tests_enforces_combined_gate_before_ratchet() -> None:
    script = _script()

    gate_call = script.index("  enforce_combined_coverage_gate\n")
    ratchet_function = script.index("update_progressive_coverage_gate()")
    ratchet_call = script.index("  update_progressive_coverage_gate", ratchet_function)

    assert gate_call < ratchet_function < ratchet_call


def test_run_tests_regenerates_machine_readable_coverage_before_gate() -> None:
    script = _script()
    gate_function = script[script.index("enforce_combined_coverage_gate()") :]

    assert "uv run python -m coverage html -d htmlcov" in gate_function
    assert "uv run python -m coverage xml -o coverage.xml" in gate_function
    assert "uv run python -m coverage json -o coverage.json" in gate_function
