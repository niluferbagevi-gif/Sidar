from __future__ import annotations

import json
from types import SimpleNamespace

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


def test_build_ruff_autofix_command_defaults_to_safe_fix_only() -> None:
    command = ci.build_ruff_autofix_command()

    assert command == "uv run ruff check --fix ."
    assert "--unsafe-fixes" not in command


def test_build_ruff_autofix_command_limits_unsafe_fixes_to_selectors() -> None:
    command = ci.build_ruff_autofix_command(unsafe_fixes=True, unsafe_selectors="I,UP034 bad;rm")

    assert command == "uv run ruff check --fix --unsafe-fixes --select I,UP034 ."


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ([], "uv run ruff check --fix ."),
        (["tests/unit/x.py"], "uv run ruff check --fix tests/unit/x.py"),
        (
            ["tests/unit/x.py", "core/y.py", "not_python.txt"],
            "uv run ruff check --fix tests/unit/x.py core/y.py",
        ),
        (["../outside.py", "/abs/path.py"], "uv run ruff check --fix ."),
        (["tests/unit/x.py", "tests/unit/x.py"], "uv run ruff check --fix tests/unit/x.py"),
        (["./tests/unit/x.py"], "uv run ruff check --fix tests/unit/x.py"),
    ],
)
def test_build_scoped_ruff_autofix_command(paths: list[str], expected: str) -> None:
    assert ci.build_scoped_ruff_autofix_command(paths) == expected


def test_is_allowed_validation_command_rejects_unbounded_ruff_unsafe_fixes() -> None:
    assert ci._is_allowed_validation_command("uv run ruff check --fix .") is True
    assert ci._is_allowed_validation_command("uv run ruff check --fix --unsafe-fixes .") is False
    assert (
        ci._is_allowed_validation_command(
            "uv run ruff check --fix --unsafe-fixes --select I,UP "
            "tests/unit/core/test_ci_remediation.py"
        )
        is True
    )
    assert (
        ci._is_allowed_validation_command(
            "uv run ruff check --fix --unsafe-fixes --select B "
            "tests/unit/core/test_ci_remediation.py"
        )
        is False
    )


def test_is_allowed_validation_command_uses_default_when_ruff_unsafe_allowlist_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "RUFF_AUTOFIX_UNSAFE_RULES", "")

    assert (
        ci._is_allowed_validation_command(
            "uv run ruff check --fix --unsafe-fixes --select I "
            "tests/unit/core/test_ci_remediation.py"
        )
        is True
    )


def test_is_allowed_validation_command_supports_explicit_ruff_unsafe_allowlist_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "RUFF_AUTOFIX_UNSAFE_RULES", "")
    monkeypatch.setattr(ci.Config, "RUFF_AUTOFIX_UNSAFE_RULES_DISABLE", True, raising=False)

    assert (
        ci._is_allowed_validation_command(
            "uv run ruff check --fix --unsafe-fixes --select I "
            "tests/unit/core/test_ci_remediation.py"
        )
        is False
    )


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
    assert ctx["trigger_origin"] == "external_ci_event"
    assert ctx["human_approval_required"] is True


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
    assert ctx["human_approval_required"] is True


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
    assert "tests/conftest.py" in prompt
    assert "fake_llm_response" in prompt
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


def test_normalize_self_heal_plan_drops_patches_when_scope_paths_is_empty() -> None:
    """Fail-closed regression test: an empty scope must reject every patch operation.

    Not silently accept unrestricted file paths. Mirrors the fail-open bug fixed in
    ``agent/self_heal/executor.py`` where ``allowed_paths and path not in allowed_paths``
    short-circuited to False (and thus skipped the check) whenever scope_paths was empty.
    """
    normalized = ci.normalize_self_heal_plan(
        {
            "operations": [
                {"action": "patch", "path": "anywhere.py", "target": "old", "replacement": "new"}
            ],
        },
        scope_paths=[],
        fallback_validation_commands=[],
    )
    assert normalized["operations"] == []


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


def test_normalize_self_heal_plan_accepts_operation_aliases() -> None:
    normalized = ci.normalize_self_heal_plan(
        {
            "patches": [
                {
                    "op": "patch",
                    "file": "tests/unit/core/test_ci_remediation.py",
                    "before": "a",
                    "after": "b",
                }
            ]
        },
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=[],
    )
    assert normalized["operations"] == [
        {
            "action": "patch",
            "path": "tests/unit/core/test_ci_remediation.py",
            "target": "a",
            "replacement": "b",
        }
    ]


def test_normalize_self_heal_plan_parses_python_list_like_response() -> None:
    raw = (
        "PLAN:\\n"
        "[{'op': 'patch', 'file': 'tests/unit/core/test_ci_remediation.py', "
        "'before': 'x', 'after': 'y'}]"
    )
    normalized = ci.normalize_self_heal_plan(
        raw,
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=[],
    )
    assert normalized["operations"] == [
        {
            "action": "patch",
            "path": "tests/unit/core/test_ci_remediation.py",
            "target": "x",
            "replacement": "y",
        }
    ]


def test_normalize_self_heal_plan_handles_literal_eval_syntax_error_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.ast, "literal_eval", lambda _value: (_ for _ in ()).throw(SyntaxError()))
    raw = (
        "PLAN:\\n"
        "[{'op': 'patch', 'file': 'tests/unit/core/test_ci_remediation.py', "
        "'before': 'x', 'after': 'y'}]"
    )
    normalized = ci.normalize_self_heal_plan(
        raw,
        scope_paths=["tests/unit/core/test_ci_remediation.py"],
        fallback_validation_commands=["pytest -q"],
    )
    assert normalized["operations"] == []
    assert normalized["validation_commands"] == ["pytest -q"]


def test_normalize_self_heal_plan_accepts_uv_pip_install_for_bootstrap() -> None:
    normalized = ci.normalize_self_heal_plan(
        {"operations": [], "validation_commands": ["uv pip install psycopg2-binary"]},
        scope_paths=[],
        fallback_validation_commands=[],
    )
    assert normalized["validation_commands"] == ["uv pip install psycopg2-binary"]


def test_normalize_self_heal_plan_accepts_single_operation_shapes() -> None:
    dict_operations = ci.normalize_self_heal_plan(
        {
            "operations": {
                "action": "patch",
                "path": "core/a.py",
                "target": "old",
                "replacement": "new",
            }
        },
        scope_paths=["core/a.py"],
        fallback_validation_commands=[],
    )
    assert dict_operations["operations"] == [
        {"action": "patch", "path": "core/a.py", "target": "old", "replacement": "new"}
    ]

    operation_alias = ci.normalize_self_heal_plan(
        {
            "operation": {
                "action": "patch",
                "path": "core/b.py",
                "target": "before",
                "replacement": "after",
            }
        },
        scope_paths=["core/b.py"],
        fallback_validation_commands=[],
    )
    assert operation_alias["operations"][0]["path"] == "core/b.py"


def test_normalize_self_heal_plan_treats_patch_like_payload_as_operation() -> None:
    normalized = ci.normalize_self_heal_plan(
        {
            "path": "core/c.py",
            "target": "left",
            "replacement": "right",
        },
        scope_paths=["core/c.py"],
        fallback_validation_commands=[],
    )

    assert normalized["operations"] == [
        {"action": "patch", "path": "core/c.py", "target": "left", "replacement": "right"}
    ]


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


def test_external_ci_payload_cannot_avoid_hitl_by_choosing_benign_text() -> None:
    context = ci.build_ci_failure_context(
        "workflow_run",
        {
            "repository": {"full_name": "org/repo", "default_branch": "main"},
            "workflow_run": {
                "status": "completed",
                "conclusion": "failure",
                "name": "routine-check",
                "display_title": "routine maintenance",
                "id": 42,
                "head_sha": "abc123",
            },
        },
    )

    assert context is not None
    remediation = ci.build_remediation_loop(context, "ordinary failure")

    assert remediation["needs_human_approval"] is True
    assert "external_ci_event" in remediation["hitl_reasons"]
    assert remediation["mode"] == "self_heal_with_hitl"


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
    raw = (
        '{"operations":["bad",{"action":"patch","path":"./tests/a.py","target":"x",'
        '"replacement":"y"}]}'
    )
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
    assert result["mode"] == "self_heal_with_hitl_batched"
    assert result["operator_guidance"]
    assert any(
        str(reason).startswith("scope_exceeds_threshold") for reason in result["hitl_reasons"]
    )
    assert result["hitl_policy"]["scope_threshold"] == 3
    assert result["autonomous_batches"]
    assert len(result["scope_paths"]) == 5
    assert len(result["failed_jobs"]) == 6


def test_build_remediation_loop_syntax_error_requires_hitl() -> None:
    context = {
        "suspected_targets": ["core/broken.py"],
        "failed_jobs": ["tests"],
        "failure_summary": "SyntaxError: invalid syntax",
        "log_excerpt": "",
    }

    result = ci.build_remediation_loop(context, "SyntaxError: invalid syntax")

    assert result["needs_human_approval"] is True
    assert "syntax_error" in result["hitl_reasons"]
    assert "--hitl-approve yes/no" in result["operator_guidance"]


def test_build_remediation_loop_large_scope_respects_env_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "SELF_HEAL_HITL_SCOPE_THRESHOLD", 3)
    context = {
        "suspected_targets": [f"tests/t{i}.py" for i in range(4)],
        "failed_jobs": ["j1"],
        "failure_summary": "minor",
        "log_excerpt": "",
    }
    result = ci.build_remediation_loop(context, "ok")
    assert result["needs_human_approval"] is True


def test_build_remediation_loop_reports_safe_ruff_autofix_policy() -> None:
    context = {
        "suspected_targets": ["core/ci_remediation.py"],
        "failed_jobs": ["lint"],
        "failure_summary": "ruff check failed",
        "log_excerpt": "uv run ruff check .",
    }

    result = ci.build_remediation_loop(context, "ruff lint failure")

    assert result["autofix_commands"] == ["uv run ruff check --fix core/ci_remediation.py"]
    assert result["unsafe_autofix_policy"]["unsafe_fixes_default"] is False
    assert result["unsafe_autofix_policy"]["allowed_unsafe_selectors"] == ["I", "UP"]
    assert "--unsafe-fixes" in result["unsafe_autofix_policy"]["guidance"]


def test_build_remediation_loop_ignores_unknown_auto_install_modules() -> None:
    context = {
        "suspected_targets": ["core/unknown.py"],
        "failed_jobs": [],
        "failure_summary": "ModuleNotFoundError: No module named 'totally_unknown_pkg'",
        "log_excerpt": 'Library stubs not installed for "unknownlib"  [import-untyped]',
    }

    result = ci.build_remediation_loop(
        context,
        "Cannot find implementation or library stub for module named 'unknownlib'",
    )

    assert result["bootstrap_commands"] == []
    assert all("totally_unknown_pkg" not in cmd for cmd in result["validation_commands"])
    assert all("unknownlib" not in cmd for cmd in result["validation_commands"])


def test_build_remediation_loop_adds_bootstrap_commands_for_missing_modules() -> None:
    context = {
        "suspected_targets": ["core/rag.py"],
        "failed_jobs": [],
        "failure_summary": "pgvector başlatma hatası: No module named 'psycopg2'",
        "log_excerpt": "",
    }
    result = ci.build_remediation_loop(context, "ModuleNotFoundError: No module named 'psycopg2'")
    assert "uv pip install psycopg2-binary" in result["bootstrap_commands"]
    assert "uv pip install psycopg2-binary" in result["validation_commands"]


def test_build_remediation_loop_adds_stub_install_for_import_untyped() -> None:
    context = {
        "suspected_targets": ["core/system_health.py"],
        "failed_jobs": [],
        "failure_summary": 'error: Library stubs not installed for "psutil"  [import-untyped]',
        "log_excerpt": 'Hint: "python3 -m pip install types-psutil"',
    }
    result = ci.build_remediation_loop(context, 'Library stubs not installed for "psutil"')
    assert "uv pip install types-psutil" in result["bootstrap_commands"]
    assert "uv pip install types-psutil" in result["validation_commands"]


def test_build_remediation_loop_adds_stub_install_from_hint_only() -> None:
    context = {
        "suspected_targets": ["core/a.py"],
        "failed_jobs": [],
        "failure_summary": "mypy import-untyped failures",
        "log_excerpt": "Hint: pip install types-requests",
    }
    result = ci.build_remediation_loop(context, "import-untyped")
    assert "uv pip install types-requests" in result["bootstrap_commands"]


def test_build_remediation_loop_batches_follow_configured_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 2)
    context = {
        "suspected_targets": [f"core/t{i}.py" for i in range(5)],
        "failed_jobs": [],
        "failure_summary": "",
        "log_excerpt": "",
    }
    result = ci.build_remediation_loop(context, "mypy failures")
    assert [len(item["scope_paths"]) for item in result["autonomous_batches"]] == [2, 2, 1]
    assert result["autonomous_batches"][0]["module_hint"] == "core"


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


def test_build_local_failure_context_parses_mypy_log() -> None:
    log_text = "\n".join(
        [
            "core/service.py:10: error: Incompatible types in assignment [assignment]",
            "agent/auto_handle.py:88: error: Function is missing a type annotation "
            "[no-untyped-def]",
        ]
    )
    ctx = ci.build_local_failure_context(log_text, source="mypy", log_path="artifacts/mypy.log")
    assert ctx["kind"] == "local_failure"
    assert ctx["workflow_name"] == "local_mypy"
    assert ctx["logs_url"] == "artifacts/mypy.log"
    assert "core/service.py" in ctx["suspected_targets"]
    assert "agent/auto_handle.py" in ctx["suspected_targets"]
    assert ctx["failed_jobs"] == ["local:mypy"]


def test_build_local_failure_context_fallbacks_when_log_has_no_structured_error() -> None:
    ctx = ci.build_local_failure_context("mypy: failed with unknown issue", source="mypy")
    assert ctx["root_cause_hint"]
    assert ctx["failure_summary"].startswith("mypy yerel kalite kapısında hata bulundu")


def test_build_local_failure_context_respects_local_scope_limit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "SELF_HEAL_LOCAL_SCOPE_LIMIT", 3)
    log_text = "\n".join(
        [
            "core/a.py:1: error: err [assignment]",
            "core/b.py:2: error: err [assignment]",
            "core/c.py:3: error: err [assignment]",
            "core/d.py:4: error: err [assignment]",
        ]
    )
    ctx = ci.build_local_failure_context(log_text, source="mypy")
    assert ctx["suspected_targets"] == ["core/a.py", "core/b.py", "core/c.py"]


def test_build_local_failure_context_parses_pytest_assertion_and_attribute_targets() -> None:
    log_text = """
    FAILED tests/unit/core/test_doctor.py::test_doctor_status - AssertionError: expected healthy
    tests/unit/root/test_cli.py:42: AttributeError: 'Namespace' object has no attribute 'doctor'
    core/doctor.py:88: in run_check
    E   AttributeError: 'Doctor' object has no attribute 'status'
    """

    ctx = ci.build_local_failure_context(log_text, source="pytest", log_path="artifacts/pytest.log")

    assert ctx["workflow_name"] == "local_pytest"
    assert ctx["conclusion"] == "failure"
    assert "tests/unit/core/test_doctor.py" in ctx["suspected_targets"]
    assert "tests/unit/root/test_cli.py" in ctx["suspected_targets"]
    assert "core/doctor.py" in ctx["suspected_targets"]
    assert "AttributeError" in ctx["root_cause_hint"] or "AssertionError" in ctx["root_cause_hint"]
    assert any("attribute" in hint.lower() for hint in ctx["diagnostic_hints"])


def test_extract_validation_commands_targets_pytest_failure_files() -> None:
    context = ci.build_local_failure_context(
        "FAILED tests/unit/core/test_doctor.py::test_x - AssertionError: drift",
        source="pytest",
    )

    commands = ci._extract_validation_commands(context, "")

    assert "pytest -q tests/unit/core/test_doctor.py" in commands


def test_summarize_mypy_log_returns_structured_signal() -> None:
    log_text = "\n".join(
        [
            "core/service.py:10: error: Incompatible types in assignment [assignment]",
            "core/service.py:11: error: Returning Any from function declared to return int "
            "[no-any-return]",
            "agent/auto_handle.py:88: error: Function is missing a type annotation "
            "[no-untyped-def]",
        ]
    )
    summary = ci._summarize_mypy_log(log_text, max_lines=5)
    assert summary["total_errors"] == 3
    assert "core/service.py" in summary["top_paths"]
    assert "assignment" in summary["error_codes"]
    assert summary["sample_lines"]


def test_summarize_mypy_log_skips_noise_and_honors_max_lines() -> None:
    log_text = "\n".join(
        [
            "",
            "not-a-mypy-line",
            "core/a.py:1: error: bad assign [assignment]",
            "core/a.py:2: error: bad return [return-value]",
            "core/b.py:3: error: missing anno [no-untyped-def]",
        ]
    )
    summary = ci._summarize_mypy_log(log_text, max_lines=1)

    assert summary["total_errors"] == 3
    assert len(summary["sample_lines"]) == 1
    assert summary["sample_lines"][0].startswith("core/a.py:1:")


def test_summarize_mypy_log_caps_per_file_samples_after_three_entries() -> None:
    log_text = "\n".join(
        f"core/repeated.py:{line}: error: issue {line} [assignment]" for line in range(1, 5)
    )

    summary = ci._summarize_mypy_log(log_text, max_lines=10)

    assert summary["total_errors"] == 4
    assert len(summary["sample_lines"]) == 3
    assert all(line.startswith("core/repeated.py:") for line in summary["sample_lines"])


@pytest.mark.parametrize(
    ("log_line", "expected_codes"),
    [
        ("core/no_code.py:4: error: message without code", []),
        ("core/has_code.py:5: error: message with code [assignment]", ["assignment"]),
    ],
)
def test_summarize_mypy_log_handles_optional_error_code(
    log_line: str,
    expected_codes: list[str],
) -> None:
    summary = ci._summarize_mypy_log(log_line, max_lines=5)

    assert summary["total_errors"] == 1
    assert summary["error_codes"] == expected_codes


def test_build_local_failure_context_ignores_blank_lines_and_collects_root_cause() -> None:
    log_text = "\n".join(
        [
            "",
            "   ",
            "Root cause: mypy found incompatible assignment in module.",
            "",
            "core/sample.py:9: error: Incompatible types in assignment [assignment]",
        ]
    )
    ctx = ci.build_local_failure_context(log_text, source="mypy")

    assert ctx["suspected_targets"] == ["core/sample.py"]
    assert "Root cause:" in ctx["root_cause_hint"]
    assert "(1 kayıt, 1 dosya)" in ctx["failure_summary"]


def test_build_local_failure_context_keeps_first_root_cause_hint() -> None:
    log_text = "\n".join(
        [
            "ValueError: first actionable failure",
            "TypeError: second actionable failure",
        ]
    )

    ctx = ci.build_local_failure_context(log_text, source="ruff")

    assert ctx["root_cause_hint"] == "ValueError: first actionable failure"
    assert ctx["conclusion"] == "failure"
    assert ctx["suspected_targets"] == []


def test_build_local_failure_context_deduplicates_suspected_targets() -> None:
    log_text = "\n".join(
        [
            "core/dup.py:9: error: first issue [assignment]",
            "core/dup.py:10: error: second issue [return-value]",
        ]
    )

    ctx = ci.build_local_failure_context(log_text, source="mypy")

    assert ctx["suspected_targets"] == ["core/dup.py"]
    assert "(2 kayıt, 1 dosya)" in ctx["failure_summary"]


def test_build_self_heal_patch_prompt_includes_mypy_summary() -> None:
    context = {
        "workflow_name": "local_mypy",
        "failure_summary": "mypy failures",
        "log_excerpt": "core/a.py:9: error: Incompatible types in assignment [assignment]",
    }
    prompt = ci.build_self_heal_patch_prompt(
        context,
        "Type mismatch",
        {"scope_paths": ["core/a.py"], "validation_commands": ["pytest -q tests/unit/core"]},
        [{"path": "core/a.py", "content": "value: int = 'x'"}],
    )
    assert "mypy_mode=true" in prompt
    assert "mypy_error_total=1" in prompt
    assert "[MYPY_SAMPLE_LINES]" in prompt


def test_normalize_ruff_rule_selectors_none_is_empty() -> None:
    assert ci._normalize_ruff_rule_selectors(None) == []


def test_configured_ruff_unsafe_selectors_normalizes_explicit_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci.Config, "RUFF_AUTOFIX_UNSAFE_RULES", " i, up034 ")

    assert ci._configured_ruff_unsafe_selectors() == ["I", "UP034"]


def test_build_ruff_autofix_command_replaces_unsafe_target() -> None:
    assert ci.build_ruff_autofix_command(target="../outside") == "uv run ruff check --fix ."


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (["uv", "run", "ruff", "check"], True),
        (["uv", "run", "ruff", "check", "--select"], False),
        (["uv", "run", "ruff", "check", "--select=I", "."], True),
        (["uv", "run", "ruff", "check", "--unknown"], False),
        (["uv", "run", "ruff", "check", "outside"], False),
        (["uv", "run", "ruff", "check", "--unsafe-fixes", "."], False),
    ],
)
def test_is_allowed_ruff_command_edge_cases(parts: list[str], expected: bool) -> None:
    assert ci._is_allowed_ruff_command(parts) is expected


@pytest.mark.parametrize(
    ("module_name", "expected"),
    [
        ("", None),
        ("core", "core.py"),
        ("core.ci_remediation", "core/ci_remediation.py"),
        ("third_party.package", None),
    ],
)
def test_resolve_module_to_repo_path(module_name: str, expected: str | None) -> None:
    assert ci._resolve_module_to_repo_path(module_name) == expected


def test_collect_cross_file_context_paths_handles_non_python_missing_and_syntax_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    assert ci._collect_cross_file_context_paths("docs/readme.md") == []
    assert ci._collect_cross_file_context_paths("core/missing.py") == []
    assert ci._collect_cross_file_context_paths("core/broken.py") == []


def test_collect_cross_file_context_paths_discovers_imports_and_skips_empty_relative_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "sample.py").write_text(
        "import core.alpha\nimport core.alpha\nfrom core import beta\nfrom . import sibling\n",
        encoding="utf-8",
    )

    assert ci._collect_cross_file_context_paths("core/sample.py") == ["core/alpha.py", "core.py"]


def test_build_local_failure_context_adds_mypy_path_outside_target_pattern() -> None:
    context = ci.build_local_failure_context(
        "pkg/service.py:7: error: Incompatible types in assignment [assignment]",
        source="mypy",
    )

    assert context["suspected_targets"] == ["pkg/service.py"]


@pytest.mark.parametrize(
    ("diagnosis", "expected_reason"),
    [
        ("pytest-timeout operation timed out", "timeout_or_flaky_runtime"),
        ("TypeError: invalid runtime value", "runtime_type_or_value_error"),
    ],
)
def test_build_remediation_loop_classifies_additional_hitl_signals(
    diagnosis: str,
    expected_reason: str,
) -> None:
    context = {"suspected_targets": [], "failed_jobs": [], "failure_summary": "", "log_excerpt": ""}

    result = ci.build_remediation_loop(context, diagnosis)

    assert expected_reason in result["hitl_reasons"]


def test_build_remediation_loop_uses_high_risk_fallback_when_specific_timeout_probe_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci, "_TIMEOUT_RUNTIME_PATTERN", SimpleNamespace(search=lambda _text: None))
    context = {"suspected_targets": [], "failed_jobs": [], "failure_summary": "", "log_excerpt": ""}

    result = ci.build_remediation_loop(context, "timeout marker")

    assert "high_risk_failure_signal" in result["hitl_reasons"]


def test_normalize_ruff_rule_selectors_deduplicates_values() -> None:
    assert ci._normalize_ruff_rule_selectors("I, i, UP") == ["I", "UP"]


def test_build_ruff_autofix_command_ignores_invalid_unsafe_selectors() -> None:
    assert ci.build_ruff_autofix_command(unsafe_fixes=True, unsafe_selectors="bad;rm") == (
        "uv run ruff check --fix ."
    )


def test_build_local_failure_context_uses_root_cause_hint_as_actionable_signal() -> None:
    context = ci.build_local_failure_context("mypy error summary", source="mypy")

    assert context["conclusion"] == "failure"
    assert context["root_cause_hint"] == "mypy error summary"


def test_build_local_failure_context_deduplicates_cross_file_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci, "_collect_cross_file_context_paths", lambda _path: ["core/shared.py"])
    context = ci.build_local_failure_context(
        "core/a.py:1: error: first [assignment]\ncore/b.py:2: error: second [assignment]",
        source="mypy",
    )

    assert context["suspected_targets"] == ["core/a.py", "core/b.py", "core/shared.py"]
