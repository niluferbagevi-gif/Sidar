from __future__ import annotations

import hashlib
import hmac

import pytest

try:
    import web_server
except ModuleNotFoundError as exc:
    pytest.skip(f"web_server import dependency missing: {exc}", allow_module_level=True)


def test_fallback_ci_failure_context_generic_flag() -> None:
    payload = {
        "ci_failure": True,
        "repo": "acme/repo",
        "workflow_name": "ci",
        "run_id": 77,
        "failed_jobs": ["test"],
    }
    result = web_server._fallback_ci_failure_context("any", payload)

    assert result["kind"] == "generic_ci_failure"
    assert result["repo"] == "acme/repo"
    assert result["workflow_name"] == "ci"
    assert result["run_id"] == "77"
    assert result["failed_jobs"] == ["test"]


def test_fallback_ci_failure_context_workflow_run_and_check_variants() -> None:
    workflow_payload = {
        "repository": {"full_name": "org/proj", "default_branch": "main"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "ci pipeline",
            "id": 12,
            "run_number": 4,
            "head_branch": "feat/x",
            "head_sha": "abc",
            "html_url": "http://example/run",
            "jobs_url": "http://example/jobs",
            "logs_url": "http://example/logs",
            "pull_requests": [{"base": {"ref": "develop"}}],
        },
    }
    out_workflow = web_server._fallback_ci_failure_context("workflow_run", workflow_payload)
    assert out_workflow["kind"] == "workflow_run"
    assert out_workflow["base_branch"] == "develop"

    check_run_payload = {
        "repository": {"name": "proj", "default_branch": "main"},
        "check_run": {
            "conclusion": "timed_out",
            "name": "lint",
            "id": 42,
            "status": "completed",
            "head_sha": "def",
            "check_suite": {"head_branch": "feat/y"},
            "details_url": "http://example/details",
            "output": {"title": "lint failed", "summary": "s", "text": "t"},
        },
    }
    out_check_run = web_server._fallback_ci_failure_context("check_run", check_run_payload)
    assert out_check_run["kind"] == "check_run"
    assert "s" in out_check_run["log_excerpt"]

    check_suite_payload = {
        "repository": {"default_branch": "main"},
        "check_suite": {
            "conclusion": "cancelled",
            "id": 9,
            "status": "completed",
            "head_branch": "hotfix/z",
            "head_sha": "ghi",
            "app": {"name": "gha"},
            "url": "http://example/suite",
        },
    }
    out_check_suite = web_server._fallback_ci_failure_context("check_suite", check_suite_payload)
    assert out_check_suite["kind"] == "check_suite"
    assert out_check_suite["workflow_name"] == "gha"


def test_resolve_ci_failure_context_prefers_core_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "build_ci_failure_context", lambda e, p: {"kind": "from_core", "event": e})
    assert web_server._resolve_ci_failure_context("evt", {}) == {"kind": "from_core", "event": "evt"}

    monkeypatch.setattr(web_server, "build_ci_failure_context", lambda e, p: {})
    fallback = web_server._resolve_ci_failure_context("pipeline_failed", {"repo": "org/repo"})
    assert fallback["kind"] == "generic_ci_failure"


def test_event_driven_federation_spec_github_jira_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "derive_correlation_id", lambda *parts: "cid-1")
    monkeypatch.setattr(web_server.secrets, "token_hex", lambda _: "abcd")

    jira = web_server._build_event_driven_federation_spec(
        "jira",
        "issue_created",
        {
            "issue": {"key": "SID-123", "summary": "Fix bug", "fields": {"project": {"key": "SID"}}},
            "action": "created",
        },
    )
    assert jira and jira["workflow_type"] == "jira_issue"

    gh = web_server._build_event_driven_federation_spec(
        "github",
        "pull_request",
        {
            "action": "opened",
            "repository": {"full_name": "org/repo"},
            "pull_request": {"number": 5, "title": "Add tests", "node_id": "n1", "base": {"ref": "main"}, "head": {"ref": "feat"}},
        },
    )
    assert gh and gh["workflow_type"] == "github_pull_request"

    system = web_server._build_event_driven_federation_spec(
        "system_monitor",
        "incident",
        {"severity": "critical", "alert_name": "db down", "message": "panic"},
    )
    assert system and system["workflow_type"] == "system_error"

    assert web_server._build_event_driven_federation_spec("unknown", "evt", {}) is None


def test_trim_swarm_goal_and_embed_payload() -> None:
    long_text = "x" * 1300
    trimmed = web_server._trim_autonomy_text(long_text, limit=12)
    assert trimmed.endswith("…[truncated]")

    spec = {"context": {"a": 1}, "inputs": ["x=1"]}
    coder_goal = web_server._build_swarm_goal_for_role("base", "coder", spec)
    reviewer_goal = web_server._build_swarm_goal_for_role("base", "reviewer", spec)
    assert "EVENT_DRIVEN_SWARM:CODER" in coder_goal
    assert "EVENT_DRIVEN_SWARM:REVIEWER" in reviewer_goal

    embedded = web_server._embed_event_driven_federation_payload(
        {"raw": 1},
        {"federation_task": {"task_id": "t1", "source_system": "github", "source_agent": "hook", "target_agent": "supervisor"}, "correlation_id": "c1", "federation_prompt": "p"},
    )
    assert embedded["task_id"] == "t1"
    assert embedded["event_payload"] == {"raw": 1}


def test_verify_hmac_signature_success_and_errors() -> None:
    body = b'{"ok": true}'
    secret = "secret"
    sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    web_server._verify_hmac_signature(body, secret, sig, label="Autonomy webhook")
    web_server._verify_hmac_signature(body, "", "", label="Autonomy webhook")

    with pytest.raises(web_server.HTTPException) as missing:
        web_server._verify_hmac_signature(body, secret, "", label="Autonomy webhook")
    assert missing.value.status_code == 401

    with pytest.raises(web_server.HTTPException) as bad:
        web_server._verify_hmac_signature(body, secret, "sha256=bad", label="Autonomy webhook")
    assert bad.value.status_code == 401


def test_git_run_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server.subprocess, "check_output", lambda *a, **k: b"main\n")
    assert web_server._git_run(["git", "status"], cwd=".") == "main"

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_server.subprocess, "check_output", _boom)
    assert web_server._git_run(["git", "status"], cwd=".") == ""
