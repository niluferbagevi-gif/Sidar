"""Audit GitHub branch-protection required checks against CI workflow jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

DEFAULT_RELEASE_JOB_IDS = (
    "test",
    "installer-smoke",
    "production-profile-dry-run",
    "pg-stress",
)


class RequiredCheckAuditError(RuntimeError):
    """Raised when the required-check audit cannot pass."""


def _repo_from_git_remote() -> str:
    """Resolve owner/repo from the local git remote when GITHUB_REPOSITORY is absent."""
    try:
        # Fixed git command without user shell or user-controlled executable.
        remote = subprocess.check_output(  # nosec B603 B607
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@github.com:"):
        return remote.removeprefix("git@github.com:")
    marker = "github.com/"
    if marker in remote:
        return remote.rsplit(marker, 1)[1]
    return ""


def _load_expected_check_names(workflow_path: Path, job_ids: tuple[str, ...]) -> list[str]:
    """Return GitHub check-run context names for selected workflow job ids."""
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise RequiredCheckAuditError(f"Workflow YAML is not a mapping: {workflow_path}")
    workflow_name = str(workflow.get("name") or workflow_path.stem)
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        raise RequiredCheckAuditError(f"Workflow has no jobs mapping: {workflow_path}")

    expected: list[str] = []
    missing_job_ids: list[str] = []
    for job_id in job_ids:
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            missing_job_ids.append(job_id)
            continue
        expected.append(f"{workflow_name} / {job.get('name') or job_id}")
    if missing_job_ids:
        raise RequiredCheckAuditError(
            "Release-critical job id(s) missing from workflow: " + ", ".join(missing_job_ids)
        )
    return expected


def _extract_required_contexts(payload: dict[str, Any]) -> set[str]:
    """Normalize required status-check contexts from GitHub branch protection JSON."""
    contexts: set[str] = set()
    raw_contexts = payload.get("contexts", [])
    if isinstance(raw_contexts, list):
        contexts.update(str(item) for item in raw_contexts if item)
    raw_checks = payload.get("checks", [])
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if isinstance(item, dict) and item.get("context"):
                contexts.add(str(item["context"]))
    return contexts


def _fetch_required_contexts(
    *, api_url: str, repo: str, branch: str, token: str | None, timeout: float
) -> set[str]:
    """Fetch branch-protection required checks from the GitHub REST API."""
    url = f"{api_url.rstrip('/')}/repos/{repo}/branches/{branch}/protection/required_status_checks"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sidar-required-check-audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        # URL is GitHub API or an explicit operator override.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            raw_payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RequiredCheckAuditError(
            f"GitHub required-check API returned HTTP {exc.code} for {repo}@{branch}: {exc.reason}"
        ) from exc
    except URLError as exc:
        raise RequiredCheckAuditError(
            f"GitHub required-check API could not be reached for {repo}@{branch}: {exc.reason}"
        ) from exc
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise RequiredCheckAuditError("GitHub required-check API response was not an object")
    return _extract_required_contexts(payload)


def audit_required_checks(
    *,
    workflow_path: Path,
    job_ids: tuple[str, ...],
    required_contexts: set[str],
) -> tuple[list[str], list[str]]:
    """Compare expected workflow check names with branch-protection contexts."""
    expected = _load_expected_check_names(workflow_path, job_ids)
    missing = [name for name in expected if name not in required_contexts]
    return expected, missing


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify GitHub branch protection requires the release-critical checks "
            "declared in .github/workflows/ci.yml."
        )
    )
    parser.add_argument("--workflow", default=".github/workflows/ci.yml", type=Path)
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY") or _repo_from_git_remote())
    parser.add_argument("--branch", default=os.getenv("SIDAR_REQUIRED_CHECK_BRANCH", "main"))
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--timeout", default=20.0, type=float)
    parser.add_argument(
        "--job-id",
        action="append",
        dest="job_ids",
        help="Release-critical CI job id that must be required. Repeatable.",
    )
    parser.add_argument(
        "--required-context",
        action="append",
        dest="required_contexts",
        help="Offline/test mode: provide a required context instead of calling GitHub.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    job_ids = tuple(args.job_ids or DEFAULT_RELEASE_JOB_IDS)
    try:
        if args.required_contexts is not None:
            required_contexts = set(args.required_contexts)
        else:
            if not args.repo:
                raise RequiredCheckAuditError(
                    "Repository is unknown. Set GITHUB_REPOSITORY or pass --repo owner/repo."
                )
            required_contexts = _fetch_required_contexts(
                api_url=args.api_url,
                repo=args.repo,
                branch=args.branch,
                token=args.token,
                timeout=args.timeout,
            )
        expected, missing = audit_required_checks(
            workflow_path=args.workflow, job_ids=job_ids, required_contexts=required_contexts
        )
    except RequiredCheckAuditError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    print("Expected release-critical required checks:")
    for context in expected:
        marker = "OK" if context not in missing else "MISSING"
        print(f"- [{marker}] {context}")
    if missing:
        print(
            "::error::Branch protection is missing required release gate check(s): "
            + "; ".join(missing),
            file=sys.stderr,
        )
        return 1
    print("Branch protection required-check audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
