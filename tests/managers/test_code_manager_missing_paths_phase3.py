from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.code_manager import CodeManager


class _SecurityStub:
    def __init__(self) -> None:
        self.level = "full"

    def can_read(self, _path: str) -> bool:
        return True

    def can_write(self, _path: str) -> bool:
        return True

    def can_execute(self) -> bool:
        return True

    def can_run_shell(self) -> bool:
        return True

    def is_path_under(self, path: str, base_dir: Path) -> bool:
        return str(path).startswith(str(base_dir))


def _build_manager(tmp_path: Path) -> CodeManager:
    manager = CodeManager.__new__(CodeManager)
    manager.base_dir = tmp_path
    manager.cfg = SimpleNamespace(SANDBOX_LIMITS={})
    manager.security = _SecurityStub()
    manager.docker_mem_limit = "256m"
    manager.docker_exec_timeout = 3
    manager.docker_nano_cpus = 1_000_000_000
    manager.max_output_chars = 60
    manager.docker_image = "python:3.11-alpine"
    manager.docker_client = None
    manager.docker_available = False
    manager.enable_lsp = True
    manager.lsp_timeout_seconds = 1
    manager.lsp_max_references = 5
    manager.python_lsp_server = "pyright-langserver"
    manager.typescript_lsp_server = "typescript-language-server"
    manager.docker_runtime = ""
    manager.docker_allowed_runtimes = ["", "runc", "runsc", "kata-runtime"]
    manager.docker_microvm_mode = "off"
    manager.docker_network_disabled = True
    manager._lock = threading.RLock()
    manager._files_read = 0
    manager._files_written = 0
    manager._syntax_checks = 0
    manager._audits_done = 0
    return manager


def test_write_generated_test_handles_empty_and_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_x():\n    assert True\n", encoding="utf-8")

    ok_empty, msg_empty = manager.write_generated_test(str(target), "```python\n\n```")
    assert ok_empty is False
    assert "boş" in msg_empty.lower()

    payload = "def test_new():\n    assert 1 == 1"
    target.write_text(payload + "\n", encoding="utf-8")
    ok_dup, msg_dup = manager.write_generated_test(str(target), payload)
    assert ok_dup is True
    assert "zaten mevcut" in msg_dup

    monkeypatch.setattr(manager, "read_file", lambda *_a, **_k: (False, "read err"))
    ok_read, msg_read = manager.write_generated_test(str(target), "def test_y():\n    assert True")
    assert ok_read is False
    assert msg_read == "read err"


def test_patch_file_reports_not_found_and_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    monkeypatch.setattr(manager, "read_file", lambda *_a, **_k: (True, "a\nb\n"))
    ok_missing, msg_missing = manager.patch_file("x.py", "c", "z")
    assert ok_missing is False
    assert "bulunamadı" in msg_missing

    monkeypatch.setattr(manager, "read_file", lambda *_a, **_k: (True, "a\na\n"))
    ok_multi, msg_multi = manager.patch_file("x.py", "a", "z")
    assert ok_multi is False
    assert "kez geçiyor" in msg_multi


def test_execute_code_docker_required_and_restricted_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import managers.code_manager as mod

    manager = _build_manager(tmp_path)
    manager.security.level = mod.SANDBOX

    ok_sandbox, msg_sandbox = manager.execute_code("print(1)")
    assert ok_sandbox is False
    assert "güvenlik politikası" in msg_sandbox

    manager.security.level = "full"
    monkeypatch.setattr(mod.Config, "DOCKER_REQUIRED", True, raising=False)
    ok_required, msg_required = manager.execute_code("print(1)")
    assert ok_required is False
    assert "DOCKER_REQUIRED=true" in msg_required


def test_execute_code_uses_local_fallback_when_not_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import managers.code_manager as mod

    manager = _build_manager(tmp_path)
    monkeypatch.setattr(mod.Config, "DOCKER_REQUIRED", False, raising=False)
    monkeypatch.setattr(manager, "execute_code_local", lambda code: (True, f"local:{code}"))

    ok, out = manager.execute_code("print('ok')")

    assert ok is True
    assert "local:print('ok')" == out


def test_run_shell_in_sandbox_guardrails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    manager.security.can_execute = lambda: False
    ok_auth, msg_auth = manager.run_shell_in_sandbox("echo hi")
    assert ok_auth is False
    assert "yetkisi yok" in msg_auth

    manager.security.can_execute = lambda: True
    ok_empty, _ = manager.run_shell_in_sandbox("   ")
    assert ok_empty is False

    ok_cwd, msg_cwd = manager.run_shell_in_sandbox("echo hi", cwd=str(tmp_path / "missing"))
    assert ok_cwd is False
    assert "Geçersiz çalışma dizini" in msg_cwd

    manager.security.is_path_under = lambda *_a, **_k: False
    ok_scope, msg_scope = manager.run_shell_in_sandbox("echo hi", cwd=str(tmp_path))
    assert ok_scope is False
    assert "proje kökü dışında" in msg_scope

    manager.security.is_path_under = lambda *_a, **_k: True
    monkeypatch.setattr("managers.code_manager.shutil.which", lambda _x: None)
    ok_docker, msg_docker = manager.run_shell_in_sandbox("echo hi", cwd=str(tmp_path))
    assert ok_docker is False
    assert "Docker CLI bulunamadı" in msg_docker


def test_run_shell_blocks_meta_without_optin_and_dangerous_patterns(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    ok_meta, msg_meta = manager.run_shell("echo ok | cat")
    assert ok_meta is False
    assert "allow_shell_features=True" in msg_meta

    ok_bad, msg_bad = manager.run_shell("rm -rf /tmp", allow_shell_features=True)
    assert ok_bad is False
    assert "tehlikeli" in msg_bad


def test_run_shell_handles_split_errors_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    monkeypatch.setattr("managers.code_manager.shlex.split", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad")))
    ok_parse, msg_parse = manager.run_shell("echo 'broken")
    assert ok_parse is False
    assert "ayrıştırılamadı" in msg_parse

    monkeypatch.setattr("managers.code_manager.shlex.split", lambda cmd: [cmd])
    monkeypatch.setattr(
        "managers.code_manager.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=60)),
    )
    ok_timeout, msg_timeout = manager.run_shell("echo x")
    assert ok_timeout is False
    assert "Zaman aşımı" in msg_timeout


def test_glob_and_grep_edge_paths(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    ok_pattern, _ = manager.glob_search("", base_path=str(tmp_path))
    assert ok_pattern is False

    ok_missing, msg_missing = manager.glob_search("*.py", base_path=str(tmp_path / "none"))
    assert ok_missing is False
    assert "Dizin bulunamadı" in msg_missing

    a = tmp_path / "a.py"
    a.write_text("print('x')\n", encoding="utf-8")
    bdir = tmp_path / "sub"
    bdir.mkdir()
    (bdir / "b.py").write_text("print('y')\n", encoding="utf-8")

    ok_glob, msg_glob = manager.glob_search("**/*.py", base_path=str(tmp_path))
    assert ok_glob is True
    assert "a.py" in msg_glob and "b.py" in msg_glob

    ok_regex, _ = manager.grep_files("(", path=str(tmp_path))
    assert ok_regex is False

    ok_grep, msg_grep = manager.grep_files("print", path=str(tmp_path), file_glob="*.py", max_results=1)
    assert ok_grep is True
    assert "Maksimum eşleşme" in msg_grep


def test_lsp_format_and_rename_flows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)
    src = tmp_path / "mod.py"
    src.write_text("name = 1\n", encoding="utf-8")

    none_txt = manager._format_lsp_locations([], limit=2)
    assert "Sonuç bulunamadı" in none_txt

    ok_empty_name, msg_empty_name = manager.lsp_rename_symbol(str(src), 0, 0, "   ")
    assert ok_empty_name is False

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_k: [{"id": 2, "result": {"changes": {"file:///tmp/x.py": []}}}],
    )
    ok_dry, msg_dry = manager.lsp_rename_symbol(str(src), 0, 0, "renamed", apply=False)
    assert ok_dry is True
    assert "dry-run" in msg_dry

    monkeypatch.setattr(manager, "_apply_workspace_edit", lambda _edit: (True, "applied"))
    ok_apply, msg_apply = manager.lsp_rename_symbol(str(src), 0, 0, "renamed", apply=True)
    assert ok_apply is True
    assert msg_apply == "applied"


def test_lsp_semantic_audit_no_targets_no_signal_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    ok_none, audit_none = manager.lsp_semantic_audit(paths=["notes.txt"])
    assert ok_none is False
    assert audit_none["status"] == "no-targets"

    py_file = tmp_path / "ok.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_k: [{"method": "other", "params": {}}])
    ok_signal, audit_signal = manager.lsp_semantic_audit(paths=[str(py_file)])
    assert ok_signal is True
    assert audit_signal["status"] == "no-signal"

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("lsp down")),
    )
    ok_err, audit_err = manager.lsp_semantic_audit(paths=[str(py_file)])
    assert ok_err is False
    assert audit_err["status"] == "tool-error"


def test_audit_project_status_and_repr(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    py_ok = tmp_path / "good.py"
    py_ok.write_text("x = 1\n", encoding="utf-8")
    py_bad = tmp_path / "bad.py"
    py_bad.write_text("def broken(:\n", encoding="utf-8")

    report = manager.audit_project(root=str(tmp_path), max_files=1)
    assert "Uyarı" in report

    manager.docker_available = True
    status = manager.status()
    assert "Docker Sandbox Aktif" in status

    manager.docker_available = False
    status2 = manager.status()
    assert "Subprocess Modu" in status2

    rep = repr(manager)
    assert "CodeManager" in rep
    assert "docker=off" in rep


def test_execute_code_local_handles_timeout_and_exception_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    monkeypatch.setattr(
        "managers.code_manager.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="python", timeout=1)),
    )
    ok_timeout, msg_timeout = manager.execute_code_local("while True: pass")
    assert ok_timeout is False
    assert "Zaman aşımı" in msg_timeout

    def _raise_unexpected(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr("managers.code_manager.subprocess.run", _raise_unexpected)
    ok_err, msg_err = manager.execute_code_local("print('x')")
    assert ok_err is False
    assert "Subprocess çalıştırma hatası" in msg_err


def test_init_docker_sdk_failure_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    class _DockerModule:
        @staticmethod
        def from_env():
            raise RuntimeError("daemon down")

    monkeypatch.setitem(os.sys.modules, "docker", _DockerModule())
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda _mod: False)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)

    manager._init_docker()
    assert manager.docker_available is False
