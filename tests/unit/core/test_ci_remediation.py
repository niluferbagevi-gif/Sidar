from __future__ import annotations

import json

import pytest

import core.ci_remediation as ci


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("", False),
        ("pytest -q tests/unit/core/test_ci_remediation.py", True),
        ("python -m pytest tests/unit/core/test_ci_remediation.py", True),
        ("bash run_tests.sh unit", True),
        ("pytest && echo hacked", False),
        ("pytest -q; rm -rf /", False),
        ("unknown cmd", False),
        ("`pytest -q`", True),
        ("pytest [", False),
    ],
)
def test_is_allowed_validation_command(command: str, expected: bool) -> None:
    assert ci._is_allowed_validation_command(command) is expected


def test_is_allowed_validation_command_handles_split_errors_and_empty_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ci.shlex, "split", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom"))
    )
    assert ci._is_allowed_validation_command("pytest -q tests/x.py") is False
    monkeypatch.setattr(ci.shlex, "split", lambda *_args, **_kwargs: [])
    assert ci._is_allowed_validation_command("pytest -q tests/x.py") is False


def test_trim_text_with_and_without_truncation() -> None:
    assert ci._trim_text("  ok  ", 10) == "ok"
    assert ci._trim_text("x" * 10, 10) == "x" * 10
    truncated = ci._trim_text("x" * 20, 10)
    assert truncated.endswith("…[truncated]")
    assert truncated.startswith("x" * 10)


def test_extract_suspected_targets_deduplicates_and_limits() -> None:
    text = "\n".join(
        [
            "tests/unit/a.py failed",
            "core/x.py had issue",
            "tests/unit/a.py duplicate",
            "agent/roles/r.py",
            "managers/m.py",
            "web_server/api.py",
            "main/app.py",
            "config/dev.py",
            "docs/readme.md",
            "web_ui_react/src/App.tsx",
        ]
    )
    targets = ci._extract_suspected_targets(text)
    assert len(targets) == 8
    assert targets[0] == "tests/unit/a.py"
    assert "tests/unit/a.py" in targets
    assert "core/x.py" in targets


def test_extract_root_cause_line_finds_first_matching_line() -> None:
    line = ci._extract_root_cause_line(
        "noise\nAssertionError: boom\nTypeError: second",
        "ValueError: other",
    )
    assert line == "AssertionError: boom"
    assert ci._extract_root_cause_line("all good") == ""


def test_extract_root_cause_line_skips_empty_lines() -> None:
    line = ci._extract_root_cause_line("\n   \nValueError: invalid payload")
    assert line == "ValueError: invalid payload"


def test_extract_failed_job_names_handles_dicts_and_strings() -> None:
    data = {
        "failed_jobs": [
            {"name": "lint"},
            {"job": "tests"},
            {"title": "build"},
            "deploy",
            "deploy",
        ]
    }
    assert ci._extract_failed_job_names(data) == ["lint", "tests", "build", "deploy"]


def test_build_diagnostic_hints_applies_all_rules_and_limit() -> None:
    hints = ci._build_diagnostic_hints(
        "pytest timeout",
        "assert failed import module error",
        [f"tests/t{i}.py" for i in range(10)],
    )
    assert hints[0].startswith("İlk inceleme hedefleri")
    assert any("assertion" in h.lower() for h in hints)
    assert any("timeout" in h.lower() for h in hints)
    assert any("import" in h.lower() for h in hints)
    assert len(hints) <= 5


def test_generic_ci_context_requires_flag_or_ci_event() -> None:
    assert ci._generic_ci_context("push", {"message": "x"}) is None

    ctx = ci._generic_ci_context(
        "pipeline_failed",
        {
            "repo": "org/repo",
            "failure_summary": "pytest failure",
            "logs": "AssertionError at tests/unit/core/test_ci_remediation.py",
            "failed_jobs": ["tests"],
            "workflow_name": "CI",
            "run_id": 7,
            "pipeline_number": 22,
            "branch": "feat",
            "target_branch": "main",
            "sha": "abc",
            "pipeline_url": "http://ci",
            "log_url": "http://logs",
        },
    )
    assert ctx is not None
    assert ctx["kind"] == "generic_ci_failure"
    assert ctx["repo"] == "org/repo"
    assert ctx["run_id"] == "7"
    assert "tests/unit/core/test_ci_remediation.py" in ctx["suspected_targets"]


@pytest.mark.parametrize(
    ("event_name", "payload", "expected"),
    [
        (
            "workflow_run",
            {"workflow_run": {"status": "completed", "conclusion": "failure"}},
            True,
        ),
        (
            "workflow_run",
            {"workflow_run": {"status": "in_progress", "conclusion": "failure"}},
            False,
        ),
        ("check_run", {"check_run": {"conclusion": "cancelled"}}, True),
        ("check_suite", {"check_suite": {"conclusion": "success"}}, False),
        ("push", {}, False),
    ],
)
def test_is_ci_failure_event(event_name, payload, expected) -> None:
    assert ci.is_ci_failure_event(event_name, payload) is expected


def test_build_ci_failure_context_returns_none_when_not_failure() -> None:
    assert ci.build_ci_failure_context("push", {}) is None


def test_build_ci_failure_context_prefers_generic() -> None:
    ctx = ci.build_ci_failure_context("ci_pipeline_failed", {"ci_failure": True, "repo": "x/y"})
    assert ctx is not None
    assert ctx["kind"] == "generic_ci_failure"


def test_build_ci_failure_context_workflow_run() -> None:
    payload = {
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "backend-ci",
            "id": 11,
            "run_number": 12,
            "head_branch": "feat",
            "head_sha": "sha",
            "html_url": "http://html",
            "jobs_url": "http://jobs",
            "logs_url": "http://logs",
            "display_title": "tests/unit/core/test_ci_remediation.py AssertionError",
            "pull_requests": [{"base": {"ref": "develop"}}],
            "failed_jobs": [{"name": "tests"}],
        },
    }
    ctx = ci.build_ci_failure_context("workflow_run", payload)
    assert ctx is not None
    assert ctx["kind"] == "workflow_run"
    assert ctx["base_branch"] == "develop"
    assert "tests/unit/core/test_ci_remediation.py" in ctx["suspected_targets"]


def test_build_ci_failure_context_check_run() -> None:
    payload = {
        "repository": {"name": "repo", "default_branch": "main"},
        "check_run": {
            "conclusion": "failure",
            "name": "pytest",
            "id": 3,
            "head_sha": "abc",
            "status": "completed",
            "html_url": "http://html",
            "details_url": "http://details",
            "check_suite": {"head_branch": "feat"},
            "output": {
                "title": "check failed",
                "summary": "AssertionError in tests/unit/core/test_ci_remediation.py",
                "text": "ImportError at core/ci_remediation.py",
            },
        },
    }
    ctx = ci.build_ci_failure_context("check_run", payload)
    assert ctx is not None
    assert ctx["kind"] == "check_run"
    assert ctx["branch"] == "feat"
    assert len(ctx["diagnostic_hints"]) >= 1


def test_build_ci_failure_context_check_suite() -> None:
    payload = {
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "check_suite": {
            "conclusion": "timed_out",
            "status": "completed",
            "id": 4,
            "head_branch": "feat",
            "head_sha": "sha",
            "url": "http://suite",
            "app": {"name": "suite-app"},
            "failed_jobs": ["suite-job"],
        },
    }
    ctx = ci.build_ci_failure_context("check_suite", payload)
    assert ctx is not None
    assert ctx["kind"] == "check_suite"
    assert ctx["html_url"] == "http://suite"


def _sample_context() -> dict:
    return {
        "repo": "org/repo",
        "kind": "workflow_run",
        "workflow_name": "backend-ci",
        "run_id": "99",
        "run_number": "101",
        "branch": "feat/fix",
        "base_branch": "main",
        "sha": "deadbeef",
        "status": "completed",
        "conclusion": "failure",
        "html_url": "http://html",
        "jobs_url": "http://jobs",
        "logs_url": "http://logs",
        "failure_summary": "pytest timeout",
        "log_excerpt": "AssertionError in tests/unit/core/test_ci_remediation.py",
        "failed_jobs": ["tests"],
        "root_cause_hint": "AssertionError in test_x",
        "suspected_targets": ["tests/unit/core/test_ci_remediation.py", "core/ci_remediation.py"],
        "diagnostic_hints": ["hint1"],
    }


def test_build_ci_failure_prompt_contains_fields() -> None:
    prompt = ci.build_ci_failure_prompt(_sample_context())
    assert "[CI_REMEDIATION]" in prompt
    assert "workflow_name=backend-ci" in prompt
    assert "failed_jobs=tests" in prompt


def test_build_self_heal_patch_prompt_limits_snapshots_and_embeds_data() -> None:
    snapshots = [{"path": f"tests/t{i}.py", "content": "x" * 20} for i in range(8)]
    prompt = ci.build_self_heal_patch_prompt(
        _sample_context(),
        diagnosis="root cause\nmore",
        remediation_loop={
            "scope_paths": ["tests/t1.py"],
            "validation_commands": ["pytest -q tests/t1.py"],
        },
        file_snapshots=snapshots,
    )
    assert prompt.startswith("[SELF_HEAL_PLAN]")
    assert "tests/t1.py" in prompt
    assert prompt.count("[FILE]") == 6


def test_normalize_self_heal_plan_from_markdown_json_and_filters() -> None:
    raw = """```json
    {
      "summary": "ok",
      "confidence": "HIGH",
      "operations": [
        {"action":"patch","path":"tests/unit/core/test_ci_remediation.py","target":"a","replacement":"b"},
        {"action":"delete","path":"x","target":"a","replacement":"b"},
        {"action":"patch","path":"../evil.py","target":"a","replacement":"b"}
      ],
      "validation_commands": ["pytest -q tests/unit/core/test_ci_remediation.py", "echo bad"]
    }
    ```"""
    normalized = ci.normalize_self_heal_plan(
        raw,
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=["python -m pytest", "echo nope"],
    )
    assert normalized["summary"] == "ok"
    assert normalized["confidence"] == "high"
    assert normalized["operations"] == [
        {
            "action": "patch",
            "path": "tests/unit/core/test_ci_remediation.py",
            "target": "a",
            "replacement": "b",
        }
    ]
    assert normalized["validation_commands"] == [
        "pytest -q tests/unit/core/test_ci_remediation.py",
        "python -m pytest",
    ]


def test_normalize_self_heal_plan_with_invalid_input_uses_defaults() -> None:
    normalized = ci.normalize_self_heal_plan(None, scope_paths=[], fallback_validation_commands=[])
    assert normalized["operations"] == []
    assert normalized["validation_commands"] == []
    assert normalized["summary"]


def test_normalize_self_heal_plan_handles_non_json_fence_and_bad_json() -> None:
    raw_non_json_fence = """```text
    not-json-body
    ```"""
    normalized_non_json = ci.normalize_self_heal_plan(
        raw_non_json_fence,
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=[],
    )
    assert normalized_non_json["operations"] == []

    raw_bad_json = '{"operations": [}'
    normalized_bad_json = ci.normalize_self_heal_plan(
        raw_bad_json,
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=[],
    )
    assert normalized_bad_json["operations"] == []


def test_normalize_self_heal_plan_deduplicates_validation_commands() -> None:
    raw = {
        "validation_commands": [
            "pytest -q tests/unit/core/test_ci_remediation.py",
            "pytest -q tests/unit/core/test_ci_remediation.py",
        ]
    }
    normalized = ci.normalize_self_heal_plan(
        raw,
        scope_paths=[],
        fallback_validation_commands=["pytest -q tests/unit/core/test_ci_remediation.py"],
    )
    assert normalized["validation_commands"] == ["pytest -q tests/unit/core/test_ci_remediation.py"]


def test_build_root_cause_summary_prefers_diagnosis_first_line() -> None:
    summary = ci.build_root_cause_summary(
        _sample_context(), "Root cause: flaky assertion\nsecond line"
    )
    assert summary.startswith("Root cause")


def test_build_root_cause_summary_fallback_order() -> None:
    info = _sample_context()
    info["root_cause_hint"] = "hint cause"
    info["failure_summary"] = "fallback summary"
    assert "AssertionError" in ci.build_root_cause_summary(info, "")

    info2 = {"root_cause_hint": "hint cause", "failure_summary": "fallback summary"}
    assert ci.build_root_cause_summary(info2, "") == "hint cause"

    info3 = _sample_context()
    info3["root_cause_hint"] = ""
    info3["log_excerpt"] = "TypeError: broken"
    assert "TypeError" in ci.build_root_cause_summary(info3, "")

    info4 = {"failure_summary": "final summary"}
    assert ci.build_root_cause_summary(info4, "") == "final summary"


def test_build_pr_proposal_shapes_content() -> None:
    proposal = ci.build_pr_proposal(_sample_context(), "Diagnosis body")
    assert proposal["title"].startswith("CI remediation")
    assert proposal["base_branch"] == "main"
    assert proposal["head_branch_suggestion"] == "ci-remediation/99"
    assert proposal["auto_create_ready"] is True
    assert "## Context" in proposal["body"]


def test_extract_validation_commands_discovers_and_deduplicates() -> None:
    context = _sample_context()
    context["failure_summary"] = "pytest -q tests/unit/core/test_ci_remediation.py"
    context["log_excerpt"] = "python -m pytest\npython -m pytest"
    commands = ci._extract_validation_commands(context, "bash run_tests.sh unit")
    assert commands[0] == "pytest -q tests/unit/core/test_ci_remediation.py"
    assert "python -m pytest" in commands
    assert any(cmd.startswith("pytest -q tests/") for cmd in commands)


def test_build_remediation_loop_high_risk_and_normal_modes() -> None:
    risky = ci.build_remediation_loop(_sample_context(), "SyntaxError: bad")
    assert risky["needs_human_approval"] is True
    assert risky["mode"] == "self_heal_with_hitl"
    assert risky["max_auto_attempts"] == 1
    assert risky["steps"][0]["status"] == "completed"

    safe_context = {
        "failure_summary": "minor",
        "log_excerpt": "",
        "suspected_targets": [],
        "failed_jobs": [],
    }
    safe = ci.build_remediation_loop(safe_context, "")
    assert safe["needs_human_approval"] is False
    assert safe["mode"] == "self_heal"
    assert safe["status"] == "needs_diagnosis"
    assert safe["steps"][1]["status"] == "blocked"


def test_build_ci_remediation_payload_assembles_all_parts() -> None:
    context = _sample_context()
    payload = ci.build_ci_remediation_payload(context, "Diagnosis")
    assert payload["context"] == context
    assert payload["prompt"].startswith("[CI_REMEDIATION]")
    assert payload["pr_proposal"]["title"].startswith("CI remediation")
    assert payload["remediation_loop"]["summary"].startswith("Remediation loop hazır")


def test_normalize_self_heal_plan_accepts_dict_and_max_operations() -> None:
    raw = {
        "operations": [
            {"action": "patch", "path": "a.py", "target": "x", "replacement": "y"},
            {"action": "patch", "path": "b.py", "target": "x", "replacement": "y"},
            {"action": "patch", "path": "c.py", "target": "x", "replacement": "y"},
            {"action": "patch", "path": "d.py", "target": "x", "replacement": "y"},
        ],
        "validation_commands": ["pytest -q"],
    }
    normalized = ci.normalize_self_heal_plan(
        raw,
        scope_paths=["a.py", "b.py", "c.py", "d.py"],
        fallback_validation_commands=[],
        max_operations=2,
    )
    assert len(normalized["operations"]) == 2


def test_extract_failed_job_names_uses_jobs_fallback_and_limit() -> None:
    data = {"jobs": [{"name": f"job{i}"} for i in range(8)]}
    names = ci._extract_failed_job_names(data)
    assert len(names) == 6
    assert names[0] == "job0"


def test_generic_ci_context_uses_defaults_and_truncates_logs() -> None:
    ctx = ci._generic_ci_context(
        "custom",
        {
            "pipeline_failed": True,
            "repository": "org/repo",
            "summary": "x" * 500,
            "details": "y" * 1500,
        },
    )
    assert ctx is not None
    assert ctx["repo"] == "org/repo"
    assert ctx["failure_summary"].endswith("…[truncated]")
    assert ctx["log_excerpt"].endswith("…[truncated]")


def test_build_ci_failure_context_workflow_default_base_branch() -> None:
    payload = {
        "repository": {"name": "repo", "default_branch": "trunk"},
        "workflow_run": {
            "status": "completed",
            "conclusion": "failure",
            "name": "ci",
            "pull_requests": [],
        },
    }
    ctx = ci.build_ci_failure_context("workflow_run", payload)
    assert ctx is not None
    assert ctx["base_branch"] == "trunk"


def test_build_ci_remediation_payload_uses_pr_root_cause_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _sample_context()

    def fake_pr(_ctx, _diag):
        return {
            "title": "t",
            "body": "b",
            "base_branch": "main",
            "head_branch_suggestion": "h",
            "root_cause_summary": "from-pr",
            "auto_create_ready": True,
        }

    monkeypatch.setattr(ci, "build_pr_proposal", fake_pr)
    payload = ci.build_ci_remediation_payload(context, "diag")
    assert payload["root_cause_summary"] == "from-pr"


def test_build_pr_proposal_uses_defaults_when_missing_fields() -> None:
    proposal = ci.build_pr_proposal({}, "")
    assert proposal["head_branch_suggestion"] == "ci-remediation/manual"
    assert proposal["base_branch"] == "main"


def test_extract_validation_commands_limits_to_five() -> None:
    context = {
        "failure_summary": "\n".join(
            ["pytest -q tests/a.py", "pytest -q tests/b.py", "pytest -q tests/c.py"]
        ),
        "log_excerpt": "\n".join(["python -m pytest", "bash run_tests.sh unit"]),
        "suspected_targets": [f"tests/t{i}.py" for i in range(10)],
    }
    commands = ci._extract_validation_commands(context, "pytest -q tests/d.py")
    assert len(commands) == 5


def test_build_self_heal_patch_prompt_skips_empty_snapshot_entries() -> None:
    snapshots = [
        {"path": "", "content": "x"},
        {"path": "tests/a.py", "content": ""},
        {"path": "tests/b.py", "content": "ok"},
    ]
    prompt = ci.build_self_heal_patch_prompt(
        _sample_context(), "d", {"scope_paths": [], "validation_commands": []}, snapshots
    )
    assert prompt.count("[FILE]") == 1


def test_normalize_self_heal_plan_strips_wrapping_and_handles_non_dict_operations() -> None:
    raw = '{"operations":["bad",{"action":"patch","path":"./tests/a.py","target":"x","replacement":"y"}]}'
    normalized = ci.normalize_self_heal_plan(
        raw, scope_paths=["tests/a.py"], fallback_validation_commands=[]
    )
    assert normalized["operations"][0]["path"] == "tests/a.py"


def test_build_root_cause_summary_with_turkish_prefix() -> None:
    summary = ci.build_root_cause_summary({}, "Kök neden: import hatası")
    assert summary.startswith("Kök neden")


def test_build_root_cause_summary_ignores_empty_first_line_and_falls_back() -> None:
    info = {"log_excerpt": "AssertionError: boom", "failure_summary": "failed"}

    class WeirdDiagnosis:
        def __str__(self) -> str:
            class WeirdStr(str):
                def strip(self, *args, **kwargs):  # type: ignore[override]
                    return self

                def splitlines(self, *args, **kwargs):  # type: ignore[override]
                    return ["   "]

            return WeirdStr("diagnosis")

    summary = ci.build_root_cause_summary(info, WeirdDiagnosis())
    assert "AssertionError" in summary


def test_build_remediation_loop_large_scope_triggers_hitl() -> None:
    context = {
        "suspected_targets": [f"tests/t{i}.py" for i in range(5)],
        "failed_jobs": ["j1", "j2", "j3", "j4", "j5", "j6", "j7"],
        "failure_summary": "minor",
        "log_excerpt": "",
    }
    result = ci.build_remediation_loop(context, "ok")
    assert result["needs_human_approval"] is True
    assert len(result["scope_paths"]) == 5
    assert len(result["failed_jobs"]) == 6


def test_ci_failure_prompt_handles_missing_optional_fields() -> None:
    prompt = ci.build_ci_failure_prompt({"repo": "org/repo"})
    assert "repo=org/repo" in prompt
    assert "failed_jobs=" in prompt


def test_json_roundtrip_smoke_for_plan_payload() -> None:
    plan = ci.normalize_self_heal_plan(
        {"summary": "s", "confidence": "low", "operations": [], "validation_commands": []},
        scope_paths=[],
        fallback_validation_commands=[],
    )
    assert json.loads(json.dumps(plan))["summary"] == "s"


def test_extract_validation_commands_skips_blank_lines() -> None:
    context = {
        "failure_summary": "\n\npytest -q tests/a.py",
        "log_excerpt": "   \npython -m pytest",
        "suspected_targets": [],
    }
    commands = ci._extract_validation_commands(context, "\n")
    assert "pytest -q tests/a.py" in commands
