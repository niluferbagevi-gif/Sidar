from __future__ import annotations

import subprocess

import github_upload


def test_run_command_returns_combined_error_output(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["git", "push"],
            output="stdout-part",
            stderr="stderr-part",
        )

    monkeypatch.setattr(github_upload.subprocess, "run", _raise)

    ok, output = github_upload.run_command(["git", "push"], show_output=False)
    assert ok is False
    assert "stderr-part" in output
    assert "stdout-part" in output


def test_get_deleted_files_and_stage_files_literal_paths(monkeypatch):
    calls = []

    def _fake_run(args, show_output=True):
        calls.append(args)
        if args[:3] == ["git", "ls-files", "-d"]:
            return True, "a.py\n\n b.py\n"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)

    deleted = github_upload.get_deleted_files()
    assert deleted == ["a.py", "b.py"]

    github_upload.stage_files(["src/main.py", "docs/read me.md"])
    assert calls[-1] == [
        "git",
        "add",
        "--",
        ":(literal)src/main.py",
        ":(literal)docs/read me.md",
    ]


def test_collect_safe_files_returns_empty_when_git_ls_files_fails(monkeypatch):
    monkeypatch.setattr(github_upload, "run_command", lambda *_args, **_kwargs: (False, "fatal"))
    safe, blocked = github_upload.collect_safe_files([])
    assert safe == []
    assert blocked == []
