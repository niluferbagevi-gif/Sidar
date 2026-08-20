from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

from scripts.ci import verify_required_checks as audit


def _workflow(path: Path) -> Path:
    path.write_text(
        "name: CI\n"
        "jobs:\n"
        "  test:\n"
        "    name: Base quality gates\n"
        "  installer-smoke:\n"
        "    name: Installer manifest and smoke gate\n"
        "  production-profile-dry-run:\n"
        "    name: Production-minimal runtime validation\n"
        "  gpu-inference-policy-gate:\n"
        "    name: GPU Inference Required Evidence Gate\n"
        "  production-readiness:\n"
        "    name: Production readiness aggregate\n"
        "  pg-stress:\n"
        "    name: PostgreSQL Connection Pool Stress Test\n",
        encoding="utf-8",
    )
    return path


def test_repo_from_git_remote_uses_allowlisted_absolute_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        audit.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None
    )

    def fake_check_output(command, **kwargs):  # noqa: ANN001 - subprocess argv test double.
        captured["command"] = command
        captured.update(kwargs)
        return "git@github.com:owner/repo.git\n"

    monkeypatch.setattr(audit.subprocess, "check_output", fake_check_output)

    assert audit._repo_from_git_remote() == "owner/repo"
    assert captured == {
        "command": ["/usr/bin/git", "remote", "get-url", "origin"],
        "text": True,
        "stderr": audit.subprocess.DEVNULL,
        "shell": False,
        "timeout": 10,
    }


def test_repo_from_git_remote_fails_closed_without_absolute_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        audit.subprocess,
        "check_output",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run without resolved git"),
    )

    assert audit._repo_from_git_remote() == ""


def test_audit_required_checks_accepts_all_release_contexts(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "ci.yml")
    expected_contexts = {
        "CI / Base quality gates",
        "CI / Installer manifest and smoke gate",
        "CI / Production-minimal runtime validation",
        "CI / GPU Inference Required Evidence Gate",
        "CI / Production readiness aggregate",
        "CI / PostgreSQL Connection Pool Stress Test",
        "CI / Extra non-release check",
    }

    expected, missing = audit.audit_required_checks(
        workflow_path=workflow,
        job_ids=audit.DEFAULT_RELEASE_JOB_IDS,
        required_contexts=expected_contexts,
    )

    assert expected == [
        "CI / Base quality gates",
        "CI / Installer manifest and smoke gate",
        "CI / Production-minimal runtime validation",
        "CI / GPU Inference Required Evidence Gate",
        "CI / Production readiness aggregate",
        "CI / PostgreSQL Connection Pool Stress Test",
    ]
    assert missing == []


def test_audit_required_checks_reports_missing_release_context(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "ci.yml")

    _expected, missing = audit.audit_required_checks(
        workflow_path=workflow,
        job_ids=audit.DEFAULT_RELEASE_JOB_IDS,
        required_contexts={
            "CI / Base quality gates",
            "CI / Installer manifest and smoke gate",
            "CI / Production-minimal runtime validation",
            "CI / GPU Inference Required Evidence Gate",
            "CI / Production readiness aggregate",
        },
    )

    assert missing == ["CI / PostgreSQL Connection Pool Stress Test"]


def test_extract_required_contexts_supports_legacy_contexts_and_checks() -> None:
    payload = {
        "contexts": ["CI / Base quality gates"],
        "checks": [
            {"context": "CI / Installer manifest and smoke gate", "app_id": 15368},
            {"context": "CI / PostgreSQL Connection Pool Stress Test"},
        ],
    }

    assert audit._extract_required_contexts(payload) == {
        "CI / Base quality gates",
        "CI / Installer manifest and smoke gate",
        "CI / PostgreSQL Connection Pool Stress Test",
    }


def test_fetch_required_contexts_uses_github_api_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"checks": [{"context": "CI / Installer manifest and smoke gate"}]}
            ).encode()

    def fake_urlopen(request, timeout):  # noqa: ANN001 - urllib Request type differs by Python minor.
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers.get("Authorization")
        captured["api_version"] = request.headers.get("X-github-api-version")
        return FakeResponse()

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)

    contexts = audit._fetch_required_contexts(
        api_url="https://api.github.test",
        repo="owner/repo",
        branch="main",
        token="token-123",
        timeout=3.0,
    )

    assert contexts == {"CI / Installer manifest and smoke gate"}
    assert captured == {
        "url": "https://api.github.test/repos/owner/repo/branches/main/protection/required_status_checks",
        "timeout": 3.0,
        "authorization": "Bearer token-123",
        "api_version": "2022-11-28",
    }


def test_fetch_required_contexts_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request, timeout):  # noqa: ANN001 - urllib Request type differs by Python minor.
        assert timeout == 3.0
        raise HTTPError("https://api.github.test", 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)

    with pytest.raises(audit.RequiredCheckAuditError, match="HTTP 404"):
        audit._fetch_required_contexts(
            api_url="https://api.github.test",
            repo="owner/repo",
            branch="main",
            token=None,
            timeout=3.0,
        )


def test_fetch_required_contexts_explains_403_admin_token_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(_request, timeout):  # noqa: ANN001 - urllib Request type differs by minor.
        assert timeout == 3.0
        raise HTTPError("https://api.github.test", 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(audit, "urlopen", fake_urlopen)

    with pytest.raises(audit.RequiredCheckAuditError) as exc_info:
        audit._fetch_required_contexts(
            api_url="https://api.github.test",
            repo="owner/repo",
            branch="main",
            token="insufficient-token",
            timeout=3.0,
        )

    message = str(exc_info.value)
    assert "HTTP 403" in message
    assert "BRANCH_PROTECTION_AUDIT_TOKEN" in message
    assert "Administration: read" in message
    assert "could not be compared with live branch protection" in message


def test_cli_prefers_branch_protection_audit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRANCH_PROTECTION_AUDIT_TOKEN", "admin-read-token")
    monkeypatch.setenv("GITHUB_TOKEN", "default-actions-token")

    args = audit._parse_args([])

    assert args.token == "admin-read-token"


def test_audit_workflow_injects_dedicated_admin_read_token() -> None:
    workflow = Path(".github/workflows/branch-protection-audit.yml").read_text(encoding="utf-8")

    assert "BRANCH_PROTECTION_AUDIT_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow


def test_audit_workflow_runs_on_schedule_dispatch_and_main_push() -> None:
    """Guard against a weekly-only cron leaving drift unnoticed for a week.

    A friend code review flagged that the weekly-only cron could leave a
    branch-protection misconfiguration unnoticed for up to a week. The audit
    must also re-verify on every push to main, not just on a Monday cron.
    """
    workflow_path = Path(".github/workflows/branch-protection-audit.yml")
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    triggers = workflow[True] if True in workflow else workflow["on"]
    assert "workflow_dispatch" in triggers
    assert any(entry.get("cron") for entry in triggers["schedule"])
    assert triggers["push"]["branches"] == ["main"]


def test_audit_workflow_alerts_on_failure_and_closes_on_recovery() -> None:
    """Guard the failure/recovery alert issue lifecycle.

    The audit failed 403 on every run for weeks without anyone noticing
    (see docs/CI_REQUIRED_CHECKS.md "Confirmed gap"): a red scheduled run
    alone was not visible enough. It must also file/comment on a standing
    issue when it fails, and close that issue once it passes again.
    """
    workflow = yaml.safe_load(
        Path(".github/workflows/branch-protection-audit.yml").read_text(encoding="utf-8")
    )

    assert workflow["permissions"]["issues"] == "write"

    steps = workflow["jobs"]["required-checks"]["steps"]
    steps_by_condition = {step.get("if"): step for step in steps if "if" in step}

    failure_step = steps_by_condition["failure()"]
    assert failure_step["uses"].startswith("actions/github-script@")
    assert "branch-protection-audit-failure" in failure_step["with"]["script"]
    assert "issues.create" in failure_step["with"]["script"]

    recovery_step = steps_by_condition["success()"]
    assert recovery_step["uses"].startswith("actions/github-script@")
    assert "branch-protection-audit-failure" in recovery_step["with"]["script"]
    assert 'state: "closed"' in recovery_step["with"]["script"]


def test_cli_offline_mode_fails_when_context_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = _workflow(tmp_path / "ci.yml")

    exit_code = audit.main(
        [
            "--workflow",
            str(workflow),
            "--required-context",
            "CI / Base quality gates",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "CI / Installer manifest and smoke gate" in captured.err
