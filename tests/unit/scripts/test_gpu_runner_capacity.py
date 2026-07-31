"""Tests for the redundant self-hosted GPU runner watchdog."""

from __future__ import annotations

import json

from scripts.ci import check_gpu_runner_capacity as capacity


def _runner(name: str, *, status: str = "online", labels: tuple[str, ...] = ()) -> dict:
    return {
        "name": name,
        "status": status,
        "labels": [{"name": label} for label in labels],
    }


def test_eligible_online_runners_requires_all_labels_and_online_state() -> None:
    payload = {
        "runners": [
            _runner("primary", labels=("self-hosted", "Linux", "GPU")),
            _runner("offline-standby", status="offline", labels=("self-hosted", "linux", "gpu")),
            _runner("cpu", labels=("self-hosted", "linux")),
        ]
    }
    assert capacity.eligible_online_runners(payload) == ["primary"]


def test_main_fails_closed_with_one_runner_and_passes_with_two(tmp_path, capsys) -> None:
    fixture = tmp_path / "runners.json"
    labels = ("self-hosted", "linux", "gpu")
    fixture.write_text(json.dumps({"runners": [_runner("primary", labels=labels)]}))
    assert capacity.main(["--fixture", str(fixture)]) == 1
    assert "kapasitesi yetersiz" in capsys.readouterr().err

    fixture.write_text(
        json.dumps({"runners": [_runner("primary", labels=labels), _runner("standby", labels=labels)]})
    )
    assert capacity.main(["--fixture", str(fixture)]) == 0
    assert "primary" in capsys.readouterr().out


def test_main_requires_authenticated_api_inputs(capsys) -> None:
    assert capacity.main(["--repo", "", "--token", ""]) == 2
    assert "GPU_RUNNER_MONITOR_TOKEN" in capsys.readouterr().err
