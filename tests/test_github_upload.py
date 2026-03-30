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
