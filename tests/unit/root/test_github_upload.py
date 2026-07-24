import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import types

import pytest

import github_upload as gu

ORIGINAL_SYNC_INSTALL_MANIFESTS_BEFORE_COMMIT = gu.sync_install_manifests_before_commit
ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE = gu.run_pre_push_quality_gate
ORIGINAL_STAMP_INSTALL_MANIFEST_PIN_AFTER_COMMIT = gu.stamp_install_manifest_pin_after_commit
ORIGINAL_ENSURE_FULL_GIT_HISTORY_FOR_MANIFEST_CHECKS = (
    gu.ensure_full_git_history_for_manifest_checks
)
ORIGINAL_ASSERT_NO_UNMERGED_FILES = gu.assert_no_unmerged_files
ORIGINAL_REEXEC_AFTER_EXTERNAL_BRANCH_MERGE = gu.reexec_after_external_branch_merge
ORIGINAL_CHECK_BRANCH_PROTECTION_BEST_EFFORT = gu.check_branch_protection_best_effort
ORIGINAL_CREATE_DRAFT_PR_BEST_EFFORT = gu.create_draft_pr_best_effort


@pytest.fixture(autouse=True)
def _stub_upload_guards(monkeypatch):
    monkeypatch.setattr(gu, "sync_install_manifests_before_commit", lambda: (True, ""))
    monkeypatch.setattr(gu, "run_pre_push_quality_gate", lambda: (True, ""))
    monkeypatch.setattr(gu, "stamp_install_manifest_pin_after_commit", lambda: (True, ""))
    monkeypatch.setattr(gu, "assert_no_unmerged_files", lambda: None)
    monkeypatch.setattr(gu, "reexec_after_external_branch_merge", lambda: None)
    # Draft PR creation and branch-protection lookups hit the real GitHub API via
    # urllib; tests default to a safe no-op unless a test overrides these to
    # exercise the PR/branch-protection flow itself.
    monkeypatch.setattr(gu, "create_draft_pr_best_effort", lambda branch, version: None)
    monkeypatch.setattr(
        gu, "check_branch_protection_best_effort", lambda owner_repo, branch, token: None
    )


def test_reexec_after_external_branch_merge_loads_new_code_without_repull(monkeypatch, tmp_path):
    """The running pre-merge module is replaced before manifest validation."""
    calls = []
    monkeypatch.setattr(gu, "__file__", str(tmp_path / "github_upload.py"))
    monkeypatch.setattr(gu.sys, "executable", "/venv/bin/python")
    monkeypatch.delenv("SIDAR_GITHUB_UPLOAD_REEXEC_AFTER_MERGE", raising=False)
    monkeypatch.setattr(gu.os, "execve", lambda *args: calls.append(args))

    ORIGINAL_REEXEC_AFTER_EXTERNAL_BRANCH_MERGE()

    assert len(calls) == 1
    executable, argv, env = calls[0]
    assert executable == "/venv/bin/python"
    assert argv == ["/venv/bin/python", str((tmp_path / "github_upload.py").resolve())]
    assert env["SIDAR_GITHUB_UPLOAD_REEXEC_AFTER_MERGE"] == "1"


def test_reexec_after_external_branch_merge_is_single_shot(monkeypatch):
    calls = []
    monkeypatch.setenv("SIDAR_GITHUB_UPLOAD_REEXEC_AFTER_MERGE", "1")
    monkeypatch.setattr(gu.os, "execve", lambda *args: calls.append(args))

    ORIGINAL_REEXEC_AFTER_EXTERNAL_BRANCH_MERGE()

    assert calls == []


def test_run_command_success_and_error(monkeypatch, capsys):
    class Result:
        def __init__(self, stdout="ok", stderr=""):
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(gu.subprocess, "run", lambda *a, **k: Result("hello\n", ""))
    ok, out = gu.run_command(["git", "status"])
    assert ok is True
    assert out == "hello"
    assert "hello" in capsys.readouterr().out

    def fail(*_a, **_k):
        raise gu.subprocess.CalledProcessError(1, ["git"], output="x", stderr="boom")

    monkeypatch.setattr(gu.subprocess, "run", fail)
    ok, err = gu.run_command(["git"], show_output=True)
    assert ok is False
    assert "boom" in err and "x" in err


def test_run_command_filters_oversized_environment(monkeypatch):
    captured = {}

    class Result:
        stdout = "ok"
        stderr = ""

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setenv("SIDAR_HUGE_SECRET", "x" * (gu.SUBPROCESS_ENV_VALUE_MAX_BYTES + 1))
    monkeypatch.setenv("SIDAR_SMALL_FLAG", "1")
    monkeypatch.setattr(gu.subprocess, "run", fake_run)

    ok, out = gu.run_command(["git", "--version"], show_output=False)

    assert ok is True
    assert out == "ok"
    assert "SIDAR_HUGE_SECRET" not in captured["env"]
    assert captured["env"]["SIDAR_SMALL_FLAG"] == "1"


def test_run_command_merges_extra_env_on_top_of_bounded_env(monkeypatch):
    captured = {}

    class Result:
        stdout = "ok"
        stderr = ""

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setenv("SIDAR_SMALL_FLAG", "1")
    monkeypatch.setattr(gu.subprocess, "run", fake_run)

    ok, out = gu.run_command(
        ["bash", "install_sidar.sh"],
        show_output=False,
        extra_env={"SIDAR_INSTALL_TEST_MODE": "1", "SIDAR_SMALL_FLAG": "override"},
    )

    assert ok is True
    assert out == "ok"
    assert captured["env"]["SIDAR_INSTALL_TEST_MODE"] == "1"
    assert captured["env"]["SIDAR_SMALL_FLAG"] == "override"


def test_run_command_reports_oserror(monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise OSError(7, "Argument list too long", "git")

    monkeypatch.setattr(gu.subprocess, "run", fail)

    ok, err = gu.run_command(["git", "--version"], show_output=True)

    assert ok is False
    assert "Argument list too long" in err
    assert "Komut baslatilamadi" in capsys.readouterr().out


def test_resolve_upload_version_uses_config_then_product_version(monkeypatch):
    monkeypatch.setattr(gu, "cfg", types.SimpleNamespace(VERSION="5.2.0"))
    assert gu.resolve_upload_version() == "5.2.0"

    monkeypatch.setattr(gu, "cfg", types.SimpleNamespace())
    monkeypatch.setattr(gu, "PRODUCT_VERSION", "5.2.0")
    assert gu.resolve_upload_version() == "5.2.0"


def test_url_and_path_helpers(tmp_path):
    assert gu._is_valid_repo_url("https://github.com/a/b")
    assert gu._is_valid_repo_url("https://github.com/a/b.git")
    assert gu._is_valid_repo_url("git@github.com:a/b.git")
    assert not gu._is_valid_repo_url("https://gitlab.com/a/b")
    assert not gu._is_valid_repo_url("https://github.com/a/b extra")
    assert not gu._is_valid_repo_url("")

    assert gu._is_valid_branch_name("feature/safe-branch_1")
    assert not gu._is_valid_branch_name("-upload-pack=evil")
    assert not gu._is_valid_branch_name("bad branch")
    assert not gu._is_valid_branch_name("bad..branch")
    assert not gu._is_valid_branch_name("bad@{branch")
    assert not gu._is_valid_branch_name("release/")
    assert not gu._is_valid_branch_name("release.lock")
    assert not gu._is_valid_branch_name("/release")
    assert not gu._is_valid_branch_name(".release")

    assert gu._normalize_path("./a//b\\c") == "a/b/c"
    assert gu._normalize_path("/root/x") == "root/x"

    assert gu.is_forbidden_path(".env")
    assert gu.is_forbidden_path("sessions/a.json")
    assert gu.is_forbidden_path(".git/config")
    assert gu.is_forbidden_path("coverage.json")
    assert gu.is_forbidden_path("coverage.xml")
    assert gu.is_forbidden_path("coverage-final.json")
    assert gu.is_forbidden_path("artifacts/test-summary.json")
    assert gu.is_forbidden_path("web_ui_react/coverage/coverage-summary.json")
    assert gu.is_forbidden_path("web_ui_react/playwright-report/index.html")
    assert gu.is_forbidden_path("web_ui_react/test-results/results.json")
    assert not gu.is_forbidden_path(".env.example")

    p = tmp_path / "ok.txt"
    p.write_text("abc", encoding="utf-8")
    assert gu.get_file_content(str(p)) == "abc"
    assert gu.get_file_content(".env") is None


def test_get_deleted_files_and_collect_safe_files(monkeypatch, tmp_path):
    text_file = tmp_path / "a.py"
    text_file.write_text("print('x')", encoding="utf-8")
    conflict_file = tmp_path / "conflict.py"
    conflict_file.write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> branch\n", encoding="utf-8")
    binary_file = tmp_path / "bad.json"
    binary_file.write_bytes(b"\xff\xfe")
    decorative_file = tmp_path / "decorative.py"
    decorative_file.write_text("Sidar CLI\n=================================\n", encoding="utf-8")
    generated_file = "coverage.json"

    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd[:3] == ["git", "ls-files", "-d"]:
            return True, "gone.txt\n"
        if cmd[:4] == ["git", "ls-files", "-co", "--exclude-standard"]:
            return (
                True,
                f"{text_file}\n{conflict_file}\n{binary_file}\n{decorative_file}\n{generated_file}\n.env\ngone.txt\n",
            )
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)
    deleted = gu.get_deleted_files()
    assert deleted == ["gone.txt"]
    assert fake_run(["git", "status"]) == (True, "")

    safe, blocked = gu.collect_safe_files(deleted)
    assert str(text_file) in safe
    assert str(decorative_file) in safe
    assert str(conflict_file) in blocked
    assert str(binary_file) in blocked
    assert generated_file in blocked
    assert ".env" in blocked

    monkeypatch.setattr(gu, "run_command", lambda *_a, **_k: (False, "err"))
    safe2, blocked2 = gu.collect_safe_files([])
    assert safe2 == [] and blocked2 == []


def test_has_conflict_markers_ignores_decorative_separator_lines(tmp_path):
    decorative_file = tmp_path / "decorative.py"
    decorative_file.write_text(
        """#!/usr/bin/env python3
Sidar CLI
=================================

print('ok')
""",
        encoding="utf-8",
    )

    markdown_file = tmp_path / "PROJE_RAPORU.md"
    markdown_file.write_text(
        """# Rapor

Bölüm ayıracı:
==============================

Alt başlık değil, Markdown süsleme çizgisi.
""",
        encoding="utf-8",
    )

    assert not gu.has_conflict_markers(str(decorative_file))
    assert not gu.has_conflict_markers(str(markdown_file))


def test_has_conflict_markers_allows_known_decorative_repo_files():
    repo_root = Path(__file__).resolve().parents[3]

    for relative_path in (
        "main.py",
        "cli.py",
        "docs/PROJE_RAPORU.md",
        "tests/unit/root/test_github_upload.py",
    ):
        assert not gu.has_conflict_markers(str(repo_root / relative_path))


def test_has_conflict_markers_detects_git_marker_lines(tmp_path):
    conflict_file = tmp_path / "conflict.py"
    conflict_file.write_text(
        "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> feature-branch\n",
        encoding="utf-8",
    )

    assert gu.has_conflict_markers(str(conflict_file))


def test_get_commit_count_returns_zero_on_missing_or_invalid_output(monkeypatch):
    monkeypatch.setattr(gu, "run_command", lambda *_a, **_k: (False, ""))
    assert gu.get_commit_count() == 0

    monkeypatch.setattr(gu, "run_command", lambda *_a, **_k: (True, "not-a-number"))
    assert gu.get_commit_count() == 0


def test_stage_files(monkeypatch):
    assert gu.stage_files([]) == (True, "")

    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]:
            return True, ""
        return True, "ok"

    monkeypatch.setattr(gu, "run_command", fake_run)
    ok, _ = gu.stage_files(["a.txt", "b.py"])
    assert ok
    assert calls[-1] == ["git", "add", "--", ":(literal)a.txt", ":(literal)b.py"]


def test_stage_deleted_files_uses_option_separator_and_literal_pathspecs(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append((cmd, show_output))
        return True, "ok"

    monkeypatch.setattr(gu, "run_command", fake_run)

    assert gu.stage_deleted_files([]) == (True, "")
    assert gu.stage_deleted_files(["-danger.txt", "folder/[draft].md"]) == (True, "ok")
    assert calls == [
        (
            [
                "git",
                "rm",
                "--ignore-unmatch",
                "--",
                ":(literal)-danger.txt",
                ":(literal)folder/[draft].md",
            ],
            False,
        )
    ]


def test_stage_files_rejects_unmerged_paths(monkeypatch):
    monkeypatch.setattr(
        gu,
        "run_command",
        lambda cmd, show_output=True: (
            (True, "a.py\nb.py\n")
            if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]
            else (True, "")
        ),
    )

    ok, err = gu.stage_files(["a.py"])

    assert ok is False
    assert "Çözülmemiş çakışmalar var" in err
    assert "a.py" in err


def test_assert_no_unmerged_files_exits_with_file_list(monkeypatch, capsys):
    monkeypatch.setattr(gu, "assert_no_unmerged_files", ORIGINAL_ASSERT_NO_UNMERGED_FILES)
    monkeypatch.setattr(
        gu, "get_unmerged_files", lambda: ["tests/smoke/test_install_verification.py"]
    )

    with pytest.raises(SystemExit) as exc_info:
        gu.assert_no_unmerged_files()

    assert exc_info.value.code == 1
    assert "tests/smoke/test_install_verification.py" in capsys.readouterr().out


def test_abort_in_progress_merge_and_rollback_tag_helpers(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    gu.abort_in_progress_merge()
    tag = gu.create_rollback_backup_tag()

    assert calls[0] == ["git", "merge", "--abort"]
    assert calls[1][:2] == ["git", "tag"]
    assert tag.startswith("backup/pre-rollback-")
    assert "Başarısız merge otomatik" in capsys.readouterr().out


def test_generate_upload_branch_name_is_timestamped_and_unique_prefix():
    name = gu.generate_upload_branch_name()
    assert name.startswith("sidar-upload/")
    assert len(name) == len("sidar-upload/") + 14  # YYYYMMDDHHMMSS


def test_create_and_checkout_upload_branch_success(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        gu, "run_command", lambda cmd, show_output=True: (calls.append(cmd), (True, ""))[1]
    )

    branch = gu.create_and_checkout_upload_branch("main")

    assert branch.startswith("sidar-upload/")
    assert calls == [["git", "checkout", "-b", branch]]
    assert "yeni bir dala alınıyor" in capsys.readouterr().out


def test_create_and_checkout_upload_branch_failure_exits(monkeypatch):
    monkeypatch.setattr(gu, "run_command", lambda cmd, show_output=True: (False, "boom"))

    with pytest.raises(SystemExit) as exc_info:
        gu.create_and_checkout_upload_branch("main")
    assert exc_info.value.code == 1


def test_resolve_owner_repo_handles_https_ssh_and_failure(monkeypatch):
    monkeypatch.setattr(
        gu,
        "run_command",
        lambda cmd, show_output=True: (True, "https://github.com/acme/widgets.git\n"),
    )
    assert gu.resolve_owner_repo() == "acme/widgets"

    monkeypatch.setattr(
        gu, "run_command", lambda cmd, show_output=True: (True, "git@github.com:acme/widgets.git")
    )
    assert gu.resolve_owner_repo() == "acme/widgets"

    monkeypatch.setattr(gu, "run_command", lambda cmd, show_output=True: (False, ""))
    assert gu.resolve_owner_repo() == ""

    monkeypatch.setattr(gu, "run_command", lambda cmd, show_output=True: (True, "not-a-github-url"))
    assert gu.resolve_owner_repo() == ""


class _FakeHTTPResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_create_pull_request_via_api_success(monkeypatch):
    monkeypatch.setattr(
        gu,
        "urlopen",
        lambda request, timeout=20: _FakeHTTPResponse(
            201, '{"number": 42, "html_url": "https://github.com/acme/widgets/pull/42"}'
        ),
    )

    success, info = gu.create_pull_request_via_api(
        "acme/widgets", "sidar-upload/x", "main", "title", "body", "tok"
    )

    assert success is True
    assert "#42" in info
    assert "pull/42" in info


def test_create_pull_request_via_api_missing_owner_repo():
    success, info = gu.create_pull_request_via_api("", "head", "main", "t", "b", "tok")
    assert success is False
    assert "owner/repo" in info


def test_create_pull_request_via_api_http_error(monkeypatch):
    def raise_http_error(request, timeout=20):
        raise gu.HTTPError("url", 422, "Unprocessable", None, None)

    monkeypatch.setattr(gu, "urlopen", raise_http_error)

    success, info = gu.create_pull_request_via_api("acme/widgets", "head", "main", "t", "b", "tok")
    assert success is False
    assert "422" in info


def test_create_pull_request_via_api_network_error(monkeypatch):
    def raise_url_error(request, timeout=20):
        raise gu.URLError("network down")

    monkeypatch.setattr(gu, "urlopen", raise_url_error)

    success, info = gu.create_pull_request_via_api("acme/widgets", "head", "main", "t", "b", "tok")
    assert success is False
    assert "erişilemedi" in info


def test_check_branch_protection_best_effort_true_false_unknown(monkeypatch):
    monkeypatch.setattr(gu, "urlopen", lambda request, timeout=20: _FakeHTTPResponse(200, "{}"))
    assert ORIGINAL_CHECK_BRANCH_PROTECTION_BEST_EFFORT("acme/widgets", "main", "tok") is True

    def raise_404(request, timeout=20):
        raise gu.HTTPError("url", 404, "Not Found", None, None)

    monkeypatch.setattr(gu, "urlopen", raise_404)
    assert ORIGINAL_CHECK_BRANCH_PROTECTION_BEST_EFFORT("acme/widgets", "main", "tok") is False

    def raise_network_error(request, timeout=20):
        raise gu.URLError("down")

    monkeypatch.setattr(gu, "urlopen", raise_network_error)
    assert ORIGINAL_CHECK_BRANCH_PROTECTION_BEST_EFFORT("acme/widgets", "main", "tok") is None

    assert ORIGINAL_CHECK_BRANCH_PROTECTION_BEST_EFFORT("", "main", "tok") is None


def test_create_draft_pr_best_effort_success_prints_pr_url(monkeypatch, capsys):
    monkeypatch.setattr(gu, "resolve_owner_repo", lambda: "acme/widgets")
    monkeypatch.setattr(gu, "resolve_github_token", lambda: "tok")
    monkeypatch.setattr(
        gu, "create_pull_request_via_api", lambda *a, **k: (True, "#7 https://x/pull/7")
    )

    ORIGINAL_CREATE_DRAFT_PR_BEST_EFFORT("sidar-upload/x", "9.9")

    assert "Draft PR oluşturuldu" in capsys.readouterr().out


def test_create_draft_pr_best_effort_failure_prints_manual_compare_link(monkeypatch, capsys):
    monkeypatch.setattr(gu, "resolve_owner_repo", lambda: "acme/widgets")
    monkeypatch.setattr(gu, "resolve_github_token", lambda: "tok")
    monkeypatch.setattr(gu, "create_pull_request_via_api", lambda *a, **k: (False, "boom"))

    ORIGINAL_CREATE_DRAFT_PR_BEST_EFFORT("sidar-upload/x", "9.9")

    out = capsys.readouterr().out
    assert "otomatik oluşturulamadı" in out
    assert "compare/main...sidar-upload/x" in out


def test_require_direct_main_confirmation_wrong_input_exits(monkeypatch):
    monkeypatch.setattr(gu, "check_branch_protection_best_effort", lambda *a, **k: False)
    monkeypatch.setattr("builtins.input", lambda _p="": "not direct main")

    with pytest.raises(SystemExit) as exc_info:
        gu.require_direct_main_confirmation("acme/widgets", "tok")
    assert exc_info.value.code == 1


def test_require_direct_main_confirmation_exact_phrase_proceeds(monkeypatch):
    monkeypatch.setattr(gu, "check_branch_protection_best_effort", lambda *a, **k: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "DIRECT-MAIN")

    gu.require_direct_main_confirmation("acme/widgets", "tok")  # must not raise


def test_report_auto_merge_changes_prints_changed_files(monkeypatch, capsys):
    monkeypatch.setattr(
        gu,
        "run_command",
        lambda cmd, show_output=True: (True, "remote.py\nlocal.md\n"),
    )

    gu.report_auto_merge_changes()

    out = capsys.readouterr().out
    assert "remote.py" in out
    assert "local.md" in out


def test_sync_install_manifests_before_commit_runs_sync_scripts_and_stages(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append((cmd, show_output))
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_SYNC_INSTALL_MANIFESTS_BEFORE_COMMIT()

    assert ok is True
    assert err == ""
    assert calls == [
        (["bash", "scripts/sync_install_module_hashes.sh"], False),
        (["bash", "scripts/sync_install_manifest.sh"], False),
        (["git", "add", "install_sidar.sh", ".sidar_manifest.txt"], False),
    ]


def test_sync_install_manifests_before_commit_stops_on_failure(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["bash", "scripts/sync_install_manifest.sh"]:
            return False, "manifest drift"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_SYNC_INSTALL_MANIFESTS_BEFORE_COMMIT()

    assert ok is False
    assert err == "manifest drift"
    assert calls == [
        ["bash", "scripts/sync_install_module_hashes.sh"],
        ["bash", "scripts/sync_install_manifest.sh"],
    ]


def test_ensure_full_git_history_skips_fetch_when_not_shallow(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "--is-shallow-repository"]:
            return True, "false"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_ENSURE_FULL_GIT_HISTORY_FOR_MANIFEST_CHECKS()

    assert ok is True
    assert err == ""
    assert calls == [["git", "rev-parse", "--is-shallow-repository"]]


def test_ensure_full_git_history_unshallows_when_shallow(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "--is-shallow-repository"]:
            return True, "true"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_ENSURE_FULL_GIT_HISTORY_FOR_MANIFEST_CHECKS()

    assert ok is True
    assert err == ""
    assert calls == [
        ["git", "rev-parse", "--is-shallow-repository"],
        ["git", "fetch", "--unshallow", "origin"],
    ]


def test_ensure_full_git_history_stops_on_unshallow_failure(monkeypatch):
    def fake_run(cmd, show_output=True):
        if cmd == ["git", "rev-parse", "--is-shallow-repository"]:
            return True, "true"
        if cmd == ["git", "fetch", "--unshallow", "origin"]:
            return False, "network error"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_ENSURE_FULL_GIT_HISTORY_FOR_MANIFEST_CHECKS()

    assert ok is False
    assert err == "network error"


def test_ensure_full_git_history_stops_when_shallow_check_fails(monkeypatch):
    monkeypatch.setattr(gu, "run_command", lambda cmd, show_output=True: (False, "no git"))

    ok, err = ORIGINAL_ENSURE_FULL_GIT_HISTORY_FOR_MANIFEST_CHECKS()

    assert ok is False
    assert err == "no git"


def test_run_pre_push_quality_gate_runs_format_then_lint(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True, extra_env=None):
        calls.append((cmd, show_output, extra_env))
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is True
    assert err == ""
    assert calls == [
        (["git", "rev-parse", "--is-shallow-repository"], False, None),
        (["uv", "run", "ruff", "format", "--check", "."], False, None),
        (["uv", "run", "ruff", "check", "."], False, None),
        (
            ["uv", "run", "pytest", "tests/unit", "-q", "--no-cov", "-x"],
            False,
            None,
        ),
        (["make", "installer-shellcheck"], False, None),
        (["sha256sum", "-c", ".sidar_manifest.txt"], False, None),
        (
            ["uv", "run", "python", "scripts/tools/update_core_install_manifest.py", "--check"],
            False,
            None,
        ),
        (
            [
                "uv",
                "run",
                "python",
                "scripts/tools/update_install_module_hash_manifest.py",
                "--target",
                "install_sidar.sh",
                "--check",
            ],
            False,
            None,
        ),
        (
            [
                "uv",
                "run",
                "python",
                "scripts/tools/update_install_module_hash_manifest.py",
                "--target",
                "install_sidar.sh",
                "--check-pin",
            ],
            False,
            None,
        ),
        (["bash", "-n", "install_sidar.sh"], False, None),
        (
            ["bash", "install_sidar.sh"],
            False,
            {"SIDAR_INSTALL_TEST_MODE": "1", "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1"},
        ),
        (
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "--no-cov",
                "tests/smoke/test_install_verification.py"
                "::test_install_sidar_embedded_manifests_in_sync",
            ],
            False,
            None,
        ),
    ]


def test_run_pre_push_quality_gate_stops_on_first_failure(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True, extra_env=None):
        calls.append(cmd)
        if cmd == ["uv", "run", "ruff", "format", "--check", "."]:
            return False, "Would reformat: bad.py"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is False
    assert "uv run ruff format --check ." in err
    assert "Would reformat: bad.py" in err
    assert "Düzeltmek için: uv run ruff format ." in err
    assert calls == [
        ["git", "rev-parse", "--is-shallow-repository"],
        ["uv", "run", "ruff", "format", "--check", "."],
    ]


def test_run_pre_push_quality_gate_stops_when_unit_tests_fail(monkeypatch):
    calls = []
    unit_command = ["uv", "run", "pytest", "tests/unit", "-q", "--no-cov", "-x"]

    def fake_run(cmd, show_output=True, extra_env=None):
        calls.append(cmd)
        if cmd == unit_command:
            return False, "1 failed"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is False
    assert "uv run pytest tests/unit -q --no-cov -x" in err
    assert "1 failed" in err
    assert calls[-1] == unit_command
    assert ["make", "installer-shellcheck"] not in calls


def test_run_pre_push_quality_gate_stops_on_installer_abort_smoke_failure(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True, extra_env=None):
        calls.append((cmd, extra_env))
        if cmd == ["bash", "install_sidar.sh"]:
            return False, "hash verify failed"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is False
    assert "bash install_sidar.sh" in err
    assert "hash verify failed" in err
    assert (
        ["bash", "install_sidar.sh"],
        {"SIDAR_INSTALL_TEST_MODE": "1", "SIDAR_INSTALL_ABORT_AFTER_HASH_VERIFY": "1"},
    ) in calls


def test_stamp_install_manifest_pin_after_commit_no_drift(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "HEAD"]:
            return True, "a" * 40
        if cmd == ["git", "diff", "--name-only", "--", "install_sidar.sh"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_STAMP_INSTALL_MANIFEST_PIN_AFTER_COMMIT()

    assert ok is True
    assert err == ""
    assert calls == [
        ["git", "rev-parse", "HEAD"],
        [
            "uv",
            "run",
            "python",
            "scripts/tools/update_install_module_hash_manifest.py",
            "--target",
            "install_sidar.sh",
            "--stamp-commit",
            "a" * 40,
        ],
        ["git", "diff", "--name-only", "--", "install_sidar.sh"],
    ]


def test_stamp_install_manifest_pin_after_commit_creates_fixup_commit_on_drift(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["git", "rev-parse", "HEAD"]:
            return True, "b" * 40
        if cmd == ["git", "diff", "--name-only", "--", "install_sidar.sh"]:
            return True, "install_sidar.sh"
        if cmd[:2] == ["git", "commit"]:
            return True, "fixup ok"
        return True, ""

    stage_calls = []
    monkeypatch.setattr(gu, "run_command", fake_run)
    monkeypatch.setattr(gu, "stage_files", lambda paths: (stage_calls.append(paths), (True, ""))[1])

    ok, err = ORIGINAL_STAMP_INSTALL_MANIFEST_PIN_AFTER_COMMIT()

    assert ok is True
    assert err == ""
    assert stage_calls == [["install_sidar.sh"]]
    commit_calls = [c for c in calls if c[:2] == ["git", "commit"]]
    assert len(commit_calls) == 1
    assert "b" * 40 in commit_calls[0][-1]


def test_stamp_install_manifest_pin_after_commit_stops_on_stamp_failure(monkeypatch):
    def fake_run(cmd, show_output=True):
        if cmd == ["git", "rev-parse", "HEAD"]:
            return True, "c" * 40
        if any("update_install_module_hash_manifest.py" in part for part in cmd):
            return False, "stamp failed"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_STAMP_INSTALL_MANIFEST_PIN_AFTER_COMMIT()

    assert ok is False
    assert err == "stamp failed"


def test_stamp_install_manifest_pin_after_commit_stops_on_fixup_commit_failure(monkeypatch):
    def fake_run(cmd, show_output=True):
        if cmd == ["git", "rev-parse", "HEAD"]:
            return True, "d" * 40
        if cmd == ["git", "diff", "--name-only", "--", "install_sidar.sh"]:
            return True, "install_sidar.sh"
        if cmd[:2] == ["git", "commit"]:
            return False, "commit failed"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)
    monkeypatch.setattr(gu, "stage_files", lambda paths: (True, ""))

    ok, err = ORIGINAL_STAMP_INSTALL_MANIFEST_PIN_AFTER_COMMIT()

    assert ok is False
    assert err == "commit failed"


def test_main_aborts_when_install_manifest_sync_fails(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))
    monkeypatch.setattr(gu, "sync_install_manifests_before_commit", lambda: (False, "sync failed"))

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
        ],
    )

    assert run_main_and_exit_code() == 1


class MainHarness:
    def __init__(self, monkeypatch, argv, outputs, inputs=None, cfg_token="tok", cfg_version="9.9"):
        self.inputs = list(inputs or [])
        self.calls = []
        gu.sys.argv = ["github_upload.py", *argv]
        monkeypatch.setattr(
            gu, "cfg", types.SimpleNamespace(GITHUB_TOKEN=cfg_token, VERSION=cfg_version)
        )
        self._outputs = list(outputs)

        def fake_run(cmd, show_output=True):
            self.calls.append(cmd)
            if not self._outputs:
                return True, ""
            return self._outputs.pop(0)

        monkeypatch.setattr(gu, "run_command", fake_run)
        import builtins

        monkeypatch.setattr(builtins, "input", lambda _p="": self.inputs.pop(0))


def run_main_and_exit_code():
    with pytest.raises(SystemExit) as e:
        gu.main()
    return e.value.code


def test_main_rejects_invalid_target_branch_name(monkeypatch):
    MainHarness(monkeypatch, ["release.lock"], outputs=[])
    assert run_main_and_exit_code() == 1


def test_main_invalid_rollback(monkeypatch):
    MainHarness(monkeypatch, ["-11"], outputs=[])
    assert run_main_and_exit_code() == 1


def test_main_missing_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    MainHarness(monkeypatch, [], outputs=[], cfg_token="")
    assert run_main_and_exit_code() == 1


def test_main_no_git_installed(monkeypatch):
    MainHarness(monkeypatch, [], outputs=[(False, "")])
    assert run_main_and_exit_code() == 1


def test_main_setup_identity_invalid_repo_url(monkeypatch):
    h = MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, ""),
            (True, ""),
            (True, ""),
            (True, ""),
            (True, ""),
        ],
        inputs=["me", "me@example.com", "http://invalid"],
    )
    assert run_main_and_exit_code() == 1
    assert ["git", "config", "--global", "user.name", "me"] in h.calls


def test_main_switch_to_main_checkout_fail_with_stash_pop(monkeypatch):
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin x"),
            (True, "dev"),
            (True, "M x"),
            (True, "stashed"),
            (False, "checkout fail"),
            (True, "pop"),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_switch_to_main_stash_pop_conflict(monkeypatch):
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "feature"),
            (True, "M file"),
            (True, "ok"),
            (True, "ok"),
            (False, "conflict"),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_rollback_rejects_when_not_enough_commits(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-2"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "2"),
        ],
        inputs=["yes"],
    )
    assert run_main_and_exit_code() == 1


def test_main_rollback_default_is_revert_not_force_push(monkeypatch):
    """Default rollback (-N without --force-rollback) uses `git revert`, never `--force`."""
    h = MainHarness(
        monkeypatch,
        ["-2"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "5"),
            (True, "reverted"),
            (False, "protected"),
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 1
    assert ["git", "revert", "--no-edit", "HEAD~2..HEAD"] in h.calls
    assert not any("--force" in call for call in h.calls if call[:2] == ["git", "push"])
    assert not any(call[:3] == ["git", "reset", "--hard"] for call in h.calls)


def test_main_rollback_cancel(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
        ],
        inputs=["hayır"],
    )
    assert run_main_and_exit_code() == 0


def test_main_pull_branch_conflict(monkeypatch):
    MainHarness(
        monkeypatch,
        ["remote-branch"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (False, "fatal conflict"),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_add_failure(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda paths: (False, "nope"))
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_aborts_when_deleted_files_cannot_be_staged(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: ["-danger.txt"])
    monkeypatch.setattr(gu, "stage_deleted_files", lambda _paths: (False, "git rm rejected path"))
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
        ],
        inputs=["yes"],
    )

    assert run_main_and_exit_code() == 1


def test_main_nothing_to_push_exits(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, ""),
            (True, " M x"),
            (True, ""),
        ],
    )
    assert run_main_and_exit_code() == 0


def test_main_commit_fail(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(
        gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], [".env"])
    )
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (False, "commit err"),
        ],
        inputs=[""],
    )
    assert run_main_and_exit_code() == 1


def test_main_aborts_when_pin_stamp_fails_after_commit(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))
    monkeypatch.setattr(
        gu, "stamp_install_manifest_pin_after_commit", lambda: (False, "stamp failed")
    )

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
            (True, "A a.py"),
            (True, "commit ok"),
        ],
        inputs=["commit msg"],
    )

    assert run_main_and_exit_code() == 1


def test_main_aborts_when_pre_push_quality_gate_fails(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))
    monkeypatch.setattr(
        gu,
        "run_pre_push_quality_gate",
        lambda: (False, "uv run ruff format --check .\nWould reformat: a.py"),
    )

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
            (True, "A a.py"),
            (True, "commit ok"),
        ],
        inputs=["commit msg"],
    )

    assert run_main_and_exit_code() == 1


def test_main_push_rejected_then_merge_then_retry_fail_rule(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: ["old.txt"])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "ok"),
            (True, "A a.py"),
            (True, "ok"),
            (False, "rejected"),
            (True, "merge made"),
            (False, "rule violations"),
        ],
        inputs=["yes", "msg", "y"],
    )
    gu.main()


def test_main_push_rejected_merge_fail_or_cancel_and_unknown_error(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))

    # cancel auto-merge
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "fetch first"),
        ],
        inputs=["m", "n"],
    )
    gu.main()

    # merge command fails (real conflict; fail-closed abort, no -X ours)
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "non-fast-forward"),
            (False, "CONFLICT (content): fatal"),
            (True, ""),  # print_unmerged_files -> get_unmerged_files
            (True, ""),  # abort_in_progress_merge -> git merge --abort
        ],
        inputs=["m", "y"],
    )
    assert run_main_and_exit_code() == 1

    # unknown push error
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "boom"),
        ],
        inputs=["m"],
    )
    gu.main()


def test_main_happy_path_with_new_repo_and_deleted_decline(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: ["gone.py"])
    monkeypatch.setattr(
        gu, "collect_safe_files", lambda deleted_files_list=None: (["x.py"], [".env"])
    )
    monkeypatch.setattr(gu, "stage_files", lambda paths: (True, ""))
    monkeypatch.setattr(gu.os.path, "exists", lambda p: False if p == ".git" else True)

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, ""),
            (True, ""),
            (True, ""),
            (True, "main"),
            (True, ""),
            (True, "A x.py"),
            (True, "commit ok"),
            (True, "push ok"),
        ],
        inputs=["https://github.com/test/repo", "hayır", "manual commit"],
    )
    gu.main()


def test_run_command_silent_branches(monkeypatch):
    class Result:
        stdout = "   "
        stderr = ""

    monkeypatch.setattr(gu.subprocess, "run", lambda *a, **k: Result())
    assert gu.run_command(["git"], show_output=False) == (True, "")

    def fail(*_a, **_k):
        raise gu.subprocess.CalledProcessError(1, ["git"], output="", stderr="")

    monkeypatch.setattr(gu.subprocess, "run", fail)
    assert gu.run_command(["git"], show_output=False) == (False, "")


def test_get_deleted_files_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(gu, "run_command", lambda *_a, **_k: (False, ""))
    assert gu.get_deleted_files() == []


def test_collect_safe_files_default_and_directory_skip(monkeypatch, tmp_path):
    dir_path = tmp_path / "folder"
    dir_path.mkdir()
    bin_file = tmp_path / "img.bin"
    bin_file.write_bytes(b"\x00\x01")

    monkeypatch.setattr(
        gu,
        "run_command",
        lambda *_a, **_k: (True, f"\n{dir_path}\n{bin_file}\n"),
    )
    safe, blocked = gu.collect_safe_files()
    assert str(bin_file) in safe
    assert blocked == []


def test_main_switch_to_main_stash_creation_fails(monkeypatch):
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "dev"),
            (True, "M a"),
            (False, "stash err"),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_switch_to_main_success_without_stash(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "feature"),
            (True, ""),
            (True, "ok"),
            (True, "https://github.com/test/repo.git"),  # resolve_owner_repo (direct-main confirm)
            (True, ""),
            (True, ""),
            (True, "unpushed"),
            (True, "push"),
        ],
        inputs=["DIRECT-MAIN"],
    )
    gu.main()


def test_main_rollback_revert_conflict_aborts(monkeypatch):
    h = MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "3"),
            (False, "CONFLICT: revert fail"),
            (True, ""),  # git revert --abort
        ],
        inputs=["yes"],
    )

    with pytest.raises(SystemExit) as exc_info:
        gu.main()
    assert ["git", "revert", "--abort"] in h.calls

    assert exc_info.value.code == 1


def test_main_target_branch_merge_made_commit_default_message(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda paths: (True, ""))

    h = MainHarness(
        monkeypatch,
        ["feature-x"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (False, "merge made"),
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (True, "ok"),
        ],
        inputs=[""],
    )
    gu.main()
    commit_cmd = [c for c in h.calls if c[:3] == ["git", "commit", "-m"]][0]
    assert "Merged branch: feature-x" in commit_cmd[3]


def test_main_retry_push_failure_non_rule_violations(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "rejected"),
            (True, "up to date"),
            (False, "some other err"),
        ],
        inputs=["msg", "y"],
    )
    gu.main()


def test_main_retry_push_success(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda _paths: (True, ""))

    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "fetch first"),
            (True, "ok"),
            (True, "ok"),
        ],
        inputs=["msg", "y"],
    )
    gu.main()


def test_main_checkout_fail_without_stash(monkeypatch):
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "dev"),
            (True, ""),
            (False, "fail"),
        ],
    )
    assert run_main_and_exit_code() == 1


def test_main_switch_to_main_with_stash_pop_success(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    MainHarness(
        monkeypatch,
        ["--direct-main"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "feature"),
            (True, "M x"),
            (True, "stashed"),
            (True, "checkout"),
            (True, "pop"),
            (True, "https://github.com/test/repo.git"),  # resolve_owner_repo (direct-main confirm)
            (True, ""),
            (True, ""),
            (True, "unpushed"),
            (True, "pushed"),
        ],
        inputs=["DIRECT-MAIN"],
    )
    gu.main()


def test_main_no_staged_status_and_clean_worktree_but_unpushed(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    guard_order = []
    monkeypatch.setattr(
        gu,
        "stamp_install_manifest_pin_after_commit",
        lambda: (guard_order.append("stamp"), (True, ""))[1],
    )
    monkeypatch.setattr(
        gu,
        "run_pre_push_quality_gate",
        lambda: (guard_order.append("gate"), (True, ""))[1],
    )
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, ""),
            (True, ""),
            (True, ""),
            (True, "commit1"),
            (True, "push ok"),
        ],
    )
    gu.main()
    assert guard_order == ["stamp", "gate"]


def test_main_aborts_before_gate_when_unpushed_pin_repair_fails(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: ([], []))
    monkeypatch.setattr(
        gu, "stamp_install_manifest_pin_after_commit", lambda: (False, "unreachable pin")
    )
    gate_calls = []
    monkeypatch.setattr(
        gu, "run_pre_push_quality_gate", lambda: (gate_calls.append(True), (True, ""))[1]
    )
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "checkout ok"),  # git checkout -b <upload branch>
            (True, ""),
            (True, ""),
            (True, ""),
            (True, "commit1"),
        ],
    )

    assert run_main_and_exit_code() == 1
    assert gate_calls == []


def test_main_rollback_revert_push_success(monkeypatch):
    h = MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "2"),
            (True, "reverted"),
            (True, "push ok"),
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 0
    assert ["git", "revert", "--no-edit", "HEAD~1..HEAD"] in h.calls
    assert ["git", "push", "origin", "main"] in h.calls


def test_main_force_rollback_requires_force_rollback_steps(monkeypatch):
    """`--force-rollback` without -N is a usage error, not a silent no-op."""
    MainHarness(monkeypatch, ["--force-rollback"], outputs=[])
    assert run_main_and_exit_code() == 1


def test_main_force_rollback_wrong_sha_cancels_without_destructive_action(monkeypatch):
    h = MainHarness(
        monkeypatch,
        ["-1", "--force-rollback"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "2"),
            (True, "deadbeefcafe"),  # git rev-parse HEAD
        ],
        inputs=["evet", "not-the-real-sha"],
    )
    assert run_main_and_exit_code() == 1
    assert not any(call[:3] == ["git", "reset", "--hard"] for call in h.calls)
    assert not any("--force" in call for call in h.calls if call[:2] == ["git", "push"])


def test_main_force_rollback_exact_sha_confirms_reset_and_force_push(monkeypatch):
    h = MainHarness(
        monkeypatch,
        ["-1", "--force-rollback"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "2"),
            (True, "deadbeefcafe"),  # git rev-parse HEAD
            (True, "tag ok"),  # create_rollback_backup_tag
            (True, "reset ok"),
            (True, "push ok"),
        ],
        inputs=["evet", "deadbeefcafe"],
    )
    assert run_main_and_exit_code() == 0
    assert ["git", "reset", "--hard", "HEAD~1"] in h.calls
    assert ["git", "push", "--force", "origin", "main"] in h.calls
