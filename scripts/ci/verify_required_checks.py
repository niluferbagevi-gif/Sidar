"""Audit GitHub branch-protection required checks against CI workflow jobs."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import yaml

DEFAULT_RELEASE_JOB_IDS = (
    "test",
    "installer-smoke",
    "production-profile-dry-run",
    "gpu-inference-policy-gate",
    "production-readiness",
    "pg-stress",
)
BRANCH_PROTECTION_AUDIT_CONTEXT = "Required release checks audit"
_GIT_REMOTE_COMMAND = ("git", "remote", "get-url", "origin")


class RequiredCheckAuditError(RuntimeError):
    """Raised when the required-check audit cannot pass."""


def _repo_from_git_remote() -> str:
    """Resolve owner/repo from the local git remote when GITHUB_REPOSITORY is absent."""
    if any("\x00" in part for part in _GIT_REMOTE_COMMAND):
        return ""
    git_binary = shutil.which("git")
    if not git_binary or not Path(git_binary).is_absolute():
        return ""
    command = [git_binary, *_GIT_REMOTE_COMMAND[1:]]
    try:
        remote = subprocess.check_output(  # nosec B603  # absolute git; exact argv allowlist
            command,
            text=True,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=10,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
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
    """Return GitHub check-run context names for selected workflow job ids.

    GitHub Actions reports a check run's context as the job's own `name:` (or its
    id, if unnamed) with no workflow-name prefix, unless the job name is
    ambiguous across workflows — which none of these release-critical jobs are.
    Confirmed against this repo's live branch-protection UI and Jobs API output
    (e.g. the audit job itself reports as "Required release checks audit", not
    "Branch protection audit / Required release checks audit").
    """
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise RequiredCheckAuditError(f"Workflow YAML is not a mapping: {workflow_path}")
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
        expected.append(str(job.get("name") or job_id))
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


def _extract_protection_required_contexts(payload: dict[str, Any]) -> set[str]:
    """Return required contexts from a complete branch-protection response."""
    required_status_checks = payload.get("required_status_checks")
    if not isinstance(required_status_checks, dict):
        return set()
    return _extract_required_contexts(required_status_checks)


def audit_merge_safety(payload: dict[str, Any]) -> list[str]:
    """Validate non-context merge-safety controls in branch protection."""
    findings: list[str] = []
    required_status_checks = payload.get("required_status_checks")
    if not isinstance(required_status_checks, dict):
        findings.append("Require status checks to pass before merging is disabled")
    elif required_status_checks.get("strict") is not True:
        findings.append("Require branches to be up to date before merging is disabled")

    if not isinstance(payload.get("required_pull_request_reviews"), dict):
        findings.append("Require a pull request before merging is disabled")

    enforce_admins = payload.get("enforce_admins")
    if not isinstance(enforce_admins, dict) or enforce_admins.get("enabled") is not True:
        findings.append("Administrator enforcement is disabled")

    allow_force_pushes = payload.get("allow_force_pushes")
    if not isinstance(allow_force_pushes, dict) or allow_force_pushes.get("enabled") is not False:
        findings.append("Force pushes are allowed or could not be verified as disabled")

    allow_deletions = payload.get("allow_deletions")
    if not isinstance(allow_deletions, dict) or allow_deletions.get("enabled") is not False:
        findings.append("Branch deletion is allowed or could not be verified as disabled")
    return findings


def _fetch_branch_protection(
    *, api_url: str, repo: str, branch: str, token: str | None, timeout: float
) -> dict[str, Any]:
    """Fetch complete branch protection so merge controls cannot escape the audit."""
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RequiredCheckAuditError(
            "GitHub API URL must be an HTTPS origin/path without credentials, query, or fragment"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RequiredCheckAuditError("Repository must use the validated owner/name form")
    endpoint = (
        f"{parsed.path.rstrip('/')}/repos/{repo}/branches/{quote(branch, safe='')}/protection"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sidar-required-check-audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request("GET", endpoint, headers=headers)
        response = connection.getresponse()
        raw_payload = response.read().decode("utf-8")
        if response.status == 403:
            raise RequiredCheckAuditError(
                "GitHub branch-protection API returned HTTP 403 for "
                f"{repo}@{branch}. Merge safety could not be verified. Configure "
                "BRANCH_PROTECTION_AUDIT_TOKEN with repository Administration: read "
                "permission (or an equivalent authorized admin token)."
            )
        if response.status >= 400:
            raise RequiredCheckAuditError(
                f"GitHub branch-protection API returned HTTP {response.status} for "
                f"{repo}@{branch}: {response.reason}"
            )
    except OSError as exc:
        raise RequiredCheckAuditError(
            f"GitHub branch-protection API could not be reached for {repo}@{branch}: {exc}"
        ) from exc
    finally:
        connection.close()
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise RequiredCheckAuditError("GitHub branch-protection API response was not an object")
    return payload


def audit_required_checks(
    *,
    workflow_path: Path,
    job_ids: tuple[str, ...],
    required_contexts: set[str],
) -> tuple[list[str], list[str]]:
    """Compare expected workflow check names with branch-protection contexts."""
    expected = _load_expected_check_names(workflow_path, job_ids)
    expected.append(BRANCH_PROTECTION_AUDIT_CONTEXT)
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
    parser.add_argument(
        "--token",
        default=os.getenv("BRANCH_PROTECTION_AUDIT_TOKEN") or os.getenv("GITHUB_TOKEN"),
        help=(
            "Authorized GitHub token. Defaults to BRANCH_PROTECTION_AUDIT_TOKEN, then "
            "GITHUB_TOKEN. Live audits require repository Administration: read permission."
        ),
    )
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
            merge_safety_findings: list[str] = []
        else:
            if not args.repo:
                raise RequiredCheckAuditError(
                    "Repository is unknown. Set GITHUB_REPOSITORY or pass --repo owner/repo."
                )
            protection = _fetch_branch_protection(
                api_url=args.api_url,
                repo=args.repo,
                branch=args.branch,
                token=args.token,
                timeout=args.timeout,
            )
            required_contexts = _extract_protection_required_contexts(protection)
            merge_safety_findings = audit_merge_safety(protection)
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
    if merge_safety_findings:
        print(
            "::error::Branch protection merge-safety policy violation(s): "
            + "; ".join(merge_safety_findings),
            file=sys.stderr,
        )
        return 1
    print("Branch protection required-check audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
