from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_autonomous_loop_config(
    *,
    profile: str,
    operation_profile: str = "coverage-campaign",
    extra_env: dict[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    env.update(
        {
            "AUTONOMOUS_LOOP_COVERAGE_PROFILE": profile,
            "AUTONOMOUS_LOOP_OPERATION_PROFILE": operation_profile,
            "AUTONOMOUS_LOOP_PRINT_CONFIG": "1",
        }
    )
    if extra_env:
        env.update(extra_env)
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


def test_autonomous_loop_disables_repeated_static_analysis_by_default() -> None:
    output = _run_autonomous_loop_config(profile="short")

    assert "Otonom test tekrarlarında RUN_STATIC_ANALYSIS=0" in output


def test_autonomous_loop_rejects_invalid_static_analysis_override() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS": "sometimes"},
    )

    assert "AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS 0 veya 1 olmalı" in output
    assert "Otonom test tekrarlarında RUN_STATIC_ANALYSIS=0" in output


def test_autonomous_loop_prints_upload_and_auto_heal_controls() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={
            "AUTONOMOUS_LOOP_SKIP_UPLOAD": "1",
            "AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE": "no",
            "AUTONOMOUS_LOOP_TEST_FAILURE_LOG": "artifacts/test-loop.log",
        },
    )

    assert "Upload adımı: AUTONOMOUS_LOOP_SKIP_UPLOAD=1" in output
    assert "Auto-heal adımı: AUTONOMOUS_LOOP_AUTO_HEAL_ENABLED=1" in output
    assert "HITL=no" in output
    assert "log=artifacts/test-loop.log" in output


def test_autonomous_loop_accepts_interactive_hitl_prompt_mode() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE": "prompt"},
    )

    assert "HITL=prompt" in output
    assert "AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE anlaşılamadı" not in output


def test_autonomous_loop_rejects_invalid_auto_heal_hitl_value() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE": "maybe"},
    )

    assert "AUTONOMOUS_LOOP_AUTO_HEAL_HITL_APPROVE anlaşılamadı" in output
    assert "HITL=no" in output


def test_autonomous_loop_defaults_to_hybrid_remediation_mode() -> None:
    output = _run_autonomous_loop_config(profile="short")

    assert "Otonom remediation modu: AUTONOMOUS_LOOP_REMEDIATION_MODE=hybrid" in output
    assert "Hibrit remediation modu:" in output
    assert "RUN_STATIC_ANALYSIS=0 AUTO_HEAL_ON_FAILURE=0" in output


def test_autonomous_loop_hybrid_forces_static_analysis_off() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS": "1"},
    )

    assert "tekrarlı mypy/self-heal blokajını önlemek" in output
    assert "Otonom test tekrarlarında RUN_STATIC_ANALYSIS=0" in output


def test_autonomous_loop_full_remediation_allows_static_analysis_override() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={
            "AUTONOMOUS_LOOP_REMEDIATION_MODE": "full",
            "AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS": "1",
        },
    )

    assert "Otonom remediation modu: AUTONOMOUS_LOOP_REMEDIATION_MODE=full" in output
    assert "Full remediation modu: otonom test tekrarlarında RUN_STATIC_ANALYSIS=1" in output


def test_autonomous_loop_rejects_invalid_remediation_mode() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_REMEDIATION_MODE": "mypy-loop"},
    )

    assert "AUTONOMOUS_LOOP_REMEDIATION_MODE hybrid, tests-only veya full olmalı" in output
    assert "Otonom remediation modu: AUTONOMOUS_LOOP_REMEDIATION_MODE=hybrid" in output
