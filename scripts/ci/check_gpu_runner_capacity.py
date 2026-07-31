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

REQUIRED_LABELS = frozenset({"self-hosted", "linux", "gpu"})


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
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
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
    minimum = max(2, args.minimum_online)
    if len(eligible) < minimum:
        print(
            f"GPU runner kapasitesi yetersiz: online={len(eligible)}, gerekli={minimum}, "
            f"runnerlar={eligible}. docs/runbooks/gpu-runner-continuity.md",
            file=sys.stderr,
        )
        return 1
    print(f"GPU runner kapasitesi hazır: online={len(eligible)}, runnerlar={eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
