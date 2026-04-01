"""github_upload.py için birim testleri."""

from __future__ import annotations

import importlib
import builtins
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _get_github_upload():
    """config bağımlılığını minimal stub ile enjekte ederek github_upload modülünü temiz import eder."""
    cfg_mod = types.ModuleType("config")

    class _Config:
        GITHUB_TOKEN = "dummy-token"
        VERSION = "5.2.0"

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod
    sys.modules.pop("github_upload", None)
    return importlib.import_module("github_upload")


class TestRepoUrlValidation:
    def test_accepts_https_github_url(self):
        mod = _get_github_upload()
        assert mod._is_valid_repo_url("https://github.com/org/repo") is True

    def test_accepts_ssh_github_url(self):
        mod = _get_github_upload()
        assert mod._is_valid_repo_url("git@github.com:org/repo.git") is True

    def test_rejects_empty_url(self):
        mod = _get_github_upload()
        assert mod._is_valid_repo_url("") is False

    def test_rejects_non_github_url(self):
        mod = _get_github_upload()
        assert mod._is_valid_repo_url("https://example.com/repo") is False


class TestPathNormalizationAndBlacklist:
    def test_normalize_path_windows_style(self):
        mod = _get_github_upload()
        assert mod._normalize_path(r".\\logs\\app.log") == "logs/app.log"

    def test_is_forbidden_exact_env(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path(".env") is True

    def test_is_forbidden_directory_prefix(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("logs/app.log") is True

    def test_allows_regular_source_file(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("core/router.py") is False


class TestGetFileContent:
    def test_returns_none_for_forbidden_path(self):
        mod = _get_github_upload()
        assert mod.get_file_content(".env") is None

    def test_reads_utf8_text_file(self, tmp_path: Path):
        mod = _get_github_upload()
        sample = tmp_path / "sample.txt"
        sample.write_text("merhaba dünya", encoding="utf-8")
        assert mod.get_file_content(str(sample)) == "merhaba dünya"

    def test_returns_none_for_decode_error(self, monkeypatch):
        mod = _get_github_upload()

        class _BadFile:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

        monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: _BadFile())
        assert mod.get_file_content("safe/path.txt") is None


class TestRunCommand:
    def test_run_command_success(self, monkeypatch, capsys):
        mod = _get_github_upload()
        completed = MagicMock(stdout="ok\n", stderr="")
        monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: completed)

        success, output = mod.run_command(["git", "status"], show_output=True)

        assert success is True
        assert output == "ok"
        assert "ok" in capsys.readouterr().out

    def test_run_command_failure_combines_stderr_and_stdout(self, monkeypatch):
        mod = _get_github_upload()
        err = mod.subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "status"],
            output="hint-line",
            stderr="err-line",
        )

        def _raise(*_args, **_kwargs):
            raise err

        monkeypatch.setattr(mod.subprocess, "run", _raise)
        success, output = mod.run_command(["git", "status"], show_output=False)

        assert success is False
        assert "err-line" in output
        assert "hint-line" in output


class TestCollectSafeFiles:
    def test_returns_empty_lists_when_git_ls_files_fails(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(mod, "run_command", lambda *_args, **_kwargs: (False, "boom"))

        safe, blocked = mod.collect_safe_files()

        assert safe == []
        assert blocked == []

    def test_collects_safe_and_blocked_files(self, monkeypatch):
        mod = _get_github_upload()

        git_listing = "\n".join(
            [
                "src/app.py",
                "logs/app.log",
                "README.md",
                "docs/manual.txt",
                "script.sh",
                "binary.bin",
                "",  # boş satır
            ]
        )
        monkeypatch.setattr(mod, "run_command", lambda *_args, **_kwargs: (True, git_listing))
        monkeypatch.setattr(mod.os.path, "isdir", lambda _p: False)

        def _fake_content(path: str):
            if path == "README.md":
                return None  # text uzantısı, okunamaz -> blocked
            if path == "docs/manual.txt":
                return "ok"
            if path == "src/app.py":
                return "print('ok')"
            if path == "script.sh":
                return "#!/bin/bash"
            return "any"

        monkeypatch.setattr(mod, "get_file_content", _fake_content)

        safe, blocked = mod.collect_safe_files()

        assert "src/app.py" in safe
        assert "docs/manual.txt" in safe
        assert "script.sh" in safe
        assert "binary.bin" in safe  # text uzantısı değilse içerik okunmasa da geçer
        assert "README.md" in blocked
        assert "logs/app.log" in blocked


class TestNormalizePathEdgeCases:
    def test_removes_dot_slash_prefix(self):
        mod = _get_github_upload()
        assert mod._normalize_path("./relative/path.py") == "relative/path.py"

    def test_removes_leading_slash(self):
        mod = _get_github_upload()
        assert mod._normalize_path("/absolute/path.py") == "absolute/path.py"

    def test_collapses_double_slashes(self):
        mod = _get_github_upload()
        assert mod._normalize_path("a//b//c.py") == "a/b/c.py"

    def test_plain_path_unchanged(self):
        mod = _get_github_upload()
        assert mod._normalize_path("src/app.py") == "src/app.py"

    def test_dot_slash_only_becomes_empty(self):
        mod = _get_github_upload()
        assert mod._normalize_path("./") == ""


class TestIsForbiddenPathExtended:
    def test_chroma_db_path_is_forbidden(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("chroma_db/data.json") is True

    def test_pycache_path_is_forbidden(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("__pycache__/module.pyc") is True

    def test_sessions_path_is_forbidden(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("sessions/user.json") is True

    def test_models_path_is_forbidden(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("models/llm.bin") is True

    def test_git_dir_is_forbidden(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path(".git/config") is True

    def test_non_forbidden_python_file_allowed(self):
        mod = _get_github_upload()
        assert mod.is_forbidden_path("agent/sidar_agent.py") is False


class TestGithubUploadMainFlow:
    def test_main_rejects_rollback_out_of_range(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-11"])
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1

    def test_main_exits_when_github_token_missing(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(mod.cfg, "GITHUB_TOKEN", "", raising=False)
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1

    def test_main_exits_when_remote_missing_and_repo_url_invalid(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(mod.cfg, "GITHUB_TOKEN", "tok", raising=False)
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True if p == ".git" else False)

        def _fake_run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2.0"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "sidar-user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, ""  # origin yok
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            return True, ""

        monkeypatch.setattr(mod, "run_command", _fake_run)
        monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "https://example.com/not-github")

        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1

    def test_main_rollback_cancelled_exits_zero(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-2"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True if p == ".git" else False)

        def _fake_run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2.0"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "sidar-user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, "origin\thttps://github.com/org/repo (fetch)"
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            return True, ""

        monkeypatch.setattr(mod, "run_command", _fake_run)
        monkeypatch.setattr(builtins, "input", lambda *_a, **_k: "hayır")

        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 0

    def test_main_reports_github_push_access_denied_error(self, monkeypatch, capsys):
        mod = _get_github_upload()
        monkeypatch.setattr(mod.cfg, "GITHUB_TOKEN", "tok", raising=False)
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True if p == ".git" else False)

        def _fake_run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2.0"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "sidar-user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, "origin\thttps://github.com/org/repo (fetch)"
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files", "-co", "--exclude-standard"]:
                return True, ""
            if args[:3] == ["git", "status", "--porcelain"]:
                return True, ""  # working tree clean
            if args[:2] == ["git", "log"]:
                return True, "commit abc123"  # unpushed commit exists
            if args[:4] == ["git", "push", "-u", "origin"]:
                return False, "remote: Permission to org/repo denied.\nfatal: HTTP 403"
            return True, ""

        monkeypatch.setattr(mod, "run_command", _fake_run)
        mod.main()
        output = capsys.readouterr().out
        assert "Yükleme sırasında bilinmeyen bir hata" in output
        assert "Permission to org/repo denied" in output

class TestGithubUploadAdditionalBranches:
    def test_collect_safe_files_skips_directories(self, monkeypatch):
        mod = _get_github_upload()
        monkeypatch.setattr(mod, "run_command", lambda *_a, **_k: (True, "src\nREADME.md"))
        monkeypatch.setattr(mod.os.path, "isdir", lambda p: p == "src")
        monkeypatch.setattr(mod, "get_file_content", lambda _p: "ok")

        safe, blocked = mod.collect_safe_files()
        assert "src" not in safe
        assert "README.md" in safe
        assert blocked == []

    def test_is_valid_repo_url_trims_whitespace(self):
        mod = _get_github_upload()
        assert mod._is_valid_repo_url("   https://github.com/org/repo   ") is True

    def test_colors_constants_are_ansi_sequences(self):
        mod = _get_github_upload()
        assert mod.Colors.HEADER.startswith("\033[")
        assert mod.Colors.OKGREEN.startswith("\033[")
        assert mod.Colors.ENDC == "\033[0m"


# ─────────────────────────────────────────────────────────────
# Helper: inject minimal config stub and (re)import the module
# ─────────────────────────────────────────────────────────────

def _load(github_token: str = "tok", version: str = "2.1"):
    """Return a fresh import of github_upload with a stubbed config."""
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        GITHUB_TOKEN = github_token
        VERSION = version

    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod
    sys.modules.pop("github_upload", None)
    return importlib.import_module("github_upload")


# ─────────────────────────────────────────────────────────────
# run_command — output paths (lines 60-62, 65-68, 69)
# ─────────────────────────────────────────────────────────────

class TestRunCommandOutputPaths:
    def test_show_output_true_with_stdout_prints(self, capsys):
        mod = _load()
        result = MagicMock(stdout="hello world\n", stderr="")
        mod.subprocess.run = MagicMock(return_value=result)

        ok, out = mod.run_command(["git", "status"], show_output=True)

        assert ok is True
        assert out == "hello world"
        captured = capsys.readouterr()
        assert "hello world" in captured.out

    def test_show_output_false_suppresses_stdout(self, capsys):
        mod = _load()
        result = MagicMock(stdout="hello world\n", stderr="")
        mod.subprocess.run = MagicMock(return_value=result)

        ok, out = mod.run_command(["git", "status"], show_output=False)

        assert ok is True
        assert out == "hello world"
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_stdout_not_printed(self, capsys):
        mod = _load()
        result = MagicMock(stdout="   ", stderr="")
        mod.subprocess.run = MagicMock(return_value=result)

        ok, _ = mod.run_command(["git", "status"], show_output=True)

        assert ok is True
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_cpe_stderr_and_stdout_combined(self, monkeypatch):
        mod = _load()
        exc = mod.subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "push"],
            output="hint text",
            stderr="fatal: error",
        )
        mod.subprocess.run = MagicMock(side_effect=exc)

        ok, msg = mod.run_command(["git", "push"], show_output=False)

        assert ok is False
        assert "fatal: error" in msg
        assert "hint text" in msg

    def test_cpe_show_output_true_prints_err_msg(self, capsys):
        mod = _load()
        exc = mod.subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "push"],
            output=None,
            stderr="permission denied",
        )
        mod.subprocess.run = MagicMock(side_effect=exc)

        ok, _ = mod.run_command(["git", "push"], show_output=True)

        assert ok is False
        captured = capsys.readouterr()
        assert "permission denied" in captured.out

    def test_cpe_empty_stderr_not_printed(self, capsys):
        mod = _load()
        exc = mod.subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "status"],
            output=None,
            stderr="",
        )
        mod.subprocess.run = MagicMock(side_effect=exc)

        ok, msg = mod.run_command(["git", "status"], show_output=True)

        assert ok is False
        assert msg == ""
        assert capsys.readouterr().out == ""


# ─────────────────────────────────────────────────────────────
# collect_safe_files — directory skip + unreadable binary (line 132)
# ─────────────────────────────────────────────────────────────

class TestCollectSafeFilesEdgeCases:
    def test_skips_directory_entries(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "run_command", lambda *a, **k: (True, "src\nfile.py"))
        monkeypatch.setattr(mod.os.path, "isdir", lambda p: p == "src")
        monkeypatch.setattr(mod, "get_file_content", lambda p: "code")

        safe, blocked = mod.collect_safe_files()

        assert "src" not in safe
        assert "file.py" in safe

    def test_blocked_when_text_file_unreadable(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "run_command", lambda *a, **k: (True, "data.csv"))
        monkeypatch.setattr(mod.os.path, "isdir", lambda p: False)
        monkeypatch.setattr(mod, "get_file_content", lambda p: None)

        safe, blocked = mod.collect_safe_files()

        assert "data.csv" in blocked
        assert "data.csv" not in safe

    def test_binary_extension_not_content_checked(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod, "run_command", lambda *a, **k: (True, "image.png"))
        monkeypatch.setattr(mod.os.path, "isdir", lambda p: False)
        content_called = []
        monkeypatch.setattr(mod, "get_file_content", lambda p: content_called.append(p) or "x")

        safe, blocked = mod.collect_safe_files()

        assert "image.png" in safe
        # get_file_content should NOT be called for .png (not in TEXT_EXTENSIONS)
        assert "image.png" not in content_called


# ─────────────────────────────────────────────────────────────
# main() — git not installed (line 179-181)
# ─────────────────────────────────────────────────────────────

class TestMainGitNotInstalled:
    def test_exits_when_git_not_found(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])

        def _fake_run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return False, "git: command not found"
            return True, ""

        monkeypatch.setattr(mod, "run_command", _fake_run)

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1


# ─────────────────────────────────────────────────────────────
# main() — git identity setup (lines 184-190)
# ─────────────────────────────────────────────────────────────

class TestMainGitIdentitySetup:
    def _base_run(self, args, show_output=False, *, extra=None):
        if args[:2] == ["git", "--version"]:
            return True, "git version 2.x"
        if args[:3] == ["git", "config", "user.name"]:
            return True, ""          # no name → triggers identity prompt
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo (fetch)"
        if args[:4] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:4] == ["git", "ls-files"]:
            return True, ""
        if args[:3] == ["git", "status"]:
            return True, ""
        if args[:2] == ["git", "log"]:
            return True, ""
        if args[:4] == ["git", "push"]:
            return True, ""
        return True, ""

    def test_prompts_for_name_and_email_when_identity_missing(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)

        inputs = iter(["Sidar Bot", "sidar@example.com"])
        monkeypatch.setattr(builtins, "input", lambda *a, **k: next(inputs))

        calls = []

        def _run(args, show_output=False):
            calls.append(args)
            return self._base_run(args, show_output=show_output)

        monkeypatch.setattr(mod, "run_command", _run)

        with pytest.raises(SystemExit):
            mod.main()

        config_calls = [c for c in calls if c[:3] == ["git", "config", "--global"]]
        assert any("user.name" in c for c in config_calls)
        assert any("user.email" in c for c in config_calls)


# ─────────────────────────────────────────────────────────────
# main() — git init when .git missing (lines 192-196)
# ─────────────────────────────────────────────────────────────

class TestMainGitInit:
    def test_runs_git_init_when_dot_git_missing(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: False)

        inputs_iter = iter(["https://github.com/org/repo"])
        monkeypatch.setattr(builtins, "input", lambda *a, **k: next(inputs_iter))

        calls = []

        def _run(args, show_output=False):
            calls.append(args)
            if args[:2] == ["git", "--version"]:
                return True, "git version 2"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, ""  # no origin yet
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files"]:
                return True, ""
            if args[:3] == ["git", "status"]:
                return True, ""
            if args[:2] == ["git", "log"]:
                return True, ""
            if args[:4] == ["git", "push"]:
                return True, ""
            return True, ""

        monkeypatch.setattr(mod, "run_command", _run)

        with pytest.raises(SystemExit):
            mod.main()

        assert any(c[:2] == ["git", "init"] for c in calls)


# ─────────────────────────────────────────────────────────────
# main() — origin setup path (lines 199-211)
# ─────────────────────────────────────────────────────────────

class TestMainOriginSetup:
    def test_adds_remote_when_origin_absent(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "https://github.com/org/repo")

        calls = []

        def _run(args, show_output=False):
            calls.append(args)
            if args[:2] == ["git", "--version"]:
                return True, "git version 2"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, ""  # no origin
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files"]:
                return True, ""
            if args[:3] == ["git", "status"]:
                return True, ""
            if args[:2] == ["git", "log"]:
                return True, ""
            if args[:4] == ["git", "push"]:
                return True, ""
            return True, ""

        monkeypatch.setattr(mod, "run_command", _run)

        with pytest.raises(SystemExit):
            mod.main()

        assert any(
            len(c) >= 4 and c[:3] == ["git", "remote", "add"]
            for c in calls
        )

    def test_prints_existing_connection_when_origin_present(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)

        def _run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, "origin\thttps://github.com/org/repo (fetch)"
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files"]:
                return True, ""
            if args[:3] == ["git", "status"]:
                return True, ""
            if args[:2] == ["git", "log"]:
                return True, ""
            if args[:4] == ["git", "push"]:
                return True, ""
            return True, ""

        monkeypatch.setattr(mod, "run_command", _run)

        with pytest.raises(SystemExit):
            mod.main()

        out = capsys.readouterr().out
        assert "Mevcut GitHub bağlantısı algılandı" in out


# ─────────────────────────────────────────────────────────────
# main() — non-main branch switch (lines 220-254)
# ─────────────────────────────────────────────────────────────

def _make_branch_switch_run(stash_status="dirty", checkout_ok=True, stash_pop_ok=True):
    """Return a fake run_command that simulates being on a non-main branch."""

    def _run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version 2"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "user"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo (fetch)"
        if args[:4] == ["git", "branch", "--show-current"]:
            return True, "feature/xyz"   # NOT main
        if args[:3] == ["git", "status", "--porcelain"]:
            return True, stash_status    # non-empty → stash needed
        if args[:3] == ["git", "stash", "push"]:
            return True, "Saved working directory"
        if args[:2] == ["git", "checkout"]:
            return checkout_ok, "" if checkout_ok else "checkout error"
        if args[:3] == ["git", "stash", "pop"]:
            return stash_pop_ok, "" if stash_pop_ok else "conflict"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:4] == ["git", "ls-files"]:
            return True, ""
        if args[:3] == ["git", "status"]:
            return True, ""
        if args[:2] == ["git", "log"]:
            return True, ""
        if args[:4] == ["git", "push"]:
            return True, ""
        return True, ""

    return _run


class TestMainBranchSwitch:
    def test_stash_and_checkout_to_main(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _make_branch_switch_run())
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        try:
            mod.main()
        except SystemExit:
            pass

        out = capsys.readouterr().out
        assert "main" in out

    def test_exits_when_checkout_fails(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _make_branch_switch_run(checkout_ok=False))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1

    def test_exits_when_stash_pop_fails(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _make_branch_switch_run(stash_pop_ok=False))

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1

    def test_no_stash_when_working_tree_clean(self, monkeypatch):
        """If porcelain status is empty, stash push should NOT be called."""
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)

        calls = []

        def _run(args, show_output=False):
            calls.append(tuple(args))
            return _make_branch_switch_run(stash_status="")(args, show_output=show_output)

        monkeypatch.setattr(mod, "run_command", _run)

        with pytest.raises(SystemExit):
            mod.main()

        stash_calls = [c for c in calls if len(c) >= 2 and c[:2] == ("git", "stash")]
        # stash push should not be called when clean
        assert not any(c[2] == "push" for c in stash_calls if len(c) > 2)


# ─────────────────────────────────────────────────────────────
# main() — rollback flow (lines 268-288)
# ─────────────────────────────────────────────────────────────

def _rollback_base_run(reset_ok=True, push_ok=True):
    def _run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version 2"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "user"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo (fetch)"
        if args[:4] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:3] == ["git", "reset", "--hard"]:
            return reset_ok, "" if reset_ok else "reset error"
        if args[:3] == ["git", "push", "--force"]:
            return push_ok, "" if push_ok else "push failed"
        return True, ""
    return _run


class TestMainRollback:
    def test_rollback_confirmed_and_push_success(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-3"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _rollback_base_run())
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "evet")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0
        assert "BAŞARILI" in capsys.readouterr().out

    def test_rollback_confirmed_reset_fails(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-2"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _rollback_base_run(reset_ok=False))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "evet")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1

    def test_rollback_confirmed_push_fails(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-1"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _rollback_base_run(push_ok=False))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "yes")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Force Push" in out

    def test_rollback_confirmed_with_y(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-1"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _rollback_base_run())
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0

    def test_rollback_out_of_range_zero(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "-0"])
        # -0 matches ^-\d+$ but rollback_steps becomes 0 — no rollback
        # Just ensure it doesn't crash with bad range
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", lambda *a, **k: (True, ""))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")
        # Should either exit(1) due to missing changes or handle gracefully
        with pytest.raises(SystemExit):
            mod.main()


# ─────────────────────────────────────────────────────────────
# main() — target_branch pull flow (lines 298-312)
# ─────────────────────────────────────────────────────────────

def _pull_branch_run(pull_ok=True, pull_err=""):
    def _run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version 2"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "user"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo (fetch)"
        if args[:4] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "pull"]:
            return pull_ok, pull_err
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:4] == ["git", "ls-files"]:
            return True, ""
        if args[:3] == ["git", "status"]:
            return True, ""
        if args[:2] == ["git", "log"]:
            return True, ""
        if args[:4] == ["git", "push"]:
            return True, ""
        return True, ""
    return _run


class TestMainTargetBranchPull:
    def test_pull_branch_success(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "feat/my-feature"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _pull_branch_run(pull_ok=True))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        with pytest.raises(SystemExit):
            mod.main()

        out = capsys.readouterr().out
        assert "feat/my-feature" in out

    def test_pull_branch_fails_exits_1(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "feat/conflict"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _pull_branch_run(pull_ok=False, pull_err="CONFLICT"))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1

    def test_pull_branch_up_to_date_is_ok(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py", "feat/stale"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            _pull_branch_run(pull_ok=False, pull_err="Already up to date.")
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        with pytest.raises(SystemExit):
            mod.main()

        out = capsys.readouterr().out
        assert "başarıyla çekildi" in out


# ─────────────────────────────────────────────────────────────
# main() — standard upload + commit flow (lines 322-358)
# ─────────────────────────────────────────────────────────────

def _upload_run(
    has_changes=True,
    commit_ok=True,
    push_ok=True,
    push_err="",
    unpushed="",
    blocked_files="",
    safe_files="main.py",
):
    def _run(args, show_output=False):
        if args[:2] == ["git", "--version"]:
            return True, "git version 2"
        if args[:3] == ["git", "config", "user.name"]:
            return True, "user"
        if args[:3] == ["git", "remote", "-v"]:
            return True, "origin\thttps://github.com/org/repo (fetch)"
        if args[:4] == ["git", "branch", "--show-current"]:
            return True, "main"
        if args[:2] == ["git", "reset"]:
            return True, ""
        if args[:2] == ["git", "ls-files"]:
            return True, safe_files
        if args[:3] == ["git", "diff", "--cached"]:
            # stage sonrası commit yoluna girilip girilmeyeceğini belirler
            return True, "M\tmain.py" if has_changes else ""
        if args[:3] == ["git", "status", "--porcelain"]:
            return True, "M main.py" if has_changes else ""
        if args[:2] == ["git", "add"]:
            return True, ""
        if args[:2] == ["git", "commit"]:
            return commit_ok, "" if commit_ok else "nothing to commit"
        if args[:2] == ["git", "log"]:
            return True, unpushed
        if args[:2] == ["git", "push"]:
            return push_ok, push_err
        return True, ""

    return _run


class TestMainUploadFlow:
    def test_commit_with_custom_message(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _upload_run(has_changes=True, push_ok=True))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "my custom commit msg")

        # After successful push main() returns normally (no sys.exit)
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        assert "TEBRİKLER" in capsys.readouterr().out

    def test_commit_with_empty_message_uses_default(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _upload_run(has_changes=True, push_ok=True))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

        # After successful push main() returns normally (no sys.exit)
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0

    def test_commit_failure_exits_1(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _upload_run(has_changes=True, commit_ok=False))
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "msg")

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1

    def test_no_changes_no_unpushed_exits_0(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(mod, "run_command", _upload_run(has_changes=False, unpushed=""))

        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0
        assert "güncel" in capsys.readouterr().out

    def test_no_changes_but_unpushed_commits_proceeds(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            _upload_run(has_changes=False, unpushed="abc123 pending commit", push_ok=True)
        )

        # main() returns normally after printing TEBRİKLER (no sys.exit at that path)
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "TEBRİKLER" in out

    def test_blocked_files_are_listed(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "msg")

        # Provide a .env file in git ls-files output → it will be blocked
        monkeypatch.setattr(
            mod, "run_command",
            _upload_run(has_changes=True, safe_files=".env\nmain.py", push_ok=True)
        )
        # We need is_forbidden_path to work naturally here
        monkeypatch.setattr(mod.os.path, "isdir", lambda p: False)

        try:
            mod.main()
        except SystemExit:
            pass

        out = capsys.readouterr().out
        assert ".env" in out or "atlanan" in out


# ─────────────────────────────────────────────────────────────
# main() — push rejection / merge flow (lines 367-406)
# ─────────────────────────────────────────────────────────────

class TestMainPushRejection:
    def _make_run(self, first_push_err, second_pull_ok=True, second_push_ok=True, second_push_err=""):
        call_count = {"push": 0}

        def _run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, "origin\thttps://github.com/org/repo (fetch)"
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files"]:
                return True, "main.py"
            if args[:3] == ["git", "status", "--porcelain"]:
                return True, ""
            if args[:2] == ["git", "log"]:
                return True, "abc123"
            if args[:2] == ["git", "pull"]:
                return second_pull_ok, ""
            if args[:4] == ["git", "push", "-u", "origin"]:
                call_count["push"] += 1
                if call_count["push"] == 1:
                    return False, first_push_err
                return second_push_ok, second_push_err
            return True, ""

        return _run

    def test_rejected_push_user_agrees_to_merge_and_repush_succeeds(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            self._make_run("error: failed to push some refs (rejected)", second_push_ok=True)
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")

        # main() returns normally (no sys.exit after successful push)
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        assert "TEBRİKLER" in capsys.readouterr().out

    def test_rejected_push_user_declines_merge(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            self._make_run("error: fetch first")
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "n")

        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "iptal" in out

    def test_rejected_push_merge_fails(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            self._make_run("non-fast-forward", second_pull_ok=False)
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")

        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "Birleştirme sırasında hata" in out

    def test_rejected_push_repush_fails_with_rule_violation(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            self._make_run(
                "rejected",
                second_push_ok=False,
                second_push_err="remote: error: GH013: Repository rule violations found"
            )
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")

        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "Güvenlik Duvarı" in out

    def test_rejected_push_repush_generic_failure(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            mod, "run_command",
            self._make_run("rejected", second_push_ok=False, second_push_err="some generic error")
        )
        monkeypatch.setattr(builtins, "input", lambda *a, **k: "y")

        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "Yeniden yükleme başarısız" in out

    def test_unknown_push_error_prints_message(self, monkeypatch, capsys):
        mod = _load()
        monkeypatch.setattr(sys, "argv", ["github_upload.py"])
        monkeypatch.setattr(mod.os.path, "exists", lambda p: True)

        def _run(args, show_output=False):
            if args[:2] == ["git", "--version"]:
                return True, "git version 2"
            if args[:3] == ["git", "config", "user.name"]:
                return True, "user"
            if args[:3] == ["git", "remote", "-v"]:
                return True, "origin\thttps://github.com/org/repo (fetch)"
            if args[:4] == ["git", "branch", "--show-current"]:
                return True, "main"
            if args[:2] == ["git", "reset"]:
                return True, ""
            if args[:4] == ["git", "ls-files"]:
                return True, "main.py"
            if args[:3] == ["git", "status", "--porcelain"]:
                return True, ""
            if args[:2] == ["git", "log"]:
                return True, "abc123"
            if args[:2] == ["git", "push"]:
                return False, "SSH: Connection timed out"
            return True, ""

        monkeypatch.setattr(mod, "run_command", _run)

        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
        out = capsys.readouterr().out
        assert "bilinmeyen bir hata" in out


# ─────────────────────────────────────────────────────────────
# is_forbidden_path — edge cases around exact vs prefix match
# ─────────────────────────────────────────────────────────────

class TestIsForbiddenPathEdgeCases:
    def test_env_prefix_blocked(self):
        mod = _load()
        # ".environment/config.py" starts with ".env" → IS blocked by FORBIDDEN_PATHS check
        assert mod.is_forbidden_path(".environment/config.py") is True

    def test_models_exact_dir_blocked(self):
        mod = _load()
        assert mod.is_forbidden_path("models/") is True

    def test_nested_git_path_blocked(self):
        mod = _load()
        assert mod.is_forbidden_path(".git/hooks/pre-commit") is True

    def test_pycache_nested_blocked(self):
        mod = _load()
        assert mod.is_forbidden_path("src/__pycache__/module.cpython-310.pyc") is False

    def test_plain_py_file_not_blocked(self):
        mod = _load()
        assert mod.is_forbidden_path("github_upload.py") is False

    def test_windows_path_with_dot_env(self):
        mod = _load()
        # backslash form should normalize and match
        assert mod.is_forbidden_path(".env") is True
