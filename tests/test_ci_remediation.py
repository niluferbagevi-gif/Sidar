from __future__ import annotations

from core.ci_remediation import (
    _extract_root_cause_line,
    _extract_suspected_targets,
    _is_allowed_validation_command,
    build_ci_failure_context,
    build_ci_remediation_payload,
    is_ci_failure_event,
    normalize_self_heal_plan,
)


def test_is_allowed_validation_command() -> None:
    assert _is_allowed_validation_command("pytest tests/test_api.py -q") is True
    assert _is_allowed_validation_command("python -m pytest tests -k smoke") is False
    assert _is_allowed_validation_command("bash run_tests.sh") is True
    assert _is_allowed_validation_command("pytest tests && whoami") is False


def test_extract_helpers_find_targets_and_root_cause() -> None:
    text = "AssertionError in core/db.py and managers/github_manager.py"
    assert _extract_suspected_targets(text) == ["core/db.py", "managers/github_manager.py"]
    assert "AssertionError" in _extract_root_cause_line(text)


def test_build_ci_failure_context_from_generic_event() -> None:
    context = build_ci_failure_context(
        "ci_pipeline_failed",
        {
            "ci_failure": True,
            "repo": "acme/sidar",
            "workflow_name": "backend-tests",
            "run_id": "123",
            "failure_summary": "pytest failed",
            "log_excerpt": "ModuleNotFoundError: x in agent/sidar_agent.py",
            "failed_jobs": ["unit-tests"],
        },
    )
    assert context is not None
    assert context["kind"] == "generic_ci_failure"
    assert context["repo"] == "acme/sidar"
    assert "agent/sidar_agent.py" in context["suspected_targets"]


def test_workflow_run_failure_detection() -> None:
    payload = {"workflow_run": {"status": "completed", "conclusion": "failure"}}
    assert is_ci_failure_event("workflow_run", payload) is True


def test_normalize_self_heal_plan_filters_invalid_commands() -> None:
    plan = normalize_self_heal_plan(
        {
            "operations": [
                {
                    "action": "patch",
                    "path": "core/ci_remediation.py",
                    "target": "return False",
                    "replacement": "return True",
                }
            ],
            "validation_commands": ["pytest tests/test_ci_remediation.py", "pytest tests && rm -rf /"],
        },
        scope_paths=["core/ci_remediation.py"],
        fallback_validation_commands=["python -m pytest"],
    )
    assert len(plan["operations"]) == 1
    assert plan["validation_commands"] == ["pytest tests/test_ci_remediation.py", "python -m pytest"]


def test_build_ci_remediation_payload_contains_expected_sections() -> None:
    ctx = {
        "repo": "acme/sidar",
        "workflow_name": "backend",
        "run_id": "77",
        "branch": "feature/x",
        "failure_summary": "assertion failed",
        "log_excerpt": "AssertionError: x != y",
        "diagnostic_hints": ["hint"],
        "suspected_targets": ["core/ci_remediation.py"],
        "failed_jobs": ["unit"],
    }
    payload = build_ci_remediation_payload(ctx, diagnosis="Root cause is assertion drift")
    assert payload["context"]["repo"] == "acme/sidar"
    assert payload["suspected_targets"] == ["core/ci_remediation.py"]
    assert "pr_proposal" in payload
