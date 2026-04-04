from __future__ import annotations

import sys

import pytest

import github_upload


def _base_env(monkeypatch, argv: list[str] | None = None) -> None:
    monkeypatch.setattr(github_upload.cfg, "GITHUB_TOKEN", "token", raising=False)
    monkeypatch.setattr(github_upload.cfg, "VERSION", "2.1", raising=False)
    monkeypatch.setattr(github_upload.os.path, "exists", lambda p: True)
    monkeypatch.setattr(sys, "argv", argv or ["github_upload.py"])


def test_main_exits_for_invalid_rollback_range(monkeypatch):
    _base_env(monkeypatch, ["github_upload.py", "-11"])

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_exits_when_github_token_missing(monkeypatch):
    monkeypatch.setattr(github_upload.cfg, "GITHUB_TOKEN", "", raising=False)
    monkeypatch.setattr(sys, "argv", ["github_upload.py"])

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_exits_when_git_not_installed(monkeypatch):
    _base_env(monkeypatch)

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return False, "not found"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_invalid_remote_url_aborts(monkeypatch):
    _base_env(monkeypatch)

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "invalid-url")

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_branch_switch_checkout_failure_restores_stash(monkeypatch):
    _base_env(monkeypatch)
    calls: list[list[str]] = []

    def _fake_run(args, show_output=True):
        calls.append(args)
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "feature"
        if args == ["git", "status", "--porcelain"]:
            return True, " M a.py"
        if args[:4] == ["git", "stash", "push", "-u"]:
            return True, "saved"
        if args == ["git", "checkout", "main"]:
            return False, "conflict"
        if args == ["git", "stash", "pop"]:
            return True, "restored"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1
    assert ["git", "stash", "pop"] in calls


def test_main_rollback_confirmed_reset_failure(monkeypatch):
    _base_env(monkeypatch, ["github_upload.py", "-2"])

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:3] == ["git", "reset", "--hard"]:
            return False, "reset failed"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "evet")

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_rollback_cancelled_exits_zero(monkeypatch):
    _base_env(monkeypatch, ["github_upload.py", "-1"])

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "hayir")

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 0


def test_main_stage_files_failure_exits(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setattr(github_upload, "get_deleted_files", lambda: [])
    monkeypatch.setattr(github_upload, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(github_upload, "stage_files", lambda _files: (False, "git add failed"))

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args == ["git", "reset"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)

    with pytest.raises(SystemExit) as exc:
        github_upload.main()

    assert exc.value.code == 1


def test_main_push_rejected_user_declines_auto_merge(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setattr(github_upload, "get_deleted_files", lambda: [])
    monkeypatch.setattr(github_upload, "collect_safe_files", lambda deleted_files_list=None: ([], []))

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args == ["git", "reset"]:
            return True, ""
        if args == ["git", "diff", "--cached", "--name-status"]:
            return True, "M a.py"
        if args[:3] == ["git", "commit", "-m"]:
            return True, "ok"
        if args == ["git", "push", "-u", "origin", "main"]:
            return False, "rejected"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    answers = iter(["", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    github_upload.main()


def test_main_push_retry_rule_violations_branch(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setattr(github_upload, "get_deleted_files", lambda: [])
    monkeypatch.setattr(github_upload, "collect_safe_files", lambda deleted_files_list=None: ([], []))

    push_count = {"n": 0}

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/o/r.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args == ["git", "reset"]:
            return True, ""
        if args == ["git", "diff", "--cached", "--name-status"]:
            return True, "M a.py"
        if args[:3] == ["git", "commit", "-m"]:
            return True, "ok"
        if args == ["git", "push", "-u", "origin", "main"]:
            push_count["n"] += 1
            if push_count["n"] == 1:
                return False, "non-fast-forward"
            return False, "rule violations"
        if args[:3] == ["git", "pull", "origin"]:
            return True, "merge made"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    answers = iter(["", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    github_upload.main()
    assert push_count["n"] == 2
