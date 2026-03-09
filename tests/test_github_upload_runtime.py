import importlib.util
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path


class _Cfg:
    GITHUB_TOKEN = "token"
    VERSION = "2.0"


@contextmanager
def _temporary_config_module(config_module):
    prev = sys.modules.get("config")
    sys.modules["config"] = config_module
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def _load_module():
    cfg_mod = types.ModuleType("config")
    cfg_mod.Config = lambda: _Cfg()
    with _temporary_config_module(cfg_mod):
        spec = importlib.util.spec_from_file_location("github_upload_under_test", Path("github_upload.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def test_helpers_path_validation_and_file_read(tmp_path):
    GU = _load_module()
    assert GU._is_valid_repo_url("https://github.com/a/b") is True
    assert GU._is_valid_repo_url("git@github.com:a/b.git") is True
    assert GU._is_valid_repo_url("http://bad") is False

    assert GU._normalize_path("./a\\b") == "a/b"
    assert GU.is_forbidden_path("sessions/data.json") is True
    assert GU.is_forbidden_path("safe/file.txt") is False

    f = tmp_path / "ok.txt"
    f.write_text("hello", encoding="utf-8")
    assert GU.get_file_content(str(f)) == "hello"


def test_run_command_success_and_failure(monkeypatch):
    GU = _load_module()
    class _Res:
        stdout = "ok\n"
        stderr = ""

    monkeypatch.setattr(GU.subprocess, "run", lambda *a, **k: _Res())
    ok, out = GU.run_command(["git", "status"])
    assert ok is True and out == "ok"

    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output="x", stderr="err")

    monkeypatch.setattr(GU.subprocess, "run", _raise)
    ok, out = GU.run_command(["git", "status"], show_output=False)
    assert ok is False and "err" in out


def test_collect_safe_files_filters_forbidden_and_binary(monkeypatch, tmp_path):
    GU = _load_module()
    good = tmp_path / "a.txt"
    good.write_text("hi", encoding="utf-8")
    bad = tmp_path / "sessions" / "secret.txt"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("x", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (True, "a.txt\nsessions/secret.txt\n"))

    safe, blocked = GU.collect_safe_files()
    assert "a.txt" in safe
    assert "sessions/secret.txt" in blocked


def test_main_flow_no_changes_and_invalid_repo(monkeypatch):
    GU = _load_module()
    # no token path
    GU.cfg.GITHUB_TOKEN = ""
    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 1

    GU.cfg.GITHUB_TOKEN = "token"

    calls = []

    def _fake_run(args, show_output=False):
        calls.append(tuple(args))
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, ""
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "init"]:
            return True, ""
        if args[:2] == ["git", "branch"]:
            return True, ""
        if args[:3] == ["git", "remote", "add"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: ([], []))
    monkeypatch.setattr("builtins.input", lambda _p: "bad-url")

    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 1


def test_main_push_conflict_branches(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    state = {"push_count": 0}

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "add"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:2] == ["git", "commit"]:
            return True, "ok"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            state["push_count"] += 1
            if state["push_count"] == 1:
                return False, "rejected fetch first"
            return True, "ok"
        if args[:2] == ["git", "pull"]:
            return True, "merge made"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))

    seq = iter(["", "y"])  # empty commit message -> default, then auto-merge yes
    monkeypatch.setattr("builtins.input", lambda _p: next(seq))
    GU.main()
    assert state["push_count"] == 2


def test_main_prompts_for_missing_git_identity_and_sets_global_config(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"
    seen = []

    def _fake_run(args, show_output=False):
        seen.append(tuple(args))
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, ""
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "add"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:2] == ["git", "commit"]:
            return True, "ok"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            return True, "ok"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: ([], []))

    answers = iter(["Dev User", "dev@example.com", "initial commit"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))

    GU.main()

    assert ("git", "config", "--global", "user.name", "Dev User") in seen
    assert ("git", "config", "--global", "user.email", "dev@example.com") in seen


def test_main_push_conflict_cancelled_by_user(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "add"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:2] == ["git", "commit"]:
            return True, "ok"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            return False, "non-fast-forward"
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))
    answers = iter(["commit msg", "n"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))

    GU.main()



def test_main_push_conflict_accepts_merge_and_retries_push(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"
    state = {"push": 0, "pull": 0}

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "add"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:2] == ["git", "commit"]:
            return True, "ok"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            state["push"] += 1
            if state["push"] == 1:
                return False, "rejected fetch first"
            return True, "ok"
        if args[:2] == ["git", "pull"]:
            state["pull"] += 1
            return True, "merge made"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))

    answers = iter(["commit msg", "Y"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))

    GU.main()
    assert state["pull"] == 1
    assert state["push"] == 2


def test_main_exits_when_git_missing(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    monkeypatch.setattr(GU, "run_command", lambda args, show_output=False: (False, "missing") if args[:2] == ["git", "--version"] else (True, ""))

    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 1