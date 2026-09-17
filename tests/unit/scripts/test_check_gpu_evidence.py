"""Tests for the release-blocking GPU evidence policy helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/ci/check_gpu_evidence.sh")


def _run(
    *,
    enabled: str | None,
    result: str = "success",
    step_summary_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("GPU_GATE_ENABLED", None)
    if enabled is not None:
        env["GPU_GATE_ENABLED"] = enabled
    env["GPU_GATE_RESULT"] = result
    if step_summary_path is not None:
        env["GITHUB_STEP_SUMMARY"] = str(step_summary_path)
    else:
        env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_gpu_evidence_rejects_missing_or_non_boolean_repository_variable() -> None:
    for value, rendered in ((None, "<empty>"), ("1", "1"), ("TRUE", "TRUE")):
        completed = _run(enabled=value)

        assert completed.returncode == 1
        assert "must be an explicit boolean (true or false)" in completed.stderr
        assert f"current value='{rendered}'" in completed.stderr


def test_gpu_evidence_false_is_valid_boolean_but_not_release_ready() -> None:
    """Explicit false is a valid boolean, but this repo's policy never exempts it.

    A code review flagged the previous wording here ("...is valid for
    non-release CI, but this repository requires...") as internally
    contradictory: it read as if some non-release context in *this* CI
    accepted `false`, when the code (and docs/CI_REQUIRED_CHECKS.md's "no
    silent checklist-only bypass" policy) rejects it unconditionally, with
    no release/non-release distinction anywhere in this workflow. The
    message now says so explicitly instead of implying an exemption exists.
    """
    completed = _run(enabled="false")

    assert completed.returncode == 1
    assert "syntactically valid boolean" in completed.stderr
    assert "no non-release exemption" in completed.stderr
    assert "requires GPU TTFT/latency evidence unconditionally" in completed.stderr


def test_gpu_evidence_requires_successful_hardware_job() -> None:
    completed = _run(enabled="true", result="failure")

    assert completed.returncode == 1
    assert "result=failure; expected success" in completed.stderr


def test_gpu_evidence_accepts_enabled_successful_hardware_job() -> None:
    completed = _run(enabled="true")

    assert completed.returncode == 0
    assert "evidence is present and passing" in completed.stdout


def test_gpu_evidence_without_step_summary_env_does_not_fail(tmp_path: Path) -> None:
    """No GITHUB_STEP_SUMMARY (e.g. a local/non-Actions run) must not error."""
    completed = _run(enabled=None, step_summary_path=None)

    assert completed.returncode == 1
    assert "must be an explicit boolean" in completed.stderr


def test_gpu_evidence_missing_variable_writes_actionable_step_summary(tmp_path: Path) -> None:
    """The Summary tab must call out this is a repo-admin action, not a code fix.

    A code review noted the raw ::error:: annotation is easy to miss (collapsed
    log, truncated PR checks list); the fix must also land in the job Summary
    tab where a reviewer looks first.
    """
    summary_path = tmp_path / "summary.md"
    completed = _run(enabled=None, step_summary_path=summary_path)

    assert completed.returncode == 1
    summary = summary_path.read_text(encoding="utf-8")
    assert "repository not configured" in summary
    assert "repository admin action" in summary
    assert "ENABLE_GPU_BENCH_GATE" in summary
    assert "docs/runbooks/gpu-runner-continuity.md" in summary


def test_gpu_evidence_false_writes_actionable_step_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.md"
    completed = _run(enabled="false", step_summary_path=summary_path)

    assert completed.returncode == 1
    summary = summary_path.read_text(encoding="utf-8")
    assert "evidence disabled" in summary
    assert "repository admin action" in summary
    assert "no non-release exemption" in summary or "no" in summary


def test_gpu_evidence_hardware_failure_step_summary_does_not_blame_repo_config(
    tmp_path: Path,
) -> None:
    """A real hardware/latency failure must not be framed as a config gap."""
    summary_path = tmp_path / "summary.md"
    completed = _run(enabled="true", result="failure", step_summary_path=summary_path)

    assert completed.returncode == 1
    summary = summary_path.read_text(encoding="utf-8")
    assert "benchmark job did not pass" in summary
    assert "not a" in summary
    assert "repository admin action" not in summary


def test_gpu_evidence_success_writes_step_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.md"
    completed = _run(enabled="true", step_summary_path=summary_path)

    assert completed.returncode == 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "passing" in summary
