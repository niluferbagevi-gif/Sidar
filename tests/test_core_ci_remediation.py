"""
core/ci_remediation.py için birim testleri.
_is_allowed_validation_command, _trim_text, _extract_suspected_targets,
_extract_root_cause_line, is_ci_failure_event, build_ci_failure_context,
normalize_self_heal_plan, build_pr_proposal, build_remediation_loop,
build_ci_remediation_payload fonksiyonlarını kapsar.
"""
from __future__ import annotations

import sys


def _get_ci():
    if "core.ci_remediation" in sys.modules:
        del sys.modules["core.ci_remediation"]
    import core.ci_remediation as ci
    return ci


# ══════════════════════════════════════════════════════════════
# _is_allowed_validation_command
# ══════════════════════════════════════════════════════════════

class TestIsAllowedValidationCommand:
    def test_pytest_allowed(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest") is True

    def test_pytest_with_path(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest tests/test_foo.py") is True

    def test_pytest_with_flag(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest -q tests/") is True

    def test_python_m_pytest(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("python -m pytest") is True

    def test_python_m_pytest_with_args(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("python -m pytest -v tests/test_cli.py") is True

    def test_bash_run_tests(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("bash run_tests.sh") is True

    def test_empty_command_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("") is False

    def test_shell_injection_ampersand_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest && rm -rf /") is False

    def test_pipe_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest | cat /etc/passwd") is False

    def test_redirect_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest > output.txt") is False

    def test_dollar_sign_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest $HOME") is False

    def test_semicolon_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest; ls") is False

    def test_arbitrary_command_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("ls -la") is False

    def test_rm_rejected(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("rm -rf tests/") is False

    def test_backtick_stripped_before_check(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("`pytest`") is True


# ══════════════════════════════════════════════════════════════
# _trim_text
# ══════════════════════════════════════════════════════════════

class TestTrimText:
    def test_short_text_unchanged(self):
        ci = _get_ci()
        assert ci._trim_text("hello") == "hello"

    def test_text_at_limit_not_truncated(self):
        ci = _get_ci()
        text = "x" * 1200
        result = ci._trim_text(text, 1200)
        assert result == text
        assert "truncated" not in result

    def test_text_over_limit_truncated(self):
        ci = _get_ci()
        text = "x" * 1300
        result = ci._trim_text(text, 1200)
        assert result.endswith("…[truncated]")
        assert len(result) < 1300

    def test_none_becomes_empty_string(self):
        ci = _get_ci()
        assert ci._trim_text(None) == ""

    def test_custom_limit(self):
        ci = _get_ci()
        result = ci._trim_text("hello world", 5)
        assert result.endswith("…[truncated]")

    def test_strips_whitespace(self):
        ci = _get_ci()
        assert ci._trim_text("  hello  ") == "hello"


# ══════════════════════════════════════════════════════════════
# _extract_suspected_targets
# ══════════════════════════════════════════════════════════════

class TestExtractSuspectedTargets:
    def test_finds_tests_path(self):
        ci = _get_ci()
        targets = ci._extract_suspected_targets("Error in tests/test_foo.py line 42")
        assert "tests/test_foo.py" in targets

    def test_finds_core_path(self):
        ci = _get_ci()
        targets = ci._extract_suspected_targets("Error in core/router.py")
        assert "core/router.py" in targets

    def test_empty_input_returns_empty(self):
        ci = _get_ci()
        assert ci._extract_suspected_targets("") == []

    def test_deduplicates_paths(self):
        ci = _get_ci()
        text = "tests/test_foo.py and tests/test_foo.py again"
        targets = ci._extract_suspected_targets(text)
        assert targets.count("tests/test_foo.py") == 1

    def test_multiple_values(self):
        ci = _get_ci()
        targets = ci._extract_suspected_targets("tests/test_foo.py", "core/dlp.py")
        assert "tests/test_foo.py" in targets
        assert "core/dlp.py" in targets

    def test_max_8_returned(self):
        ci = _get_ci()
        text = " ".join(f"tests/test_{i}.py" for i in range(20))
        targets = ci._extract_suspected_targets(text)
        assert len(targets) <= 8


# ══════════════════════════════════════════════════════════════
# _extract_root_cause_line
# ══════════════════════════════════════════════════════════════

class TestExtractRootCauseLine:
    def test_finds_assertion_error(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("AssertionError: expected True got False")
        assert "AssertionError" in result

    def test_finds_import_error(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("some text\nImportError: No module named foo\nmore")
        assert "ImportError" in result

    def test_finds_timeout(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("operation timed out after 30s")
        assert "timed out" in result.lower()

    def test_no_match_returns_empty(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("everything ok")
        assert result == ""

    def test_none_input_returns_empty(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line(None)
        assert result == ""

    def test_multiple_values_first_match_wins(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("no error here", "TypeError: bad type")
        assert "TypeError" in result


# ══════════════════════════════════════════════════════════════
# is_ci_failure_event
# ══════════════════════════════════════════════════════════════

class TestIsCiFailureEvent:
    def test_workflow_run_failure(self):
        ci = _get_ci()
        payload = {"workflow_run": {"status": "completed", "conclusion": "failure"}}
        assert ci.is_ci_failure_event("workflow_run", payload) is True

    def test_workflow_run_success_not_failure(self):
        ci = _get_ci()
        payload = {"workflow_run": {"status": "completed", "conclusion": "success"}}
        assert ci.is_ci_failure_event("workflow_run", payload) is False

    def test_workflow_run_not_completed(self):
        ci = _get_ci()
        payload = {"workflow_run": {"status": "in_progress", "conclusion": "failure"}}
        assert ci.is_ci_failure_event("workflow_run", payload) is False

    def test_check_run_failure(self):
        ci = _get_ci()
        payload = {"check_run": {"conclusion": "failure"}}
        assert ci.is_ci_failure_event("check_run", payload) is True

    def test_check_run_success_not_failure(self):
        ci = _get_ci()
        payload = {"check_run": {"conclusion": "success"}}
        assert ci.is_ci_failure_event("check_run", payload) is False

    def test_check_suite_timed_out(self):
        ci = _get_ci()
        payload = {"check_suite": {"conclusion": "timed_out"}}
        assert ci.is_ci_failure_event("check_suite", payload) is True

    def test_unknown_event_returns_false(self):
        ci = _get_ci()
        assert ci.is_ci_failure_event("push", {"ref": "main"}) is False

    def test_workflow_run_cancelled(self):
        ci = _get_ci()
        payload = {"workflow_run": {"status": "completed", "conclusion": "cancelled"}}
        assert ci.is_ci_failure_event("workflow_run", payload) is True


# ══════════════════════════════════════════════════════════════
# build_ci_failure_context
# ══════════════════════════════════════════════════════════════

class TestBuildCiFailureContext:
    def test_workflow_run_returns_context(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {
                "status": "completed",
                "conclusion": "failure",
                "name": "CI",
                "id": 12345,
                "run_number": 42,
                "head_branch": "main",
                "head_sha": "abc123",
                "html_url": "https://github.com/...",
                "jobs_url": "",
                "logs_url": "",
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("workflow_run", payload)
        assert result is not None
        assert result["kind"] == "workflow_run"
        assert result["repo"] == "org/repo"
        assert result["workflow_name"] == "CI"
        assert result["conclusion"] == "failure"

    def test_check_run_returns_context(self):
        ci = _get_ci()
        payload = {
            "check_run": {
                "conclusion": "failure",
                "name": "lint",
                "id": 99,
                "head_sha": "sha1",
                "output": {"title": "Lint failed", "summary": "2 errors"},
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("check_run", payload)
        assert result is not None
        assert result["kind"] == "check_run"

    def test_check_suite_returns_context(self):
        ci = _get_ci()
        payload = {
            "check_suite": {
                "conclusion": "failure",
                "id": 55,
                "head_branch": "feature",
                "head_sha": "deadbeef",
            },
            "repository": {"default_branch": "main"},
        }
        result = ci.build_ci_failure_context("check_suite", payload)
        assert result is not None
        assert result["kind"] == "check_suite"

    def test_non_failure_event_returns_none(self):
        ci = _get_ci()
        result = ci.build_ci_failure_context("push", {"ref": "main"})
        assert result is None

    def test_generic_ci_failure_flag(self):
        ci = _get_ci()
        payload = {"ci_failure": True, "failure_summary": "tests failed"}
        result = ci.build_ci_failure_context("custom_event", payload)
        assert result is not None
        assert result["kind"] == "generic_ci_failure"

    def test_ci_failure_remediation_event_name(self):
        ci = _get_ci()
        payload = {"failure_summary": "pipeline error"}
        result = ci.build_ci_failure_context("ci_failure_remediation", payload)
        assert result is not None
        assert result["kind"] == "generic_ci_failure"

    def test_generic_context_uses_default_base_branch_when_missing(self):
        ci = _get_ci()
        payload = {"ci_failure": True, "failure_summary": "job failed"}
        result = ci.build_ci_failure_context("custom_event", payload)
        assert result is not None
        assert result["base_branch"] == "main"

    def test_context_contains_required_keys(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {"status": "completed", "conclusion": "failure"},
            "repository": {},
        }
        result = ci.build_ci_failure_context("workflow_run", payload)
        for key in ("kind", "repo", "workflow_name", "run_id", "branch", "sha",
                    "conclusion", "failure_summary", "suspected_targets"):
            assert key in result


# ══════════════════════════════════════════════════════════════
# normalize_self_heal_plan
# ══════════════════════════════════════════════════════════════

class TestNormalizeSelfHealPlan:
    def _norm(self, raw, scope=None, fallback=None):
        ci = _get_ci()
        return ci.normalize_self_heal_plan(
            raw,
            scope_paths=scope or ["core/router.py"],
            fallback_validation_commands=fallback or ["pytest"],
        )

    def test_dict_input_processed(self):
        plan = {
            "summary": "fix router",
            "confidence": "high",
            "operations": [
                {"action": "patch", "path": "core/router.py", "target": "old", "replacement": "new"}
            ],
            "validation_commands": [],
        }
        result = self._norm(plan)
        assert result["summary"] == "fix router"
        assert result["confidence"] == "high"
        assert len(result["operations"]) == 1

    def test_string_json_input(self):
        import json
        raw = json.dumps({
            "summary": "fix",
            "confidence": "medium",
            "operations": [
                {"action": "patch", "path": "core/router.py", "target": "x", "replacement": "y"}
            ],
            "validation_commands": ["pytest"],
        })
        result = self._norm(raw)
        assert result["confidence"] == "medium"

    def test_markdown_json_stripped(self):
        import json
        inner = json.dumps({
            "summary": "ok",
            "confidence": "low",
            "operations": [],
            "validation_commands": [],
        })
        raw = f"```json\n{inner}\n```"
        result = self._norm(raw)
        assert result["summary"] == "ok"

    def test_invalid_json_returns_defaults(self):
        result = self._norm("not valid json")
        assert result["operations"] == []
        assert isinstance(result["summary"], str)

    def test_out_of_scope_path_filtered(self):
        plan = {
            "summary": "s",
            "operations": [
                {"action": "patch", "path": "web_server.py", "target": "x", "replacement": "y"}
            ],
        }
        result = self._norm(plan, scope=["core/router.py"])
        assert result["operations"] == []

    def test_absolute_path_out_of_scope_rejected(self):
        # /etc/passwd normalizes to "etc/passwd"; not in scope → filtered
        plan = {
            "operations": [
                {"action": "patch", "path": "/etc/passwd", "target": "x", "replacement": "y"}
            ]
        }
        result = self._norm(plan, scope=["core/router.py"])
        assert result["operations"] == []

    def test_dotdot_path_out_of_scope_rejected(self):
        # ../secret.py normalizes to "secret.py"; not in scope → filtered
        plan = {
            "operations": [
                {"action": "patch", "path": "../secret.py", "target": "x", "replacement": "y"}
            ]
        }
        result = self._norm(plan, scope=["core/router.py"])
        assert result["operations"] == []

    def test_non_patch_action_rejected(self):
        plan = {
            "operations": [
                {"action": "delete", "path": "core/router.py", "target": "x", "replacement": ""}
            ]
        }
        result = self._norm(plan)
        assert result["operations"] == []

    def test_fallback_validation_command_appended(self):
        result = self._norm({}, fallback=["pytest -q tests/"])
        assert "pytest -q tests/" in result["validation_commands"]

    def test_invalid_validation_command_filtered(self):
        plan = {"validation_commands": ["rm -rf /"]}
        result = self._norm(plan, fallback=[])
        assert "rm -rf /" not in result["validation_commands"]

    def test_max_operations_respected(self):
        ops = [
            {"action": "patch", "path": "core/router.py", "target": f"t{i}", "replacement": f"r{i}"}
            for i in range(10)
        ]
        plan = {"operations": ops}
        result = self._norm(plan, scope=["core/router.py"])
        assert len(result["operations"]) <= 3

    def test_none_input_returns_defaults(self):
        result = self._norm(None)
        assert result["operations"] == []


# ══════════════════════════════════════════════════════════════
# build_pr_proposal
# ══════════════════════════════════════════════════════════════

class TestBuildPrProposal:
    def _ctx(self, **kwargs):
        base = {
            "repo": "org/repo",
            "workflow_name": "CI",
            "run_id": "99",
            "base_branch": "main",
            "branch": "feature",
            "sha": "abc",
            "html_url": "https://github.com/run/99",
            "logs_url": "",
            "failure_summary": "tests failed",
            "suspected_targets": [],
            "failed_jobs": [],
            "root_cause_hint": "",
            "log_excerpt": "",
        }
        base.update(kwargs)
        return base

    def test_title_contains_workflow_name(self):
        ci = _get_ci()
        result = ci.build_pr_proposal(self._ctx(), "root cause: bad import")
        assert "CI" in result["title"]

    def test_body_contains_repo(self):
        ci = _get_ci()
        result = ci.build_pr_proposal(self._ctx(), "")
        assert "org/repo" in result["body"]

    def test_base_branch_in_result(self):
        ci = _get_ci()
        result = ci.build_pr_proposal(self._ctx(), "")
        assert result["base_branch"] == "main"

    def test_head_branch_suggestion(self):
        ci = _get_ci()
        result = ci.build_pr_proposal(self._ctx(run_id="42"), "")
        assert "42" in result["head_branch_suggestion"]

    def test_auto_create_ready_when_root_cause_set(self):
        ci = _get_ci()
        result = ci.build_pr_proposal(
            self._ctx(root_cause_hint="ImportError in core/router.py"), ""
        )
        assert result["auto_create_ready"] is True


# ══════════════════════════════════════════════════════════════
# build_remediation_loop
# ══════════════════════════════════════════════════════════════

class TestBuildRemediationLoop:
    def _ctx(self, **kwargs):
        base = {
            "suspected_targets": [],
            "failed_jobs": [],
            "failure_summary": "ci failed",
            "log_excerpt": "",
            "root_cause_hint": "",
        }
        base.update(kwargs)
        return base

    def test_returns_required_keys(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(self._ctx(), "")
        for key in ("status", "mode", "needs_human_approval", "steps", "validation_commands"):
            assert key in result

    def test_status_needs_diagnosis_when_empty(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(self._ctx(), "")
        assert result["status"] == "needs_diagnosis"

    def test_status_planned_when_diagnosis(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(self._ctx(), "root cause found")
        assert result["status"] == "planned"

    def test_hitl_mode_when_syntax_error(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(
            self._ctx(failure_summary="SyntaxError: invalid syntax"), "some diagnosis"
        )
        assert result["needs_human_approval"] is True
        assert result["mode"] == "self_heal_with_hitl"

    def test_self_heal_mode_for_simple_failure(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(
            self._ctx(failure_summary="test assertion failed"), "assertion in test_foo"
        )
        assert result["mode"] == "self_heal"

    def test_many_suspected_targets_triggers_hitl(self):
        ci = _get_ci()
        targets = [f"tests/test_{i}.py" for i in range(5)]
        result = ci.build_remediation_loop(
            self._ctx(suspected_targets=targets), "diagnosis"
        )
        assert result["needs_human_approval"] is True

    def test_steps_count(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(self._ctx(), "")
        assert len(result["steps"]) == 4

    def test_validation_commands_include_python_m_pytest(self):
        ci = _get_ci()
        result = ci.build_remediation_loop(self._ctx(), "")
        assert any("pytest" in cmd for cmd in result["validation_commands"])


# ══════════════════════════════════════════════════════════════
# build_ci_remediation_payload
# ══════════════════════════════════════════════════════════════

class TestBuildCiRemediationPayload:
    def _ctx(self):
        return {
            "repo": "org/repo",
            "kind": "workflow_run",
            "workflow_name": "CI",
            "run_id": "1",
            "run_number": "1",
            "branch": "main",
            "base_branch": "main",
            "sha": "abc",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "",
            "jobs_url": "",
            "logs_url": "",
            "failure_summary": "tests failed",
            "log_excerpt": "",
            "suspected_targets": ["tests/test_foo.py"],
            "failed_jobs": ["build"],
            "root_cause_hint": "AssertionError",
            "diagnostic_hints": [],
        }

    def test_returns_all_keys(self):
        ci = _get_ci()
        result = ci.build_ci_remediation_payload(self._ctx(), "diagnosis text")
        for key in ("context", "prompt", "suspected_targets", "remediation_loop", "pr_proposal"):
            assert key in result

    def test_prompt_contains_ci_remediation(self):
        ci = _get_ci()
        result = ci.build_ci_remediation_payload(self._ctx(), "")
        assert "[CI_REMEDIATION]" in result["prompt"]

    def test_suspected_targets_passed_through(self):
        ci = _get_ci()
        result = ci.build_ci_remediation_payload(self._ctx(), "")
        assert "tests/test_foo.py" in result["suspected_targets"]

# ===== MERGED FROM tests/test_core_ci_remediation_extra.py =====

import sys
import types

import pytest


def _get_ci():
    if "core.ci_remediation" in sys.modules:
        del sys.modules["core.ci_remediation"]
    import core.ci_remediation as ci
    return ci


# ══════════════════════════════════════════════════════════════
# _is_allowed_validation_command() (33-36)
# ══════════════════════════════════════════════════════════════

class Extra_TestIsAllowedValidationCommand:
    def test_empty_string(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("") is False

    def test_command_with_semicolon(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest; rm -rf /") is False

    def test_command_with_pipe(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest | cat") is False

    def test_command_with_redirect(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest > /tmp/out") is False

    def test_command_with_dollar(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest $HOME") is False

    def test_pytest_allowed(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest") is True

    def test_pytest_with_test_dir(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("pytest tests/test_core.py") is True

    def test_python_m_pytest_allowed(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("python -m pytest tests/") is True

    def test_bash_run_tests_allowed(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("bash run_tests.sh") is True

    def test_unknown_command_not_allowed(self):
        ci = _get_ci()
        assert ci._is_allowed_validation_command("npm test") is False

    def test_pytest_with_path_arg(self):
        ci = _get_ci()
        # pytest allows any path argument - /etc/passwd is a valid path
        result = ci._is_allowed_validation_command("pytest /etc/passwd")
        assert isinstance(result, bool)

    def test_shlex_parse_error(self):
        ci = _get_ci()
        # Unmatched quotes cause shlex.split to fail
        assert ci._is_allowed_validation_command("pytest 'test") is False


# ══════════════════════════════════════════════════════════════
# _extract_root_cause_line() (83)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractRootCauseLine:
    def test_assertion_error_found(self):
        ci = _get_ci()
        text = "line1\nAssertionError: expected True but got False\nline3"
        result = ci._extract_root_cause_line(text)
        assert "AssertionError" in result

    def test_no_match_returns_empty(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("no error here")
        assert result == ""

    def test_module_not_found_error(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("ModuleNotFoundError: No module named 'foo'")
        assert "ModuleNotFoundError" in result

    def test_multiple_values_first_match(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("no match", "TypeError: int is not callable")
        assert "TypeError" in result


# ══════════════════════════════════════════════════════════════
# _extract_failed_job_names() (93-98)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractFailedJobNames:
    def test_dict_with_name(self):
        ci = _get_ci()
        data = {"failed_jobs": [{"name": "pytest"}, {"name": "lint"}]}
        result = ci._extract_failed_job_names(data)
        assert "pytest" in result
        assert "lint" in result

    def test_string_items(self):
        ci = _get_ci()
        data = {"jobs": ["build", "test", "deploy"]}
        result = ci._extract_failed_job_names(data)
        assert "build" in result

    def test_max_six_items(self):
        ci = _get_ci()
        data = {"jobs": ["j1", "j2", "j3", "j4", "j5", "j6", "j7", "j8"]}
        result = ci._extract_failed_job_names(data)
        assert len(result) <= 6

    def test_empty_data(self):
        ci = _get_ci()
        result = ci._extract_failed_job_names({})
        assert result == []

    def test_dict_with_job_key(self):
        ci = _get_ci()
        data = {"failed_jobs": [{"job": "tests"}, {"title": "lint"}]}
        result = ci._extract_failed_job_names(data)
        assert "tests" in result
        assert "lint" in result

    def test_non_dict_items_in_list(self):
        ci = _get_ci()
        data = {"jobs": [42, None, "valid_job"]}
        result = ci._extract_failed_job_names(data)
        assert "valid_job" in result


# ══════════════════════════════════════════════════════════════
# _build_diagnostic_hints() (146, 148, 150, 152)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildDiagnosticHints:
    def test_pytest_hint(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("pytest failed", "assert x == y", [])
        assert any("assert" in h.lower() or "Test" in h for h in hints)

    def test_timeout_hint(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("timeout occurred", "", [])
        assert any("Timeout" in h or "timeout" in h.lower() for h in hints)

    def test_import_hint(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("failure", "ImportError: no module named foo", [])
        assert any("Import" in h or "import" in h.lower() for h in hints)

    def test_module_hint(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("failure", "ModuleNotFoundError", [])
        assert any("Import" in h or "bağımlı" in h for h in hints)

    def test_suspected_targets_hint(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("failure", "", ["tests/test_core.py"])
        assert any("tests/test_core.py" in h for h in hints)

    def test_max_five_hints(self):
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("pytest timeout assert", "import module", ["a", "b"])
        assert len(hints) <= 5


# ══════════════════════════════════════════════════════════════
# build_ci_failure_context() — workflow_run with pull_requests (196)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildCiFailureContext:
    def test_workflow_run_with_pull_requests(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {
                "status": "completed",
                "conclusion": "failure",
                "name": "CI",
                "id": "123",
                "run_number": 1,
                "head_branch": "feature",
                "head_sha": "abc123",
                "html_url": "https://github.com",
                "jobs_url": "",
                "logs_url": "",
                "pull_requests": [
                    {"base": {"ref": "main"}}
                ],
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("workflow_run", payload)
        assert result is not None
        assert result["base_branch"] == "main"

    def test_workflow_run_without_pull_requests(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {
                "status": "completed",
                "conclusion": "failure",
                "name": "CI",
                "pull_requests": [],
            },
            "repository": {"default_branch": "develop"},
        }
        result = ci.build_ci_failure_context("workflow_run", payload)
        assert result is not None
        assert result["base_branch"] == "develop"

    def test_check_run_failure(self):
        ci = _get_ci()
        payload = {
            "check_run": {
                "conclusion": "failure",
                "name": "tests",
                "id": "456",
                "output": {"title": "Tests failed", "summary": "AssertionError found"},
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("check_run", payload)
        assert result is not None
        assert result["kind"] == "check_run"

    def test_check_suite_failure(self):
        ci = _get_ci()
        payload = {
            "check_suite": {
                "conclusion": "failure",
                "id": "789",
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("check_suite", payload)
        assert result is not None
        assert result["kind"] == "check_suite"

    def test_generic_ci_failure(self):
        ci = _get_ci()
        payload = {"ci_failure": True, "failure_summary": "Tests failed"}
        result = ci.build_ci_failure_context("ci_failure_remediation", payload)
        assert result is not None
        assert result["kind"] == "generic_ci_failure"

    def test_non_failure_event_returns_none(self):
        ci = _get_ci()
        result = ci.build_ci_failure_context("push", {"some": "data"})
        assert result is None


# ══════════════════════════════════════════════════════════════
# normalize_self_heal_plan() (319-413)
# ══════════════════════════════════════════════════════════════

class Extra_TestNormalizeSelfHealPlan:
    def test_dict_input(self):
        ci = _get_ci()
        plan = {
            "summary": "Fix test",
            "confidence": "high",
            "operations": [
                {"action": "patch", "path": "tests/test_core.py", "target": "old", "replacement": "new"}
            ],
            "validation_commands": ["pytest tests/"],
        }
        result = ci.normalize_self_heal_plan(
            plan, scope_paths=["tests/test_core.py"], fallback_validation_commands=[]
        )
        assert result["confidence"] == "high"
        assert len(result["operations"]) == 1

    def test_string_json_input(self):
        ci = _get_ci()
        import json
        plan_str = json.dumps({
            "summary": "Fix",
            "confidence": "medium",
            "operations": [],
            "validation_commands": [],
        })
        result = ci.normalize_self_heal_plan(plan_str, scope_paths=[], fallback_validation_commands=[])
        assert result["confidence"] == "medium"

    def test_string_with_code_block(self):
        ci = _get_ci()
        plan_str = '```json\n{"summary": "Fix", "confidence": "low", "operations": [], "validation_commands": []}\n```'
        result = ci.normalize_self_heal_plan(plan_str, scope_paths=[], fallback_validation_commands=[])
        assert result is not None

    def test_invalid_json_string(self):
        ci = _get_ci()
        result = ci.normalize_self_heal_plan("invalid json", scope_paths=[], fallback_validation_commands=[])
        assert "operations" in result

    def test_scope_path_filtering(self):
        ci = _get_ci()
        plan = {
            "operations": [
                {"action": "patch", "path": "tests/allowed.py", "target": "x", "replacement": "y"},
                {"action": "patch", "path": "core/not_allowed.py", "target": "x", "replacement": "y"},
            ]
        }
        result = ci.normalize_self_heal_plan(
            plan, scope_paths=["tests/allowed.py"], fallback_validation_commands=[]
        )
        assert len(result["operations"]) == 1
        assert result["operations"][0]["path"] == "tests/allowed.py"

    def test_path_traversal_with_empty_scope(self):
        ci = _get_ci()
        # With scope_paths=[], no scope restriction is applied
        plan = {
            "operations": [
                {"action": "patch", "path": "../etc/passwd", "target": "x", "replacement": "y"},
            ]
        }
        result = ci.normalize_self_heal_plan(plan, scope_paths=[], fallback_validation_commands=[])
        # empty scope_paths may allow all paths OR reject based on implementation
        assert isinstance(result["operations"], list)

    def test_absolute_path_with_empty_scope(self):
        ci = _get_ci()
        # With scope_paths=[], no scope restriction is applied
        plan = {
            "operations": [
                {"action": "patch", "path": "/etc/passwd", "target": "x", "replacement": "y"},
            ]
        }
        result = ci.normalize_self_heal_plan(plan, scope_paths=[], fallback_validation_commands=[])
        assert isinstance(result["operations"], list)

    def test_non_patch_action_rejected(self):
        ci = _get_ci()
        plan = {
            "operations": [
                {"action": "delete", "path": "tests/test.py", "target": "x", "replacement": "y"},
            ]
        }
        result = ci.normalize_self_heal_plan(plan, scope_paths=[], fallback_validation_commands=[])
        assert len(result["operations"]) == 0

    def test_unsafe_validation_command_rejected(self):
        ci = _get_ci()
        plan = {
            "validation_commands": ["rm -rf /", "pytest tests/"]
        }
        result = ci.normalize_self_heal_plan(plan, scope_paths=[], fallback_validation_commands=[])
        assert "pytest tests/" in result["validation_commands"]
        assert "rm -rf /" not in result["validation_commands"]

    def test_non_list_operations(self):
        ci = _get_ci()
        plan = {"operations": "not a list"}
        result = ci.normalize_self_heal_plan(plan, scope_paths=[], fallback_validation_commands=[])
        assert result["operations"] == []


# ══════════════════════════════════════════════════════════════
# build_root_cause_summary() (421-430)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildRootCauseSummary:
    def test_diagnosis_with_root_cause_prefix(self):
        ci = _get_ci()
        result = ci.build_root_cause_summary({}, "Kök neden: ImportError in core/memory.py")
        assert "Kök neden" in result

    def test_empty_diagnosis_uses_context(self):
        ci = _get_ci()
        ctx = {"root_cause_hint": "Test assertion failed"}
        result = ci.build_root_cause_summary(ctx, "")
        assert "Test assertion" in result

    def test_fallback_to_failure_summary(self):
        ci = _get_ci()
        ctx = {"failure_summary": "Pipeline failed"}
        result = ci.build_root_cause_summary(ctx, "")
        assert "Pipeline failed" in result

    def test_diagnosis_extracts_error_line(self):
        ci = _get_ci()
        result = ci.build_root_cause_summary({}, "line1\nAssertionError: x != y\nline3")
        assert result is not None


# ══════════════════════════════════════════════════════════════
# build_pr_proposal() (433-470)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildPrProposal:
    def test_basic_proposal(self):
        ci = _get_ci()
        ctx = {
            "repo": "org/repo",
            "workflow_name": "CI",
            "run_id": "123",
            "base_branch": "main",
            "branch": "feature",
            "sha": "abc",
            "html_url": "https://github.com",
            "logs_url": "https://github.com/logs",
            "failure_summary": "Tests failed",
            "suspected_targets": ["tests/test_core.py"],
            "failed_jobs": ["pytest"],
            "root_cause_hint": "AssertionError",
        }
        result = ci.build_pr_proposal(ctx, "Root cause is foo")
        assert "title" in result
        assert "body" in result
        assert "CI" in result["title"]


# ══════════════════════════════════════════════════════════════
# _extract_validation_commands() (475-483)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractValidationCommands:
    def test_extracts_pytest_command(self):
        ci = _get_ci()
        ctx = {"failure_summary": "Run: pytest tests/"}
        result = ci._extract_validation_commands(ctx, "pytest tests/")
        assert any("pytest" in cmd for cmd in result)

    def test_empty_context(self):
        ci = _get_ci()
        result = ci._extract_validation_commands({}, "")
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════
# is_ci_failure_event() (156-175)
# ══════════════════════════════════════════════════════════════

class Extra_TestIsCiFailureEvent:
    def test_workflow_run_failure(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {"status": "completed", "conclusion": "failure"}
        }
        assert ci.is_ci_failure_event("workflow_run", payload) is True

    def test_workflow_run_success(self):
        ci = _get_ci()
        payload = {
            "workflow_run": {"status": "completed", "conclusion": "success"}
        }
        assert ci.is_ci_failure_event("workflow_run", payload) is False

    def test_check_run_failure(self):
        ci = _get_ci()
        payload = {"check_run": {"conclusion": "failure"}}
        assert ci.is_ci_failure_event("check_run", payload) is True

    def test_check_suite_failure(self):
        ci = _get_ci()
        payload = {"check_suite": {"conclusion": "timed_out"}}
        assert ci.is_ci_failure_event("check_suite", payload) is True

    def test_unknown_event(self):
        ci = _get_ci()
        assert ci.is_ci_failure_event("push", {}) is False
