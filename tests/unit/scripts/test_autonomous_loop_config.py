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


def test_autonomous_loop_hybrid_mode_ignores_static_analysis_override() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={"AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS": "1"},
    )

    assert "AUTONOMOUS_LOOP_REMEDIATION_MODE=hybrid" in output
    assert "Hibrit otonom döngüde tekrar eden mypy/statik analiz kapalıdır" in output
    assert "Otonom test tekrarlarında RUN_STATIC_ANALYSIS=0" in output


def test_autonomous_loop_full_static_mode_allows_static_analysis_override() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={
            "AUTONOMOUS_LOOP_REMEDIATION_MODE": "full-static",
            "AUTONOMOUS_LOOP_RUN_STATIC_ANALYSIS": "1",
        },
    )

    assert "AUTONOMOUS_LOOP_REMEDIATION_MODE=full-static" in output
    assert "Otonom test tekrarlarında RUN_STATIC_ANALYSIS=1" in output
    assert "Hibrit otonom döngüde" not in output


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


def test_autonomous_loop_defaults_exclude_entrypoints_and_uses_parallel_mutmut() -> None:
    output = _run_autonomous_loop_config(
        profile="short",
        extra_env={
            "AUTONOMOUS_LOOP_MUTATION_ENABLED": "true",
            "AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN": "8",
        },
    )

    assert (
        "CoverageAgent exclude listesi: "
        "AUTONOMOUS_LOOP_EXCLUDE_FILES='web_server.py,main.py,gui_launcher.py,cli.py'"
        in output
    )
    assert (
        "Mutasyon kalite kapısı: AUTONOMOUS_LOOP_MUTATION_ENABLED=true; max_children=8"
        in output
    )
    assert "uv run --with mutmut mutmut run --max-children 8" in output

