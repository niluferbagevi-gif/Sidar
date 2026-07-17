import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import types

import pytest

import github_upload as gu

ORIGINAL_SYNC_INSTALL_MANIFESTS_BEFORE_COMMIT = gu.sync_install_manifests_before_commit
ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE = gu.run_pre_push_quality_gate
ORIGINAL_ASSERT_NO_UNMERGED_FILES = gu.assert_no_unmerged_files


@pytest.fixture(autouse=True)
def _stub_upload_guards(monkeypatch):
    monkeypatch.setattr(gu, "sync_install_manifests_before_commit", lambda: (True, ""))
    monkeypatch.setattr(gu, "run_pre_push_quality_gate", lambda: (True, ""))
    monkeypatch.setattr(gu, "assert_no_unmerged_files", lambda: None)


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


def test_report_ours_strategy_changes_prints_changed_files(monkeypatch, capsys):
    monkeypatch.setattr(
        gu,
        "run_command",
        lambda cmd, show_output=True: (True, "remote.py\nlocal.md\n"),
    )

    gu.report_ours_strategy_changes()

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


def test_run_pre_push_quality_gate_runs_format_then_lint(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append((cmd, show_output))
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is True
    assert err == ""
    assert calls == [
        (["uv", "run", "ruff", "format", "--check", "."], False),
        (["uv", "run", "ruff", "check", "."], False),
    ]


def test_run_pre_push_quality_gate_stops_on_first_failure(monkeypatch):
    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd == ["uv", "run", "ruff", "format", "--check", "."]:
            return False, "Would reformat: bad.py"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)

    ok, err = ORIGINAL_RUN_PRE_PUSH_QUALITY_GATE()

    assert ok is False
    assert "uv run ruff format --check ." in err
    assert "Would reformat: bad.py" in err
    assert calls == [["uv", "run", "ruff", "format", "--check", "."]]


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
        [],
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
        [],
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


def test_main_rollback_yes_push_fail(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-2"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "5"),
            (True, "reset ok"),
            (False, "protected"),
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 1


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
            (True, ""),
            (True, "A a.py"),
            (False, "commit err"),
        ],
        inputs=[""],
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
            (True, ""),
            (True, "A a.py"),
            (True, "ok"),
            (False, "fetch first"),
        ],
        inputs=["m", "n"],
    )
    gu.main()

    # merge command fails
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
            (True, "ok"),
            (False, "non-fast-forward"),
            (False, "fatal"),
        ],
        inputs=["m", "y"],
    )
    gu.main()

    # unknown push error
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
        [],
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
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "feature"),
            (True, ""),
            (True, "ok"),
            (True, ""),
            (True, ""),
            (True, "unpushed"),
            (True, "push"),
        ],
    )
    gu.main()


def test_main_rollback_reset_fail(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "3"),
            (False, "reset fail"),
        ],
        inputs=["yes"],
    )

    with pytest.raises(SystemExit) as exc_info:
        gu.main()

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
        [],
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
        [],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "feature"),
            (True, "M x"),
            (True, "stashed"),
            (True, "checkout"),
            (True, "pop"),
            (True, ""),
            (True, ""),
            (True, "unpushed"),
            (True, "pushed"),
        ],
    )
    gu.main()


def test_main_no_staged_status_and_clean_worktree_but_unpushed(monkeypatch):
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
            (True, ""),
            (True, ""),
            (True, ""),
            (True, "commit1"),
            (True, "push ok"),
        ],
    )
    gu.main()


def test_main_rollback_push_success(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "2"),
            (True, "reset ok"),
            (True, "push ok"),
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 0
