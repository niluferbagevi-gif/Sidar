from core.ci_remediation import (
    build_ci_remediation_payload,
    build_ci_failure_context,
    build_ci_failure_prompt,
    build_pr_proposal,
    is_ci_failure_event,
)


def test_workflow_run_failure_context_and_prompt_are_built():
    payload = {
        "repository": {"full_name": "acme/sidar", "default_branch": "main"},
        "workflow_run": {
            "id": 42,
            "run_number": 9,
            "name": "CI",
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "feature/test",
            "head_sha": "abc123",
            "html_url": "https://github.com/acme/sidar/actions/runs/42",
            "jobs_url": "https://api.github.com/jobs/42",
            "logs_url": "https://api.github.com/logs/42",
            "display_title": "pytest failed on tests/test_reviewer_agent.py",
            "pull_requests": [{"base": {"ref": "main"}}],
        },
    }

    assert is_ci_failure_event("workflow_run", payload) is True
    context = build_ci_failure_context("workflow_run", payload)
    assert context is not None
    assert context["repo"] == "acme/sidar"
    assert context["workflow_name"] == "CI"
    assert context["run_id"] == "42"
    assert context["suspected_targets"] == ["tests/test_reviewer_agent.py"]
    assert context["diagnostic_hints"]

    prompt = build_ci_failure_prompt(context)
    assert "[CI_REMEDIATION]" in prompt
    assert "logs_url=https://api.github.com/logs/42" in prompt
    assert "suspected_targets=tests/test_reviewer_agent.py" in prompt


def test_check_run_failure_generates_pr_proposal():
    payload = {
        "repository": {"full_name": "acme/sidar", "default_branch": "main"},
        "check_run": {
            "id": 501,
            "name": "pytest",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "def456",
            "details_url": "https://github.com/acme/sidar/checks/501",
            "html_url": "https://github.com/acme/sidar/checks/501",
            "output": {
                "title": "2 tests failed",
                "summary": "tests/test_reviewer_agent.py failed while importing core/rag.py",
                "text": "AssertionError: expected approve",
            },
        },
    }

    context = build_ci_failure_context("check_run", payload)
    assert context is not None
    proposal = build_pr_proposal(context, "Kök neden pytest beklentisi ile runtime çıktısının drift etmesi.")

    assert proposal["title"].startswith("CI remediation:")
    assert proposal["base_branch"] == "main"
    assert proposal["head_branch_suggestion"] == "ci-remediation/501"
    assert "Kök neden" in proposal["body"]
    assert "tests/test_reviewer_agent.py" in proposal["body"]


def test_generic_ci_failure_payload_builds_structured_remediation():
    payload = {
        "event_name": "ci_pipeline_failed",
        "ci_failure": True,
        "repo": "acme/sidar",
        "workflow_name": "Nightly",
        "pipeline_id": 901,
        "branch": "main",
        "base_branch": "main",
        "failure_summary": "pytest timed out on tests/test_web_server_voice.py",
        "log_excerpt": "TimeoutError: tests/test_web_server_voice.py exceeded 120s",
        "failed_jobs": [{"name": "pytest"}],
        "logs_url": "https://ci.example/logs/901",
    }

    context = build_ci_failure_context("ci_pipeline_failed", payload)

    assert context is not None
    assert context["kind"] == "generic_ci_failure"
    assert context["workflow_name"] == "Nightly"
    assert context["failed_jobs"] == ["pytest"]
    assert context["root_cause_hint"].startswith("TimeoutError")

    remediation = build_ci_remediation_payload(context, "TimeoutError: flaky websocket teardown causes long wait.")
    assert remediation["root_cause_summary"].startswith("TimeoutError")
    assert remediation["pr_proposal"]["auto_create_ready"] is True
    assert "Root Cause Hypothesis" in remediation["pr_proposal"]["body"]
