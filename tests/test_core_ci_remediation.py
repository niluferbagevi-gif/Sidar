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


# ══════════════════════════════════════════════════════════════
# Eksik branch kapsamı için ek testler
# ══════════════════════════════════════════════════════════════

class TestIsAllowedValidationCommandMissingBranches:
    """Lines 33-34 (ValueError) ve 36 (empty parts) kapsamı."""

    def test_shlex_value_error_returns_false(self):
        """Lines 33-34: shlex.split raises ValueError for unclosed quote → return False."""
        ci = _get_ci()
        # Unclosed single quote causes ValueError in shlex.split
        result = ci._is_allowed_validation_command("pytest 'unclosed")
        assert result is False

    def test_empty_parts_after_shlex_returns_false(self):
        """Line 36: shlex.split returns [] → if not parts: return False."""
        from unittest.mock import patch
        ci = _get_ci()
        with patch("core.ci_remediation.shlex.split", return_value=[]):
            result = ci._is_allowed_validation_command("pytest")
        assert result is False


class TestExtractRootCauseLineEmptyLines:
    """Line 83: empty line in text → continue (158->156 equivalent for _extract_root_cause_line)."""

    def test_skips_empty_lines_before_finding_error(self):
        """Line 83: text with empty lines → continue executed."""
        ci = _get_ci()
        result = ci._extract_root_cause_line("line1\n\nImportError: bad module\nmore")
        assert "ImportError" in result

    def test_empty_only_lines_no_match(self):
        ci = _get_ci()
        result = ci._extract_root_cause_line("\n\n\n")
        assert result == ""


class TestExtractFailedJobNames:
    """Lines 93-98: _extract_failed_job_names body coverage."""

    def test_dict_items_with_name_field(self):
        """Lines 93-95: isinstance(item, dict) True → use item.get('name')."""
        ci = _get_ci()
        data = {"failed_jobs": [{"name": "build"}, {"name": "test"}]}
        result = ci._extract_failed_job_names(data)
        assert "build" in result
        assert "test" in result

    def test_string_items_non_dict(self):
        """Lines 95-96: isinstance(item, dict) False → name = str(item).strip()."""
        ci = _get_ci()
        data = {"failed_jobs": ["build-job", "lint-job"]}
        result = ci._extract_failed_job_names(data)
        assert "build-job" in result
        assert "lint-job" in result

    def test_mixed_dict_and_string_items(self):
        """Lines 93-98: mix of dict and non-dict items."""
        ci = _get_ci()
        data = {"failed_jobs": [{"name": "test-suite"}, "deploy-stage"]}
        result = ci._extract_failed_job_names(data)
        assert "test-suite" in result
        assert "deploy-stage" in result

    def test_deduplicates_job_names(self):
        """Line 97-98: if name not in names → dedup."""
        ci = _get_ci()
        data = {"failed_jobs": [{"name": "ci"}, {"name": "ci"}]}
        result = ci._extract_failed_job_names(data)
        assert result.count("ci") == 1

    def test_jobs_key_fallback(self):
        """Line 90: uses 'jobs' key when 'failed_jobs' not present."""
        ci = _get_ci()
        data = {"jobs": [{"name": "build"}]}
        result = ci._extract_failed_job_names(data)
        assert "build" in result


class TestBuildDiagnosticHints:
    """Lines 146, 148, 150, 152: _build_diagnostic_hints hint appends."""

    def test_suspected_targets_hint(self):
        """Line 146: suspected_targets non-empty → append targets hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("failure", "", ["tests/test_foo.py"])
        assert any("tests/test_foo.py" in h for h in hints)

    def test_pytest_assert_hint(self):
        """Line 148: 'pytest' in summary → append assertion drift hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("pytest tests failed", "", [])
        assert any("assertion" in h.lower() or "Test" in h for h in hints)

    def test_assert_in_log_hint(self):
        """Line 148: 'assert' in log_excerpt → append assertion drift hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("ci failed", "AssertionError: assert 1 == 2", [])
        assert any("assert" in h.lower() or "Test" in h for h in hints)

    def test_timeout_hint(self):
        """Line 150: 'timeout' in failure_summary → append timeout hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("timeout after 30s", "", [])
        assert any("timeout" in h.lower() or "Timeout" in h for h in hints)

    def test_import_hint(self):
        """Line 152: 'import' in log_excerpt → append import chain hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("ci failed", "ImportError: no module named foo", [])
        assert any("import" in h.lower() or "Import" in h for h in hints)

    def test_module_hint(self):
        """Line 152: 'module' in log_excerpt → append import chain hint."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints("ci failed", "ModuleNotFoundError: module core.x", [])
        assert any("module" in h.lower() or "Import" in h for h in hints)

    def test_all_hints_combined(self):
        """Lines 146, 148, 150, 152: all hints triggered."""
        ci = _get_ci()
        hints = ci._build_diagnostic_hints(
            "pytest timeout error",
            "assert failed, ImportError: missing",
            ["tests/test_foo.py"],
        )
        assert len(hints) >= 4


class TestBuildCiFailureContextPullRequests:
    """Line 196: workflow_run with pull_requests → base_branch from PR."""

    def test_workflow_run_with_pull_requests_sets_base_branch(self):
        """Line 196: pull_requests non-empty → base_branch = pr.base.ref."""
        ci = _get_ci()
        payload = {
            "workflow_run": {
                "status": "completed",
                "conclusion": "failure",
                "name": "CI",
                "id": 1,
                "run_number": 1,
                "head_branch": "feature",
                "head_sha": "abc",
                "html_url": "",
                "jobs_url": "",
                "logs_url": "",
                "pull_requests": [
                    {"base": {"ref": "develop"}}
                ],
            },
            "repository": {"full_name": "org/repo"},
        }
        result = ci.build_ci_failure_context("workflow_run", payload)
        assert result is not None
        assert result["base_branch"] == "develop"


class TestNormalizeSelfHealPlanMissingBranches:
    """Lines 365->367 (no-json code block) and 384 (non-dict operation)."""

    def _norm(self, raw, scope=None, fallback=None):
        ci = _get_ci()
        return ci.normalize_self_heal_plan(
            raw,
            scope_paths=scope or ["core/router.py"],
            fallback_validation_commands=fallback or ["pytest"],
        )

    def test_markdown_code_block_without_json_prefix(self):
        """365->367: ``` block without 'json' prefix → text[4:] NOT stripped."""
        import json as _json
        inner = _json.dumps({
            "summary": "plain block",
            "confidence": "low",
            "operations": [],
            "validation_commands": [],
        })
        raw = f"```\n{inner}\n```"
        result = self._norm(raw)
        assert result["summary"] == "plain block"

    def test_non_dict_operation_item_skipped(self):
        """Line 384: non-dict item in operations → continue (skipped)."""
        plan = {
            "summary": "test",
            "operations": [
                "this is a string, not a dict",
                {"action": "patch", "path": "core/router.py", "target": "x", "replacement": "y"},
            ],
        }
        result = self._norm(plan, scope=["core/router.py"])
        # Only the dict operation should appear
        assert len(result["operations"]) == 1
        assert result["operations"][0]["target"] == "x"


class TestBuildRootCauseSummary:
    """Lines 421->425, 428-430: build_root_cause_summary all paths."""

    def _ctx(self, **kwargs):
        base = {
            "failure_summary": "ci failed",
            "log_excerpt": "",
            "root_cause_hint": "",
        }
        base.update(kwargs)
        return base

    def test_diagnosis_starts_with_root_cause(self):
        """Line 423-424: compact_sentence starts with 'root cause' → return it."""
        ci = _get_ci()
        result = ci.build_root_cause_summary(self._ctx(), "Root cause: bad import in core/router.py")
        assert "root cause" in result.lower() or "Root cause" in result

    def test_diagnosis_starts_with_kok_neden(self):
        """Line 423-424: compact_sentence starts with 'kök neden' → return it."""
        ci = _get_ci()
        result = ci.build_root_cause_summary(self._ctx(), "Kök neden: ImportError at core/rag.py")
        assert "Kök neden" in result or "kök neden" in result.lower()

    def test_empty_first_line_falls_through(self):
        """421->425: first sentence is empty (leading newline) → fall through to inferred."""
        ci = _get_ci()
        result = ci.build_root_cause_summary(
            self._ctx(log_excerpt="ImportError: no module"),
            "\nsome non-root-cause text",
        )
        # Falls to _extract_root_cause_line → finds ImportError
        assert result != ""

    def test_no_inferred_uses_root_cause_hint(self):
        """Lines 428-429: inferred empty (no pattern keywords), root_cause_hint set → return hint."""
        ci = _get_ci()
        # failure_summary and log_excerpt must NOT contain any _ROOT_CAUSE_PATTERN keywords
        # (AssertionError, ImportError, TypeError, ValueError, SyntaxError, NameError,
        #  timeout, timed out, failed) so that _extract_root_cause_line returns ""
        result = ci.build_root_cause_summary(
            self._ctx(
                failure_summary="pipeline unreachable due to network issue",
                root_cause_hint="Possible deadlock in threading",
            ),
            "generic analysis with no pattern keywords",
        )
        assert "Possible deadlock" in result

    def test_no_hint_fallback_to_failure_summary(self):
        """Line 430: no inferred, no hint → return failure_summary."""
        ci = _get_ci()
        result = ci.build_root_cause_summary(
            self._ctx(
                failure_summary="Pipeline unreachable on step 3",
                root_cause_hint="",
            ),
            "generic analysis only",
        )
        assert "Pipeline unreachable" in result

    def test_empty_diagnosis_uses_hint(self):
        """Line 421->425 via empty diagnosis_text → skip to inferred → hint path."""
        ci = _get_ci()
        # failure_summary must NOT contain pattern keywords so inferred = ""
        result = ci.build_root_cause_summary(
            self._ctx(
                failure_summary="pipeline unreachable",
                root_cause_hint="Deadlock in auth service",
            ),
            "",
        )
        assert "Deadlock" in result


class TestBuildSelfHealPatchPrompt:
    """Lines 319-331: build_self_heal_patch_prompt coverage."""

    def _ctx(self):
        return {
            "repo": "org/repo",
            "workflow_name": "CI",
            "failure_summary": "tests failed",
            "root_cause_hint": "AssertionError in tests/test_foo.py",
        }

    def _loop(self):
        return {
            "scope_paths": ["core/router.py"],
            "validation_commands": ["pytest tests/"],
        }

    def test_basic_prompt_contains_markers(self):
        """Line 319-331: basic invocation returns a SELF_HEAL_PLAN prompt."""
        ci = _get_ci()
        result = ci.build_self_heal_patch_prompt(
            self._ctx(),
            "Diagnosis: bad import",
            self._loop(),
            [],
        )
        assert "[SELF_HEAL_PLAN]" in result
        assert "core/router.py" in result

    def test_with_valid_file_snapshots(self):
        """Line 324-329: file_snapshots with valid path and content → appended."""
        ci = _get_ci()
        snapshots = [{"path": "core/router.py", "content": "def route(): pass"}]
        result = ci.build_self_heal_patch_prompt(
            self._ctx(),
            "Diagnosis: routing error",
            self._loop(),
            snapshots,
        )
        assert "[FILE] core/router.py" in result
        assert "def route(): pass" in result

    def test_snapshot_with_empty_path_skipped(self):
        """Line 327: not path → continue (snapshot with empty path is skipped)."""
        ci = _get_ci()
        snapshots = [
            {"path": "", "content": "some content"},
            {"path": "core/router.py", "content": "def route(): pass"},
        ]
        result = ci.build_self_heal_patch_prompt(
            self._ctx(), "dx", self._loop(), snapshots
        )
        assert "[FILE] core/router.py" in result
        # Empty path snapshot should not appear
        assert "[FILE] " not in result.split("[FILE] core/router.py")[0]

    def test_snapshot_with_empty_content_skipped(self):
        """Line 327: not content → continue (snapshot with empty content is skipped)."""
        ci = _get_ci()
        snapshots = [
            {"path": "core/router.py", "content": ""},
        ]
        result = ci.build_self_heal_patch_prompt(
            self._ctx(), "dx", self._loop(), snapshots
        )
        assert "[FILE] core/router.py" not in result

    def test_empty_context_and_loop(self):
        """Line 319-320: empty context and remediation_loop dicts handled gracefully."""
        ci = _get_ci()
        result = ci.build_self_heal_patch_prompt({}, "diagnosis", {}, [])
        assert "[SELF_HEAL_PLAN]" in result


class TestExtractValidationCommands:
    """Lines 481, 483: _extract_validation_commands coverage."""

    def test_finds_pytest_command_in_log_excerpt(self):
        """Line 483: valid command in log_excerpt → appended to commands."""
        ci = _get_ci()
        context = {
            "failure_summary": "",
            "log_excerpt": "pytest tests/test_foo.py",
            "suspected_targets": [],
        }
        result = ci._extract_validation_commands(context, "")
        assert any("pytest" in cmd for cmd in result)

    def test_skips_empty_lines_in_sources(self):
        """Line 481: empty normalized line → continue executed."""
        ci = _get_ci()
        context = {
            "failure_summary": "\npytest tests/test_foo.py\n",
            "log_excerpt": "",
            "suspected_targets": [],
        }
        result = ci._extract_validation_commands(context, "")
        # Empty lines are skipped; valid pytest line is found
        assert any("pytest" in cmd for cmd in result)

    def test_suspected_targets_added_as_pytest_command(self):
        """Line 485-487: suspected_targets with tests/ prefix → targeted pytest cmd."""
        ci = _get_ci()
        context = {
            "failure_summary": "",
            "log_excerpt": "",
            "suspected_targets": ["tests/test_foo.py", "tests/test_bar.py"],
        }
        result = ci._extract_validation_commands(context, "")
        assert any("tests/test_foo.py" in cmd for cmd in result)

    def test_invalid_command_in_diagnosis_not_added(self):
        """Line 482: invalid command skipped."""
        ci = _get_ci()
        context = {"failure_summary": "", "log_excerpt": "", "suspected_targets": []}
        result = ci._extract_validation_commands(context, "rm -rf /")
        assert "rm -rf /" not in result
