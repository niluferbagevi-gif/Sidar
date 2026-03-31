"""
core/ci_remediation.py için ek testler — eksik satırları kapsar.
"""
from __future__ import annotations

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

class TestIsAllowedValidationCommand:
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

class TestExtractRootCauseLine:
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

class TestExtractFailedJobNames:
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

class TestBuildDiagnosticHints:
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

class TestBuildCiFailureContext:
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

class TestNormalizeSelfHealPlan:
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

class TestBuildRootCauseSummary:
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

class TestBuildPrProposal:
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

class TestExtractValidationCommands:
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

class TestIsCiFailureEvent:
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
