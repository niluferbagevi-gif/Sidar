from core.ci_remediation import (
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
            "display_title": "pytest failed on reviewer flow",
            "pull_requests": [{"base": {"ref": "main"}}],
        },
    }

    assert is_ci_failure_event("workflow_run", payload) is True
    context = build_ci_failure_context("workflow_run", payload)
    assert context is not None
    assert context["repo"] == "acme/sidar"
    assert context["workflow_name"] == "CI"
    assert context["run_id"] == "42"

    prompt = build_ci_failure_prompt(context)
    assert "[CI_REMEDIATION]" in prompt
    assert "logs_url=https://api.github.com/logs/42" in prompt


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
                "summary": "tests/test_reviewer_agent.py failed",
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