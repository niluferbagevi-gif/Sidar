"""Validate that GitHub exposes redundant online GPU self-hosted runners."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

REQUIRED_LABELS = frozenset({"self-hosted", "linux", "x64", "gpu", "cuda"})


def eligible_online_runners(payload: dict[str, Any]) -> list[str]:
    """Return names of online runners carrying every required GPU label."""
    eligible: list[str] = []
    for runner in payload.get("runners", []):
        if not isinstance(runner, dict) or runner.get("status") != "online":
            continue
        labels = {
            str(item.get("name", "")).strip().lower()
            for item in runner.get("labels", [])
            if isinstance(item, dict)
        }
        if REQUIRED_LABELS <= labels:
            eligible.append(str(runner.get("name", "unnamed-runner")))
    return sorted(eligible)


def eligible_idle_runners(payload: dict[str, Any]) -> list[str]:
    """Return eligible online runners that are ready to accept a queued job."""
    eligible_names = set(eligible_online_runners(payload))
    return sorted(
        str(runner.get("name", "unnamed-runner"))
        for runner in payload.get("runners", [])
        if isinstance(runner, dict)
        and str(runner.get("name", "unnamed-runner")) in eligible_names
        and runner.get("busy") is False
    )


def runner_inventory_diagnostics(payload: dict[str, Any]) -> list[str]:
    """Summarize runner state and missing labels without exposing credentials."""
    diagnostics: list[str] = []
    for runner in payload.get("runners", []):
        if not isinstance(runner, dict):
            continue
        labels = {
            str(item.get("name", "")).strip().lower()
            for item in runner.get("labels", [])
            if isinstance(item, dict)
        }
        missing = sorted(REQUIRED_LABELS - labels)
        diagnostics.append(
            f"{runner.get('name', 'unnamed-runner')}:status={runner.get('status', 'unknown')},"
            f"busy={runner.get('busy', 'unknown')},missing_labels={missing}"
        )
    return sorted(diagnostics)


def fetch_runner_payload(repository: str, token: str) -> dict[str, Any]:
    """Fetch repository runner inventory through GitHub's authenticated API."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runners?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sidar-gpu-runner-watchdog",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310  # sabit https://api.github.com hedefi, kullanıcı girdisi değil.
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("GPU runner API cevabı JSON object değil.")
            return cast(dict[str, Any], payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GPU runner envanteri alınamadı: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Check an API or fixture payload against the redundant-runner policy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.getenv("GPU_RUNNER_MONITOR_TOKEN", ""))
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--minimum-online", type=int, default=2)
    parser.add_argument("--minimum-idle", type=int, default=0)
    args = parser.parse_args(argv)

    if args.fixture:
        payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    elif not args.repo or not args.token:
        print(
            "GPU runner watchdog için --repo/GITHUB_REPOSITORY ve "
            "--token/GPU_RUNNER_MONITOR_TOKEN gerekli.",
            file=sys.stderr,
        )
        return 2
    else:
        try:
            payload = fetch_runner_payload(args.repo, args.token)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    eligible = eligible_online_runners(payload)
    idle = eligible_idle_runners(payload)
    minimum = max(2, args.minimum_online)
    if len(eligible) < minimum:
        print(
            f"GPU runner kapasitesi yetersiz: online={len(eligible)}, gerekli={minimum}, "
            f"runnerlar={eligible}, envanter={runner_inventory_diagnostics(payload)}. "
            "docs/runbooks/gpu-runner-continuity.md",
            file=sys.stderr,
        )
        return 1
    minimum_idle = max(0, args.minimum_idle)
    if len(idle) < minimum_idle:
        print(
            f"GPU runner kuyruğu için idle kapasite yok: idle={len(idle)}, "
            f"gerekli={minimum_idle}, online_runnerlar={eligible}, "
            f"envanter={runner_inventory_diagnostics(payload)}. "
            "docs/runbooks/gpu-runner-continuity.md",
            file=sys.stderr,
        )
        return 1
    print(
        f"GPU runner kapasitesi hazır: online={len(eligible)}, idle={len(idle)}, "
        f"runnerlar={eligible}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
