from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        "Base quality gates",
        "Installer manifest and smoke gate",
        "Production-minimal runtime validation",
        "GPU Inference Required Evidence Gate",
        "Production readiness aggregate",
        "PostgreSQL Connection Pool Stress Test",
        "Extra non-release check",
        "Required release checks audit",
    }

    expected, missing = audit.audit_required_checks(
        workflow_path=workflow,
        job_ids=audit.DEFAULT_RELEASE_JOB_IDS,
        required_contexts=expected_contexts,
    )

    assert expected == [
        "Base quality gates",
        "Installer manifest and smoke gate",
        "Production-minimal runtime validation",
        "GPU Inference Required Evidence Gate",
        "Production readiness aggregate",
        "PostgreSQL Connection Pool Stress Test",
        "Required release checks audit",
    ]
    assert missing == []


def test_audit_required_checks_reports_missing_release_context(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "ci.yml")

    _expected, missing = audit.audit_required_checks(
        workflow_path=workflow,
        job_ids=audit.DEFAULT_RELEASE_JOB_IDS,
        required_contexts={
            "Base quality gates",
            "Installer manifest and smoke gate",
            "Production-minimal runtime validation",
            "GPU Inference Required Evidence Gate",
            "Production readiness aggregate",
            "Required release checks audit",
        },
    )

    assert missing == ["PostgreSQL Connection Pool Stress Test"]


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


def test_audit_merge_safety_accepts_fail_closed_protection() -> None:
    payload = {
        "required_status_checks": {"strict": True, "checks": []},
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }

    assert audit.audit_merge_safety(payload) == []


def test_audit_merge_safety_reports_each_unsafe_control() -> None:
    payload = {
        "required_status_checks": {"strict": False, "checks": []},
        "enforce_admins": {"enabled": False},
        "allow_force_pushes": {"enabled": True},
        "allow_deletions": {"enabled": True},
    }

    assert audit.audit_merge_safety(payload) == [
        "Require branches to be up to date before merging is disabled",
        "Require a pull request before merging is disabled",
        "Administrator enforcement is disabled",
        "Force pushes are allowed or could not be verified as disabled",
        "Branch deletion is allowed or could not be verified as disabled",
    ]


def test_extract_protection_required_contexts_uses_nested_payload() -> None:
    payload = {
        "required_status_checks": {"checks": [{"context": "CI / Production readiness aggregate"}]}
    }

    assert audit._extract_protection_required_contexts(payload) == {
        "CI / Production readiness aggregate"
    }


def test_fetch_branch_protection_uses_complete_protection_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    payload = {
        "required_status_checks": {"strict": True, "checks": []},
        "required_pull_request_reviews": {},
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }

    class FakeResponse:
        status = 200
        reason = "OK"

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    class FakeConnection:
        def __init__(self, host, port, timeout):  # noqa: ANN001 - protocol test double.
            captured.update(host=host, port=port, timeout=timeout)

        def request(self, method, path, headers):  # noqa: ANN001 - protocol test double.
            captured.update(method=method, path=path, headers=headers)

        def getresponse(self):  # noqa: ANN201 - protocol test double.
            return FakeResponse()

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(audit.http.client, "HTTPSConnection", FakeConnection)

    assert (
        audit._fetch_branch_protection(
            api_url="https://api.github.test",
            repo="owner/repo",
            branch="main",
            token="token-123",
            timeout=3.0,
        )
        == payload
    )
    assert captured == {
        "host": "api.github.test",
        "port": None,
        "timeout": 3.0,
        "method": "GET",
        "path": "/repos/owner/repo/branches/main/protection",
        "headers": {
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer token-123",
            "User-Agent": "sidar-required-check-audit",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        "closed": True,
    }


@pytest.mark.parametrize(
    "api_url",
    ["http://api.github.test", "https://user:secret@api.github.test", "file:///tmp/api"],
)
def test_fetch_branch_protection_rejects_unsafe_api_urls(api_url: str) -> None:
    with pytest.raises(audit.RequiredCheckAuditError, match="must be an HTTPS"):
        audit._fetch_branch_protection(
            api_url=api_url, repo="owner/repo", branch="main", token="token", timeout=3.0
        )


def test_fetch_branch_protection_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status = 404
        reason = "Not Found"

        def read(self) -> bytes:
            return b"{}"

    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(audit.http.client, "HTTPSConnection", FakeConnection)

    with pytest.raises(audit.RequiredCheckAuditError, match="HTTP 404"):
        audit._fetch_branch_protection(
            api_url="https://api.github.test",
            repo="owner/repo",
            branch="main",
            token=None,
            timeout=3.0,
        )


def test_fetch_branch_protection_explains_403_admin_token_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenResponse:
        status = 403
        reason = "Forbidden"

        def read(self) -> bytes:
            return b"{}"

    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return ForbiddenResponse()

        def close(self):
            pass

    monkeypatch.setattr(audit.http.client, "HTTPSConnection", FakeConnection)

    with pytest.raises(audit.RequiredCheckAuditError) as exc_info:
        audit._fetch_branch_protection(
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
    assert "Merge safety could not be verified" in message


def test_cli_prefers_branch_protection_audit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRANCH_PROTECTION_AUDIT_TOKEN", "admin-read-token")
    monkeypatch.setenv("GITHUB_TOKEN", "default-actions-token")

    args = audit._parse_args([])

    assert args.token == "admin-read-token"


def test_audit_workflow_injects_dedicated_admin_read_token() -> None:
    workflow = Path(".github/workflows/branch-protection-audit.yml").read_text(encoding="utf-8")

    assert "BRANCH_PROTECTION_AUDIT_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}" in workflow
    assert "pull_request_target:" in workflow
    assert "branches: [main]" in workflow
    assert "issues: write" in workflow
    assert "actions/github-script@v8" in workflow
    assert "if: steps.audit.outcome == 'failure'" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow


def test_cli_offline_mode_fails_when_context_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = _workflow(tmp_path / "ci.yml")

    exit_code = audit.main(
        [
            "--workflow",
            str(workflow),
            "--required-context",
            "Base quality gates",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Installer manifest and smoke gate" in captured.err
