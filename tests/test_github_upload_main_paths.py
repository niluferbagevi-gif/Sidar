from __future__ import annotations

import sys

import github_upload


def test_main_exits_when_target_branch_merge_fails(monkeypatch) -> None:
    monkeypatch.setattr(github_upload.cfg, "GITHUB_TOKEN", "token", raising=False)
    monkeypatch.setattr(github_upload.os.path, "exists", lambda p: True)
    monkeypatch.setattr(sys, "argv", ["github_upload.py", "feature/broken"])

    calls: list[list[str]] = []

    def _fake_run(args, show_output=True):
        calls.append(args)
        if args == ["git", "--version"]:
            return True, "git version 2.x"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:3] == ["git", "pull", "origin"]:
            return False, "merge conflict"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    try:
        github_upload.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("main() merge hatasında SystemExit(1) vermeliydi")

    assert ["git", "pull", "origin", "feature/broken", "--no-rebase", "--allow-unrelated-histories", "--no-edit"] in calls


def test_main_retries_push_after_remote_reject_and_merge(monkeypatch) -> None:
    monkeypatch.setattr(github_upload.cfg, "GITHUB_TOKEN", "token", raising=False)
    monkeypatch.setattr(github_upload.cfg, "VERSION", "9.9.9", raising=False)
    monkeypatch.setattr(github_upload.os.path, "exists", lambda p: True)
    monkeypatch.setattr(sys, "argv", ["github_upload.py"])
    monkeypatch.setattr(github_upload, "get_deleted_files", lambda: [])
    monkeypatch.setattr(github_upload, "collect_safe_files", lambda deleted_files_list=None: ([], []))

    push_attempts = {"count": 0}

    def _fake_run(args, show_output=True):
        if args == ["git", "--version"]:
            return True, "git version 2.x"
        if args == ["git", "config", "user.name"]:
            return True, "sidar"
        if args == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo.git (fetch)"
        if args == ["git", "branch", "--show-current"]:
            return True, "main"
        if args == ["git", "reset"]:
            return True, ""
        if args == ["git", "diff", "--cached", "--name-status"]:
            return True, "M core/db.py"
        if args[:3] == ["git", "commit", "-m"]:
            return True, "[main] commit ok"
        if args == ["git", "push", "-u", "origin", "main"]:
            push_attempts["count"] += 1
            if push_attempts["count"] == 1:
                return False, "rejected non-fast-forward"
            return True, "pushed"
        if args[:3] == ["git", "pull", "origin"]:
            return True, "merge made"
        if args == ["git", "log", "origin/main..HEAD"]:
            return False, ""
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)

    answers = iter(["", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    github_upload.main()

    assert push_attempts["count"] == 2
