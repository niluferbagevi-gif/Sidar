"""Tests for the release-blocking GPU evidence policy helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/ci/check_gpu_evidence.sh")


def _run(*, enabled: str | None, result: str = "success") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("GPU_GATE_ENABLED", None)
    if enabled is not None:
        env["GPU_GATE_ENABLED"] = enabled
    env["GPU_GATE_RESULT"] = result
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
