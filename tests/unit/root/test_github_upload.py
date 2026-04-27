import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import types

import pytest

import github_upload as gu


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


def test_url_and_path_helpers(tmp_path):
    assert gu._is_valid_repo_url("https://github.com/a/b")
    assert gu._is_valid_repo_url("git@github.com:a/b.git")
    assert not gu._is_valid_repo_url("https://gitlab.com/a/b")
    assert not gu._is_valid_repo_url("")

    assert gu._normalize_path("./a//b\\c") == "a/b/c"
    assert gu._normalize_path("/root/x") == "root/x"

    assert gu.is_forbidden_path(".env")
    assert gu.is_forbidden_path("sessions/a.json")
    assert gu.is_forbidden_path(".git/config")
    assert not gu.is_forbidden_path(".env.example")

    p = tmp_path / "ok.txt"
    p.write_text("abc", encoding="utf-8")
    assert gu.get_file_content(str(p)) == "abc"
    assert gu.get_file_content(".env") is None


def test_get_deleted_files_and_collect_safe_files(monkeypatch, tmp_path):
    text_file = tmp_path / "a.py"
    text_file.write_text("print('x')", encoding="utf-8")
    binary_file = tmp_path / "bad.json"
    binary_file.write_bytes(b"\xff\xfe")

    calls = []

    def fake_run(cmd, show_output=True):
        calls.append(cmd)
        if cmd[:3] == ["git", "ls-files", "-d"]:
            return True, "gone.txt\n"
        if cmd[:4] == ["git", "ls-files", "-co", "--exclude-standard"]:
            return True, f"{text_file}\n{binary_file}\n.env\ngone.txt\n"
        return True, ""

    monkeypatch.setattr(gu, "run_command", fake_run)
    deleted = gu.get_deleted_files()
    assert deleted == ["gone.txt"]
    assert fake_run(["git", "status"]) == (True, "")

    safe, blocked = gu.collect_safe_files(deleted)
    assert str(text_file) in safe
    assert str(binary_file) in blocked
    assert ".env" in blocked

    monkeypatch.setattr(gu, "run_command", lambda *_a, **_k: (False, "err"))
    safe2, blocked2 = gu.collect_safe_files([])
    assert safe2 == [] and blocked2 == []


def test_stage_files(monkeypatch):
    assert gu.stage_files([]) == (True, "")

    captured = {}

    def fake_run(cmd, show_output=True):
        captured["cmd"] = cmd
        return True, "ok"

    monkeypatch.setattr(gu, "run_command", fake_run)
    ok, _ = gu.stage_files(["a.txt", "b.py"])
    assert ok
    assert captured["cmd"] == ["git", "add", "--", ":(literal)a.txt", ":(literal)b.py"]


class MainHarness:
    def __init__(self, monkeypatch, argv, outputs, inputs=None, cfg_token="tok", cfg_version="9.9"):
        self.inputs = list(inputs or [])
        self.calls = []
        gu.sys.argv = ["github_upload.py", *argv]
        monkeypatch.setattr(gu, "cfg", types.SimpleNamespace(GITHUB_TOKEN=cfg_token, VERSION=cfg_version))
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


def test_main_rollback_yes_push_fail(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-2"],
        outputs=[
            (True, "git version"),
            (True, "name"),
            (True, "origin"),
            (True, "main"),
            (True, "reset ok"),
            (False, "protected"),
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 0


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
        outputs=[(True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, "")],
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
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], [".env"]))
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, "A a.py"), (True, "ok"), (False, "fetch first")
        ],
        inputs=["m", "n"],
    )
    gu.main()

    # merge command fails
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, "A a.py"), (True, "ok"), (False, "non-fast-forward"), (False, "fatal")
        ],
        inputs=["m", "y"],
    )
    gu.main()

    # unknown push error
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, "A a.py"), (True, "ok"), (False, "boom")
        ],
        inputs=["m"],
    )
    gu.main()


def test_main_happy_path_with_new_repo_and_deleted_decline(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: ["gone.py"])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["x.py"], [".env"]))
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "dev"), (True, "M a"), (False, "stash err")
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "feature"), (True, ""), (True, "ok"),
            (True, ""), (True, ""), (True, "unpushed") ,(True, "push")
        ],
    )
    gu.main()


def test_main_rollback_reset_fail(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (False, "reset fail")
        ],
        inputs=["yes"],
    )
    assert run_main_and_exit_code() == 1


def test_main_target_branch_merge_made_commit_default_message(monkeypatch):
    monkeypatch.setattr(gu, "get_deleted_files", lambda: [])
    monkeypatch.setattr(gu, "collect_safe_files", lambda deleted_files_list=None: (["a.py"], []))
    monkeypatch.setattr(gu, "stage_files", lambda paths: (True, ""))

    h = MainHarness(
        monkeypatch,
        ["feature-x"],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (False, "merge made"),
            (True, ""), (True, "A a.py"), (True, "ok"), (True, "ok")
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, "A a.py"), (True, "ok"), (False, "rejected"), (True, "up to date"), (False, "some other err")
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, "A a.py"), (True, "ok"), (False, "fetch first"), (True, "ok"), (True, "ok")
        ],
        inputs=["msg", "y"],
    )
    gu.main()


def test_main_checkout_fail_without_stash(monkeypatch):
    MainHarness(
        monkeypatch,
        [],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "dev"), (True, ""), (False, "fail")
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "feature"), (True, "M x"),
            (True, "stashed"), (True, "checkout"), (True, "pop"), (True, ""), (True, ""), (True, "unpushed"), (True, "pushed")
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
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, ""),
            (True, ""), (True, ""), (True, "commit1"), (True, "push ok")
        ],
    )
    gu.main()

def test_main_rollback_push_success(monkeypatch):
    MainHarness(
        monkeypatch,
        ["-1"],
        outputs=[
            (True, "git version"), (True, "name"), (True, "origin"), (True, "main"), (True, "reset ok"), (True, "push ok")
        ],
        inputs=["evet"],
    )
    assert run_main_and_exit_code() == 0
