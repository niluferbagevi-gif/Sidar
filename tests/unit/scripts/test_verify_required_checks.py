from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

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
        "  pg-stress:\n"
        "    name: PostgreSQL Connection Pool Stress Test\n",
        encoding="utf-8",
    )
    return path


def test_audit_required_checks_accepts_all_release_contexts(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path / "ci.yml")
    expected_contexts = {
        "CI / Base quality gates",
        "CI / Installer manifest and smoke gate",
        "CI / Production-minimal runtime validation",
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


def test_cli_offline_mode_fails_when_context_is_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
