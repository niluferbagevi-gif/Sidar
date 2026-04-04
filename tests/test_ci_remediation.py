from __future__ import annotations

from core.ci_remediation import (
    _build_diagnostic_hints,
    _extract_failed_job_names,
    _extract_root_cause_line,
    _extract_suspected_targets,
    _extract_validation_commands,
    _generic_ci_context,
    _is_allowed_validation_command,
    _trim_text,
    build_ci_failure_context,
    build_pr_proposal,
    build_remediation_loop,
    build_ci_remediation_payload,
    build_root_cause_summary,
    build_self_heal_patch_prompt,
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

def test_validation_command_guards_extra_cases() -> None:
    assert _is_allowed_validation_command("") is False
    assert _is_allowed_validation_command("`pytest -q tests/core/test_rag.py`") is True
    assert _is_allowed_validation_command("pytest tests/test_api.py | cat") is False
    assert _is_allowed_validation_command("python -m pytest tests/core/test_rag.py -q") is True
    assert _is_allowed_validation_command("bash run_tests.sh smoke") is True
    assert _is_allowed_validation_command("bash run_tests.sh smoke;whoami") is False


def test_trim_text_and_job_name_helpers() -> None:
    long = "x" * 20
    assert _trim_text(long, 10).endswith("…[truncated]")
    jobs = _extract_failed_job_names({"jobs": [{"name": "unit"}, {"title": "integration"}, "unit", "e2e"]})
    assert jobs == ["unit", "integration", "e2e"]


def test_generic_ci_context_none_and_populated() -> None:
    assert _generic_ci_context("push", {"message": "ok"}) is None

    ctx = _generic_ci_context(
        "pipeline_failed",
        {
            "summary": "pytest timeout",
            "error": "ImportError at core/router.py\nAssertionError happened",
            "jobs": [{"job": "unit"}],
            "repository": "org/repo",
            "pipeline": "ci",
            "pipeline_id": "9",
            "pipeline_number": "14",
            "target_branch": "develop",
        },
    )
    assert ctx is not None
    assert ctx["repo"] == "org/repo"
    assert "core/router.py" in ctx["suspected_targets"]
    assert ctx["failed_jobs"] == ["unit"]
    assert ctx["base_branch"] == "develop"


def test_build_diagnostic_hints_variants() -> None:
    hints = _build_diagnostic_hints(
        "pytest timeout",
        "assert failed and import chain broken",
        ["tests/test_x.py"],
    )
    assert any("İlk inceleme" in h for h in hints)
    assert any("Timeout" in h for h in hints)
    assert any("Import" in h for h in hints)


def test_ci_failure_context_check_run_and_check_suite() -> None:
    check_run_ctx = build_ci_failure_context(
        "check_run",
        {
            "repository": {"full_name": "acme/sidar", "default_branch": "main"},
            "check_run": {
                "conclusion": "failure",
                "name": "lint",
                "id": 42,
                "head_sha": "abc",
                "status": "completed",
                "html_url": "https://example/check",
                "details_url": "https://example/details",
                "check_suite": {"head_branch": "feat/x"},
                "output": {
                    "title": "lint failed",
                    "summary": "AssertionError in tests/test_ci_remediation.py",
                    "text": "ModuleNotFoundError in core/db.py",
                },
            },
        },
    )
    assert check_run_ctx is not None
    assert check_run_ctx["kind"] == "check_run"
    assert "core/db.py" in check_run_ctx["suspected_targets"]

    check_suite_ctx = build_ci_failure_context(
        "check_suite",
        {
            "repository": {"name": "sidar", "default_branch": "main"},
            "check_suite": {
                "conclusion": "timed_out",
                "status": "completed",
                "head_branch": "bugfix",
                "id": 99,
                "head_sha": "def",
                "url": "https://example/suite",
                "app": {"name": "checks"},
                "jobs": ["job-a"],
            },
        },
    )
    assert check_suite_ctx is not None
    assert check_suite_ctx["kind"] == "check_suite"
    assert check_suite_ctx["failed_jobs"] == ["job-a"]


def test_is_ci_failure_event_other_branches() -> None:
    assert is_ci_failure_event("check_run", {"check_run": {"conclusion": "cancelled"}}) is True
    assert is_ci_failure_event("check_suite", {"check_suite": {"conclusion": "neutral"}}) is False
    assert is_ci_failure_event("workflow_run", {"workflow_run": {"status": "queued", "conclusion": "failure"}}) is False


def test_build_root_cause_summary_and_pr_proposal() -> None:
    ctx = {"failure_summary": "ModuleNotFoundError seen", "root_cause_hint": "hint", "base_branch": "main"}
    assert build_root_cause_summary(ctx, "Kök neden: import kırılmış") == "Kök neden: import kırılmış"
    assert "ModuleNotFoundError" in build_root_cause_summary({"failure_summary": "ModuleNotFoundError: x"}, "")
    assert build_root_cause_summary({"failure_summary": "just fail", "root_cause_hint": "hint"}, "") == "hint"

    proposal = build_pr_proposal(
        {
            "repo": "acme/sidar",
            "workflow_name": "tests",
            "run_id": "12",
            "base_branch": "main",
            "branch": "feat",
            "sha": "abc",
            "html_url": "u",
            "logs_url": "l",
            "failure_summary": "failed",
        },
        diagnosis="Root cause line\nsecond line",
    )
    assert proposal["title"].startswith("CI remediation")
    assert proposal["auto_create_ready"] is True
    assert "Root Cause Hypothesis" in proposal["body"]


def test_extract_validation_commands_and_build_remediation_loop() -> None:
    context = {
        "failure_summary": "pytest -q tests/test_ci_remediation.py",
        "log_excerpt": "python -m pytest tests/core/test_rag.py\npytest tests && rm",
        "suspected_targets": ["tests/test_ci_remediation.py", "core/ci_remediation.py", "a", "b"],
        "failed_jobs": ["unit", "lint"],
    }
    cmds = _extract_validation_commands(context, "bash run_tests.sh smoke")
    assert "pytest -q tests/test_ci_remediation.py" in cmds
    assert "python -m pytest tests/core/test_rag.py" in cmds
    assert all("&&" not in c for c in cmds)

    loop = build_remediation_loop(context, "TypeError happened")
    assert loop["needs_human_approval"] is True
    assert loop["mode"] == "self_heal_with_hitl"
    assert loop["max_auto_attempts"] == 1

    loop2 = build_remediation_loop({"suspected_targets": ["core/ci_remediation.py"], "failure_summary": "minor"}, "")
    assert loop2["status"] == "planned"
    assert loop2["mode"] == "self_heal"


def test_build_self_heal_patch_prompt_and_normalize_variants() -> None:
    prompt = build_self_heal_patch_prompt(
        {"repo": "acme/sidar", "workflow_name": "ci", "failure_summary": "f", "root_cause_hint": "r"},
        diagnosis="d",
        remediation_loop={"scope_paths": ["core/ci_remediation.py"], "validation_commands": ["pytest -q"]},
        file_snapshots=[
            {"path": "core/ci_remediation.py", "content": "line" * 2000},
            {"path": "", "content": "skip"},
        ],
    )
    assert prompt.startswith("[SELF_HEAL_PLAN]")
    assert "core/ci_remediation.py" in prompt

    code_fenced = """```json
    {"summary":"ok","confidence":"HIGH","operations":[{"action":"patch","path":"./core/ci_remediation.py","target":"a","replacement":"b"},{"action":"write","path":"x","target":"a","replacement":"b"}],"validation_commands":["pytest tests/test_ci_remediation.py","echo bad"]}
    ```"""
    normalized = normalize_self_heal_plan(
        code_fenced,
        scope_paths=["core/ci_remediation.py"],
        fallback_validation_commands=["python -m pytest", "python -m pytest"],
        max_operations=5,
    )
    assert normalized["confidence"] == "high"
    assert normalized["operations"] == [
        {"action": "patch", "path": "core/ci_remediation.py", "target": "a", "replacement": "b"}
    ]
    assert normalized["validation_commands"] == ["pytest tests/test_ci_remediation.py", "python -m pytest"]

    normalized2 = normalize_self_heal_plan(123, scope_paths=[], fallback_validation_commands=["invalid ; cmd"])
    assert normalized2["operations"] == []
    assert normalized2["validation_commands"] == []
