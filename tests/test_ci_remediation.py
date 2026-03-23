import core.ci_remediation as ci_mod
from core.ci_remediation import (
    build_ci_remediation_payload,
    build_ci_failure_context,
    build_ci_failure_prompt,
    build_pr_proposal,
    build_remediation_loop,
    build_self_heal_patch_prompt,
    is_ci_failure_event,
    normalize_self_heal_plan,
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


def test_build_remediation_loop_requires_hitl_for_high_risk_timeout():
    context = {
        "failure_summary": "pytest timed out on tests/test_web_server_voice.py",
        "log_excerpt": "TimeoutError: tests/test_web_server_voice.py exceeded 120s",
        "suspected_targets": ["tests/test_web_server_voice.py", "web_server.py"],
        "failed_jobs": ["pytest"],
    }

    loop = build_remediation_loop(context, "TimeoutError: flaky websocket teardown causes long wait.")

    assert loop["status"] == "planned"
    assert loop["mode"] == "self_heal_with_hitl"
    assert loop["needs_human_approval"] is True
    assert loop["validation_commands"][0].startswith("pytest -q tests/test_web_server_voice.py")


def test_ci_remediation_payload_includes_remediation_loop():
    context = {
        "repo": "acme/sidar",
        "workflow_name": "CI",
        "run_id": "77",
        "failure_summary": "pytest failed on tests/test_reviewer_agent.py",
        "log_excerpt": "AssertionError: expected approve",
        "suspected_targets": ["tests/test_reviewer_agent.py"],
        "failed_jobs": ["pytest"],
        "base_branch": "main",
        "branch": "feature/remediate",
        "sha": "abc123",
        "html_url": "https://github.com/acme/sidar/actions/runs/77",
        "logs_url": "https://github.com/acme/sidar/actions/runs/77/logs",
    }

    remediation = build_ci_remediation_payload(context, "Kök neden pytest assertion drift.")

    assert remediation["remediation_loop"]["status"] == "planned"
    assert remediation["remediation_loop"]["validation_commands"][0] == "pytest -q tests/test_reviewer_agent.py"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "completed"


def test_ci_remediation_helper_fallbacks_cover_trim_skip_and_non_dict_jobs():
    long_text = "x" * 1300
    assert ci_mod._trim_text(long_text).endswith(" …[truncated]")

    root_cause = ci_mod._extract_root_cause_line("\n\n   \n", "  ", "AssertionError: boom")
    assert root_cause == "AssertionError: boom"

    jobs = ci_mod._extract_failed_job_names({"jobs": ["pytest", {"title": "lint"}, "pytest"]})
    assert jobs == ["pytest", "lint"]

    hints = ci_mod._build_diagnostic_hints("Build timeout", "ImportError: missing module", ["tests/test_ci_remediation.py"])
    assert any("Timeout" in hint for hint in hints)
    assert any("Import zinciri" in hint for hint in hints)


def test_check_suite_failure_context_and_event_detection_use_defaults():
    payload = {
        "repository": {"name": "sidar", "default_branch": "develop"},
        "check_suite": {
            "id": 88,
            "head_branch": "feature/check-suite",
            "head_sha": "cafebabe",
            "status": "completed",
            "conclusion": "timed_out",
            "app": {"name": "GitHub Actions"},
        },
    }

    assert is_ci_failure_event("check_suite", payload) is True

    context = build_ci_failure_context("check_suite", payload)

    assert context is not None
    assert context["kind"] == "check_suite"
    assert context["repo"] == "sidar"
    assert context["workflow_name"] == "feature/check-suite"
    assert context["base_branch"] == "develop"
    assert context["log_excerpt"] == "GitHub Actions"
    assert context["failure_summary"] == "timed_out"


def test_root_cause_summary_uses_inferred_line_when_first_sentence_is_not_root_cause(monkeypatch):
    monkeypatch.setattr(ci_mod, "_extract_root_cause_line", lambda *_args: "Inferred: flaky teardown")

    summary = ci_mod.build_root_cause_summary({}, "AssertionError: websocket timeout")

    assert summary == "Inferred: flaky teardown"


def test_root_cause_summary_infers_syntax_error_from_malformed_ci_log_payload():
    payload = {
        "event_name": "ci_pipeline_failed",
        "ci_failure": True,
        "repo": "acme/sidar",
        "workflow_name": "CI",
        "pipeline_id": 902,
        "branch": "main",
        "base_branch": "main",
        "failure_summary": "CI parser malformed output aldı",
        "log_excerpt": "@@ ??? malformed syntax payload <<<\nnot-json: [}\nSyntaxError: unexpected EOF while parsing",
        "failed_jobs": [{"name": "pytest"}],
    }

    context = build_ci_failure_context("ci_pipeline_failed", payload)
    summary = ci_mod.build_root_cause_summary(context or {}, "Parser çıktısı normalize edilemedi.")

    assert summary == "SyntaxError: unexpected EOF while parsing"


def test_root_cause_summary_falls_back_to_hint_and_validation_commands_skip_blanks():
    context = {
        "failure_summary": "",
        "root_cause_hint": "ImportError: core/db.py could not be imported",
        "suspected_targets": ["tests/test_ci_remediation.py"],
    }

    summary = ci_mod.build_root_cause_summary(context, "\n   \n")
    commands = ci_mod._extract_validation_commands(
        context,
        "\n\n   \npytest -q tests/test_ci_remediation.py\npython -m pytest tests/test_agent_core_contracts.py\n",
    )

    assert summary == "ImportError: core/db.py could not be imported"
    assert "pytest -q tests/test_ci_remediation.py" in commands
    assert "python -m pytest tests/test_agent_core_contracts.py" in commands


def test_self_heal_prompt_and_normalize_plan_filter_scope():
    context = {
        "repo": "acme/sidar",
        "workflow_name": "CI",
        "failure_summary": "AssertionError in app.py",
    }
    remediation_loop = {
        "scope_paths": ["app.py"],
        "validation_commands": ["pytest -q tests/test_app.py", "python -m pytest"],
    }
    prompt = build_self_heal_patch_prompt(
        context,
        "Kök neden: sabit değer drift oldu.",
        remediation_loop,
        [{"path": "app.py", "content": "VALUE = 1\n"}],
    )
    assert "[SELF_HEAL_PLAN]" in prompt
    assert "Yalnızca şu kapsam içindeki dosyaları değiştir: app.py" in prompt

    plan = normalize_self_heal_plan(
        {
            "summary": "Fix",
            "confidence": "medium",
            "operations": [
                {"action": "patch", "path": "app.py", "target": "VALUE = 1", "replacement": "VALUE = 2"},
                {"action": "patch", "path": "../secrets.py", "target": "A", "replacement": "B"},
                {"action": "write", "path": "app.py", "content": "VALUE = 3"},
            ],
            "validation_commands": ["pytest -q tests/test_app.py", "rm -rf /"],
        },
        scope_paths=["app.py"],
        fallback_validation_commands=["python -m pytest"],
    )

    assert plan["operations"] == [
        {"action": "patch", "path": "app.py", "target": "VALUE = 1", "replacement": "VALUE = 2"}
    ]
    assert plan["validation_commands"] == ["pytest -q tests/test_app.py", "python -m pytest"]


def test_normalize_self_heal_plan_rejects_shell_chaining_in_validation_commands():
    plan = normalize_self_heal_plan(
        {
            "operations": [
                {"action": "patch", "path": "app.py", "target": "VALUE = 1", "replacement": "VALUE = 2"}
            ],
            "validation_commands": [
                "pytest -q tests/test_app.py && echo hacked",
                "python -m pytest; rm -rf /",
                "bash run_tests.sh smoke",
            ],
        },
        scope_paths=["app.py"],
        fallback_validation_commands=[],
    )

    assert plan["validation_commands"] == ["bash run_tests.sh smoke"]
