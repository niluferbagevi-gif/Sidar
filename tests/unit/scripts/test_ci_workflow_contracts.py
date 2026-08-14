"""Repository-access contracts for GitHub-hosted workflow jobs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(".github/workflows")
REPOSITORY_SCRIPT_COMMAND = re.compile(
    r"(?:^|[;&|]\s*|\n\s*)(?:uv\s+run\s+)?(?:bash|python(?:3)?)\s+"
    r"(?:\./)?scripts/[^\s;&|]+",
    re.MULTILINE,
)
GITHUB_HOSTED_LABELS = ("ubuntu-", "windows-", "macos-")


def _uses_github_hosted_runner(runs_on: Any) -> bool:
    """Return whether a job selects one of GitHub's hosted runner images."""
    labels = [runs_on] if isinstance(runs_on, str) else runs_on
    return isinstance(labels, list) and any(
        isinstance(label, str) and label.startswith(GITHUB_HOSTED_LABELS) for label in labels
    )


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda path: path.name)
def test_github_hosted_script_jobs_checkout_repository_first(workflow: Path) -> None:
    """Repo-local script commands must never run before the repository is available."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))

    for job_id, job in (document.get("jobs") or {}).items():
        if not _uses_github_hosted_runner(job.get("runs-on")):
            continue

        checkout_seen = False
        for step_number, step in enumerate(job.get("steps") or (), start=1):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                checkout_seen = True
            command = str(step.get("run", ""))
            if REPOSITORY_SCRIPT_COMMAND.search(command):
                assert checkout_seen, (
                    f"{workflow}: job {job_id!r}, step {step_number} runs a repository-local "
                    "script before actions/checkout"
                )
