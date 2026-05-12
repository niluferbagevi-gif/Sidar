from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_autonomous_loop_config(*, profile: str, operation_profile: str = "coverage-campaign") -> str:
    env = os.environ.copy()
    env.update(
        {
            "AUTONOMOUS_LOOP_COVERAGE_PROFILE": profile,
            "AUTONOMOUS_LOOP_OPERATION_PROFILE": operation_profile,
            "AUTONOMOUS_LOOP_PRINT_CONFIG": "1",
        }
    )
    completed = subprocess.run(
        ["bash", "autonomous_loop.sh"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def test_coverage_campaign_short_profile_targets_99_8_percent() -> None:
    output = _run_autonomous_loop_config(profile="short")

    assert "Coverage operasyon profili: coverage-campaign." in output
    assert "AUTONOMOUS_LOOP_COVERAGE_PROFILE=short => %99.8" in output
    assert "AUTONOMOUS_LOOP_PRINT_CONFIG=1" in output


def test_coverage_campaign_full_profile_targets_100_percent() -> None:
    output = _run_autonomous_loop_config(profile="full")

    assert "Coverage operasyon profili: coverage-campaign." in output
    assert "AUTONOMOUS_LOOP_COVERAGE_PROFILE=full => %100" in output
    assert "AUTONOMOUS_LOOP_PRINT_CONFIG=1" in output
