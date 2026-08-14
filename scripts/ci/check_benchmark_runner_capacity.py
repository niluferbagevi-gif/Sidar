"""Validate that GitHub exposes an online self-hosted benchmark runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

REQUIRED_LABELS = frozenset({"self-hosted", "linux", "benchmark"})


def eligible_online_runners(payload: dict[str, Any]) -> list[str]:
    """Return online runner names carrying every stable benchmark label."""
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
            "User-Agent": "sidar-benchmark-runner-watchdog",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310 -- fixed GitHub API origin
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Benchmark runner API response is not a JSON object.")
            return cast(dict[str, Any], payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Benchmark runner inventory could not be fetched: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Check an API or fixture payload against the benchmark-runner policy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.getenv("BENCHMARK_RUNNER_MONITOR_TOKEN", ""))
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--minimum-online", type=int, default=1)
    args = parser.parse_args(argv)

    if args.fixture:
        payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    elif not args.repo or not args.token:
        print(
            "--repo/GITHUB_REPOSITORY and BENCHMARK_RUNNER_MONITOR_TOKEN are required.",
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
    minimum = max(1, args.minimum_online)
    if len(eligible) < minimum:
        print(
            f"Benchmark runner capacity is insufficient: online={len(eligible)}, "
            f"required={minimum}, runners={eligible}. "
            "docs/runbooks/benchmark-runner-continuity.md",
            file=sys.stderr,
        )
        return 1
    print(f"Benchmark runner capacity is ready: online={len(eligible)}, runners={eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
