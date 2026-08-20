"""Tests for the self-hosted benchmark runner capacity watchdog."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import check_benchmark_runner_capacity as capacity


def _runner(name: str, *, status: str = "online", labels: tuple[str, ...] = ()) -> dict:
    return {
        "name": name,
        "status": status,
        "busy": False,
        "labels": [{"name": label} for label in labels],
    }


def test_watchdog_workflow_uses_hosted_control_plane_and_checks_capacity() -> None:
    workflow = Path(".github/workflows/benchmark-runner-capacity-watchdog.yml").read_text(
        encoding="utf-8"
    )

    assert "runs-on: ubuntu-latest" in workflow
    assert "uses: actions/checkout@v7" in workflow
    assert "BENCHMARK_RUNNER_MONITOR_TOKEN" in workflow
    assert "check_benchmark_runner_capacity.py" in workflow
    assert "--minimum-online 2" in workflow
    assert "--minimum-idle 1" in workflow
    assert "types: [requested]" in workflow
    assert "actions/github-script@v8" in workflow


def test_watchdog_token_is_documented_in_advanced_env_template() -> None:
    env_template = Path(".env.advanced.example").read_text(encoding="utf-8")

    assert "BENCHMARK_RUNNER_MONITOR_TOKEN=" in env_template
    assert "Runner watchdog token'ları SIDAR_KEYS_FILE'da tutulmalıdır." in env_template


def test_eligible_online_runners_requires_every_label_and_online_state() -> None:
    payload = {
        "runners": [
            _runner("stable", labels=("self-hosted", "Linux", "Benchmark")),
            _runner(
                "offline",
                status="offline",
                labels=("self-hosted", "linux", "benchmark"),
            ),
            _runner("unlabelled", labels=("self-hosted", "linux")),
        ]
    }

    assert capacity.eligible_online_runners(payload) == ["stable"]
    assert capacity.eligible_idle_runners(payload) == ["stable"]


def test_main_fails_closed_without_redundancy_and_passes_with_two(tmp_path, capsys) -> None:
    fixture = tmp_path / "runners.json"
    labels = ("self-hosted", "linux", "benchmark")
    fixture.write_text(json.dumps({"runners": []}), encoding="utf-8")
    assert capacity.main(["--fixture", str(fixture)]) == 1
    assert "capacity is insufficient" in capsys.readouterr().err

    fixture.write_text(json.dumps({"runners": [_runner("stable", labels=labels)]}))
    assert capacity.main(["--fixture", str(fixture)]) == 1
    assert "required=2" in capsys.readouterr().err

    fixture.write_text(
        json.dumps(
            {
                "runners": [
                    _runner("primary", labels=labels),
                    _runner("standby", labels=labels),
                ]
            }
        ),
        encoding="utf-8",
    )
    assert capacity.main(["--fixture", str(fixture)]) == 0
    assert "primary" in capsys.readouterr().out


def test_main_fails_when_redundant_runners_are_all_busy(tmp_path, capsys) -> None:
    fixture = tmp_path / "runners.json"
    labels = ("self-hosted", "linux", "benchmark")
    primary = _runner("primary", labels=labels)
    standby = _runner("standby", labels=labels)
    primary["busy"] = True
    standby["busy"] = True
    fixture.write_text(json.dumps({"runners": [primary, standby]}), encoding="utf-8")

    assert capacity.main(["--fixture", str(fixture), "--minimum-idle", "1"]) == 1
    assert "idle capacity is insufficient" in capsys.readouterr().err


def test_main_requires_authenticated_api_inputs(capsys) -> None:
    assert capacity.main(["--repo", "", "--token", ""]) == 2
    assert "BENCHMARK_RUNNER_MONITOR_TOKEN" in capsys.readouterr().err


def test_runbook_keeps_compare_and_baseline_evidence_fail_closed() -> None:
    runbook = Path("docs/runbooks/benchmark-runner-continuity.md").read_text(encoding="utf-8")

    assert "[self-hosted, linux, benchmark]" in runbook
    assert "GitHub-hosted runner'a otomatik\nfallback yapılmaz" in runbook
    assert "Watchdog yalnız kapasite erken uyarısıdır" in runbook
    assert "compare kapısı gevşetilmemeli" in runbook
    assert "Host başına baseline hazırlığı" in runbook
    assert "--minimum-online 2" in runbook
