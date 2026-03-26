import importlib.util
import runpy
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest


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


def test_collect_deleted_files_returns_git_deleted_list(monkeypatch):
    GU = _load_module()
    monkeypatch.setattr(
        GU, "run_command", lambda *a, **k: (True, "old.txt\nnested/removed.py\n")
    )
    assert GU.collect_deleted_files() == ["old.txt", "nested/removed.py"]


def test_collect_tracked_ignored_files_returns_conflicts(monkeypatch):
    GU = _load_module()
    monkeypatch.setattr(
        GU, "run_command", lambda *a, **k: (True, "sidar_project.egg-info/PKG-INFO\n.env.local\n")
    )
    assert GU.collect_tracked_ignored_files() == [
        "sidar_project.egg-info/PKG-INFO",
        ".env.local",
    ]


def test_main_stages_deleted_files_with_explicit_pathspec(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"
    seen = []

    def _fake_run(args, show_output=False):
        seen.append(tuple(args))
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "D old.txt"
        if args[:2] == ["git", "commit"]:
            return True, "ok"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            return True, "ok"
        if args[:3] == ["git", "ls-files", "-d"]:
            return True, "old.txt"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: ([], []))
    monkeypatch.setattr("builtins.input", lambda _p: "sync deletes")

    GU.main()

    assert ("git", "add", "-u", "--", "old.txt") in seen


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
        if args[:3] == ["git", "ls-files", "-d"]:
            return True, ""
        if args[:4] == ["git", "ls-files", "-ci", "--exclude-standard"]:
            return True, ""
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



def test_github_upload_all_edge_cases(monkeypatch, tmp_path):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    # güvenli dosya filtresi
    (tmp_path / "valid.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "x.txt").write_text("secret", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (True, "valid.py\nsessions/x.txt\n"))
    safe, blocked = GU.collect_safe_files()
    assert "valid.py" in safe
    assert "sessions/x.txt" in blocked

    # interaction + conflict accept
    state = {"push": 0}

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, ""
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] in (["git", "reset"], ["git", "add"], ["git", "commit"]):
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M valid.py"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            state["push"] += 1
            return (False, "rejected fetch first") if state["push"] == 1 else (True, "ok")
        if args[:2] == ["git", "pull"]:
            return True, "merge made"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["valid.py"], []))
    answers = iter(["Test User", "test@example.com", "Test commit", "Y"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    GU.main()
    assert state["push"] == 2


def test_github_upload_empty_commit_and_no_remote(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, ""
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: ([], []))
    monkeypatch.setattr("builtins.input", lambda _p: "")

    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 1


def test_runtime_helper_error_branches(monkeypatch, tmp_path):
    GU = _load_module()

    # run_command: show_output=True + stderr branch
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))

    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], output="out", stderr="err")

    monkeypatch.setattr(GU.subprocess, "run", _raise)
    ok, out = GU.run_command(["git", "status"], show_output=True)
    assert ok is False and "err" in out
    assert any("Git çıktısı" in p for p in printed)

    # get_file_content: forbidden + decode/os errors
    assert GU.get_file_content("sessions/secret.txt") is None

    bin_file = tmp_path / "bad.bin"
    bin_file.write_bytes(b"\xff\xfe")
    assert GU.get_file_content(str(bin_file)) is None

    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert GU.get_file_content("safe.txt") is None

    # collect_safe_files: git ls-files failure
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (False, "x"))
    safe, blocked = GU.collect_safe_files()
    assert safe == [] and blocked == []


def test_collect_safe_files_skips_empty_dirs_and_unreadable(monkeypatch, tmp_path):
    GU = _load_module()
    (tmp_path / "ok.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "dir1").mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (True, "\ndir1\nok.txt\nblocked.txt\n"))
    monkeypatch.setattr(GU, "get_file_content", lambda p: "hello" if p == "ok.txt" else None)

    safe, blocked = GU.collect_safe_files()
    assert safe == ["ok.txt"]
    assert "blocked.txt" in blocked


def test_main_branches_for_repo_init_blocked_no_status_and_commit_fail(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"
    calls = []

    def _fake_run(args, show_output=False):
        calls.append(tuple(args))
        if args[:2] == ["git", "--version"]:
            return True, "git"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, ""
        if args[:3] == ["git", "remote", "add"]:
            return True, ""
        if args[:2] == ["git", "init"]:
            return True, ""
        if args[:3] == ["git", "branch", "-M"]:
            return True, ""
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, ""
        if args[:2] == ["git", "commit"]:
            return False, "commit fail"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda p: False)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], ["blocked.txt"]))
    answers = iter(["https://github.com/a/b"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))

    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 0

    # commit-fail path
    monkeypatch.setattr(GU.os.path, "exists", lambda p: True)

    def _fake_run2(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git"
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
            return False, "commit fail"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run2)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))
    monkeypatch.setattr("builtins.input", lambda _p: "msg")
    try:
        GU.main()
        assert False
    except SystemExit as exc:
        assert exc.code == 1


def test_main_push_retry_failure_and_unknown_push_error(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    def _common(args):
        if args[:2] == ["git", "--version"]:
            return True, "git"
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
        return None

    # merge success but retry push rule-violations
    state = {"push": 0}

    def _fake_run(args, show_output=False):
        base = _common(args)
        if base is not None:
            return base
        if args[:2] == ["git", "push"]:
            state["push"] += 1
            if state["push"] == 1:
                return False, "rejected fetch first"
            return False, "rule violations"
        if args[:2] == ["git", "pull"]:
            return True, "merge made"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))
    answers = iter(["msg", "y"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    GU.main()

    # merge fail prints pull command/error + unknown push error path
    def _fake_run2(args, show_output=False):
        base = _common(args)
        if base is not None:
            return base
        if args[:2] == ["git", "push"]:
            return False, "fatal push error"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run2)
    monkeypatch.setattr("builtins.input", lambda _p: "msg")
    GU.main()


def test_github_upload_dunder_main_keyboard_interrupt(monkeypatch):
    cfg_mod = types.ModuleType("config")
    cfg_mod.Config = lambda: _Cfg()

    with _temporary_config_module(cfg_mod):
        monkeypatch.setattr("builtins.input", lambda _p: (_ for _ in ()).throw(KeyboardInterrupt))
        try:
            runpy.run_path("github_upload.py", run_name="__main__")
            assert False
        except SystemExit as exc:
            assert exc.code == 0


def test_github_upload_dunder_main_keyboard_interrupt_prints_cancel(monkeypatch, capsys):
    cfg_mod = types.ModuleType("config")
    cfg_mod.Config = lambda: _Cfg()

    def _raise_keyboard_interrupt(*_a, **_k):
        raise KeyboardInterrupt

    with _temporary_config_module(cfg_mod):
        monkeypatch.setattr(subprocess, "run", _raise_keyboard_interrupt)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path("github_upload.py", run_name="__main__")

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "İşlem kullanıcı tarafından iptal edildi" in out

def test_main_push_conflict_merge_fails(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] in (["git", "reset"], ["git", "add"], ["git", "commit"]):
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            return False, "rejected fetch first"
        if args[:2] == ["git", "pull"]:
            return False, "fatal error during merge"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))
    answers = iter(["msg", "y"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    GU.main()


def test_main_push_conflict_merge_success_but_retry_push_fails(monkeypatch):
    GU = _load_module()
    GU.cfg.GITHUB_TOKEN = "token"
    state = {"push": 0}

    def _fake_run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "dev"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin"
        if args[:2] in (["git", "reset"], ["git", "add"], ["git", "commit"]):
            return True, ""
        if args[:2] == ["git", "status"]:
            return True, "M a.txt"
        if args[:3] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "push"]:
            state["push"] += 1
            if state["push"] == 1:
                return False, "rejected fetch first"
            return False, "Connection reset by peer"
        if args[:2] == ["git", "pull"]:
            return True, "Merge made"
        return True, ""

    monkeypatch.setattr(GU, "run_command", _fake_run)
    monkeypatch.setattr(GU.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(GU, "collect_safe_files", lambda: (["a.txt"], []))
    answers = iter(["msg", "y"])
    monkeypatch.setattr("builtins.input", lambda _p: next(answers))
    GU.main()


def test_collect_deleted_files_edge_cases(monkeypatch):
    GU = _load_module()

    # failure path -> returns empty list
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (False, "err"))
    assert GU.collect_deleted_files() == []

    # empty lines and forbidden paths are skipped
    monkeypatch.setattr(
        GU, "run_command",
        lambda *a, **k: (True, "\nsessions/secret.txt\nlegit.txt\n")
    )
    assert GU.collect_deleted_files() == ["legit.txt"]


def test_collect_tracked_ignored_files_failure(monkeypatch):
    GU = _load_module()
    monkeypatch.setattr(GU, "run_command", lambda *a, **k: (False, "err"))
    assert GU.collect_tracked_ignored_files() == []