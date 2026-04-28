from __future__ import annotations

from pathlib import Path

import pytest

from scripts import auto_remediate_tests as mod


def test_parse_failure_signal_extracts_summary_and_targets():
    result = mod.CommandResult(
        command="pytest -q",
        returncode=1,
        stdout="AssertionError: boom in tests/unit/x.py\n",
        stderr="ImportError: fail at core/ci_remediation.py\n",
    )

    signal = mod.parse_failure_signal(result)

    assert "ImportError" in signal.summary
    assert signal.root_cause == "AssertionError: boom in tests/unit/x.py"
    assert "tests/unit/x.py" in signal.suspected_targets
    assert "core/ci_remediation.py" in signal.suspected_targets


def test_build_remediation_prompt_contains_loop_metadata():
    signal = mod.FailureSignal(
        summary="pytest failed",
        root_cause="AssertionError",
        suspected_targets=["tests/unit/a.py"],
        raw_excerpt="trace...",
    )

    payload = mod.build_remediation_prompt(
        failure=signal,
        test_command="./run_tests.sh",
        attempt=2,
        max_attempts=4,
    )

    assert '"attempt": 2' in payload
    assert '"max_attempts": 4' in payload
    assert '"tests/unit/a.py"' in payload
    assert '"test_command": "./run_tests.sh"' in payload


def test_remediate_loop_succeeds_after_first_fix(monkeypatch, tmp_path: Path):
    calls = {"run": [], "fix": []}

    test_fail = mod.CommandResult("./run_tests.sh", 1, "AssertionError at tests/unit/a.py", "")
    test_ok = mod.CommandResult("./run_tests.sh", 0, "ok", "")
    fix_ok = mod.CommandResult("fix", 0, "patched", "")

    def fake_run_command(command: str, cwd: Path):
        calls["run"].append((command, cwd))
        if len(calls["run"]) == 1:
            return test_fail
        return test_ok

    def fake_run_fixer(*, fixer_command_template: str, prompt: str, cwd: Path):
        calls["fix"].append((fixer_command_template, prompt, cwd))
        return fix_ok

    monkeypatch.setattr(mod, "run_command", fake_run_command)
    monkeypatch.setattr(mod, "run_fixer", fake_run_fixer)

    exit_code = mod.remediate_loop(
        test_command="./run_tests.sh",
        fixer_command_template="python cli.py --command-file {prompt_file}",
        max_attempts=3,
        cwd=tmp_path,
    )

    assert exit_code == 0
    assert len(calls["run"]) == 2
    assert len(calls["fix"]) == 1


def test_remediate_loop_stops_after_max_attempts(monkeypatch, tmp_path: Path):
    test_fail = mod.CommandResult("./run_tests.sh", 2, "TypeError in agent/x.py", "")
    fix_fail = mod.CommandResult("fix", 1, "", "error")

    monkeypatch.setattr(mod, "run_command", lambda *_args, **_kwargs: test_fail)
    monkeypatch.setattr(mod, "run_fixer", lambda **_kwargs: fix_fail)

    exit_code = mod.remediate_loop(
        test_command="./run_tests.sh",
        fixer_command_template="python fixer.py --input {prompt_file}",
        max_attempts=2,
        cwd=tmp_path,
    )

    assert exit_code == 2


@pytest.mark.parametrize("attempts", [0, -1])
def test_remediate_loop_rejects_invalid_attempt_count(attempts: int, tmp_path: Path):
    with pytest.raises(ValueError, match="en az 1"):
        mod.remediate_loop(
            test_command="./run_tests.sh",
            fixer_command_template="echo {prompt_file}",
            max_attempts=attempts,
            cwd=tmp_path,
        )
