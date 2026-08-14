"""Tests for the redundant self-hosted GPU runner watchdog."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import check_gpu_runner_capacity as capacity


def test_watchdog_workflow_guards_gate_variable_and_runner_capacity() -> None:
    """The hourly control plane must monitor both halves of GPU readiness."""
    workflow = Path(".github/workflows/gpu-runner-capacity-watchdog.yml").read_text(
        encoding="utf-8"
    )

    assert "GPU_BENCH_GATE_ENABLED: ${{ vars.ENABLE_GPU_BENCH_GATE }}" in workflow
    assert '[[ "${GPU_BENCH_GATE_ENABLED}" != "true" ]]' in workflow
    assert "--minimum-online 2" in workflow


def test_runbook_provisions_and_verifies_repository_control_plane() -> None:
    """Operators must configure GitHub state explicitly instead of weakening the gate."""
    runbook = Path("docs/runbooks/gpu-runner-continuity.md").read_text(encoding="utf-8")

    assert "gh variable set ENABLE_GPU_BENCH_GATE --body true" in runbook
    assert "gh variable get ENABLE_GPU_BENCH_GATE" in runbook
    assert "gh workflow run gpu-runner-capacity-watchdog.yml" in runbook
    assert "GPU_RUNNER_MONITOR_TOKEN" in runbook
    assert "`self-hosted`, `linux`, `x64`, `gpu`, `cuda`" in runbook
    assert "yerel GPU sonucu bu kontrolü bypass edemez" in runbook


def _runner(name: str, *, status: str = "online", labels: tuple[str, ...] = ()) -> dict:
    return {
        "name": name,
        "status": status,
        "labels": [{"name": label} for label in labels],
    }


def test_eligible_online_runners_requires_all_labels_and_online_state() -> None:
    payload = {
        "runners": [
            _runner("primary", labels=("self-hosted", "Linux", "X64", "GPU", "CUDA")),
            _runner(
                "offline-standby",
                status="offline",
                labels=("self-hosted", "linux", "x64", "gpu", "cuda"),
            ),
            _runner("cpu", labels=("self-hosted", "linux")),
        ]
    }
    assert capacity.eligible_online_runners(payload) == ["primary"]


def test_main_fails_closed_with_one_runner_and_passes_with_two(tmp_path, capsys) -> None:
    fixture = tmp_path / "runners.json"
    labels = ("self-hosted", "linux", "x64", "gpu", "cuda")
    fixture.write_text(json.dumps({"runners": [_runner("primary", labels=labels)]}))
    assert capacity.main(["--fixture", str(fixture)]) == 1
    assert "kapasitesi yetersiz" in capsys.readouterr().err

    fixture.write_text(
        json.dumps(
            {"runners": [_runner("primary", labels=labels), _runner("standby", labels=labels)]}
        )
    )
    assert capacity.main(["--fixture", str(fixture)]) == 0
    assert "primary" in capsys.readouterr().out


def test_main_requires_authenticated_api_inputs(capsys) -> None:
    assert capacity.main(["--repo", "", "--token", ""]) == 2
    assert "GPU_RUNNER_MONITOR_TOKEN" in capsys.readouterr().err
