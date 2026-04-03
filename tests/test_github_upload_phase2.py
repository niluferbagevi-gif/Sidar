from __future__ import annotations

import subprocess

import github_upload


def test_run_command_collects_stdout_on_failure(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git"], stderr="err", output="out")

    monkeypatch.setattr(github_upload.subprocess, "run", _raise)

    ok, output = github_upload.run_command(["git", "status"], show_output=False)
    assert ok is False
    assert "err" in output
    assert "out" in output


def test_collect_safe_files_marks_unreadable_as_blocked(monkeypatch):
    def _fake_run(args, show_output=False):
        _ = show_output
        if args[:3] == ["git", "ls-files", "-co"]:
            return True, "safe.py\nlogs/app.log\nnotes.bin\n"
        return True, ""

    monkeypatch.setattr(github_upload, "run_command", _fake_run)
    monkeypatch.setattr(github_upload.os.path, "isdir", lambda _path: False)
    monkeypatch.setattr(github_upload, "get_file_content", lambda path: None if path.endswith(".bin") else "ok")

    safe, blocked = github_upload.collect_safe_files(deleted_files_list=[])

    assert "safe.py" in safe
    assert "logs/app.log" in blocked
    assert "notes.bin" in safe


def test_get_deleted_files_handles_failure(monkeypatch):
    monkeypatch.setattr(github_upload, "run_command", lambda *_args, **_kwargs: (False, "fatal"))
    assert github_upload.get_deleted_files() == []
