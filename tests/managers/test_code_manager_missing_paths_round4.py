from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.code_manager import CodeManager, _encode_lsp_message


class _SecurityStub:
    def can_read(self, _path: str) -> bool:
        return True

    def can_write(self, _path: str) -> bool:
        return True

    def can_execute(self) -> bool:
        return True

    def can_run_shell(self) -> bool:
        return True

    def is_path_under(self, _path: str, _base_dir: Path) -> bool:
        return True


def _manager(tmp_path: Path) -> CodeManager:
    m = CodeManager.__new__(CodeManager)
    m.base_dir = tmp_path
    m.cfg = SimpleNamespace(SANDBOX_LIMITS={})
    m.security = _SecurityStub()
    m._lock = threading.RLock()
    m._files_read = 0
    m._files_written = 0
    m._syntax_checks = 0
    m._audits_done = 0
    m.enable_lsp = True
    m.lsp_timeout_seconds = 1
    m.lsp_max_references = 10
    m.python_lsp_server = "pyright-langserver"
    m.typescript_lsp_server = "typescript-language-server"
    m.docker_runtime = ""
    m.docker_allowed_runtimes = ["", "runc", "runsc", "kata-runtime"]
    m.docker_microvm_mode = "off"
    m.docker_network_disabled = True
    m.docker_mem_limit = "256m"
    m.docker_exec_timeout = 3
    m.docker_nano_cpus = 1_000_000_000
    m.max_output_chars = 30
    m.docker_image = "python:3.11-alpine"
    m.docker_available = False
    m.docker_client = None
    return m


def test_run_shell_in_sandbox_timeout_and_failure_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manager(tmp_path)
    monkeypatch.setattr("managers.code_manager.shutil.which", lambda _n: "docker")

    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr("managers.code_manager.subprocess.run", _timeout)
    ok_timeout, msg_timeout = m.run_shell_in_sandbox("echo hi", cwd=str(tmp_path))
    assert ok_timeout is False
    assert "Zaman aşımı" in msg_timeout

    monkeypatch.setattr(
        "managers.code_manager.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
    )
    ok_fail, msg_fail = m.run_shell_in_sandbox("echo hi", cwd=str(tmp_path))
    assert ok_fail is False
    assert "çıkış kodu: 2" in msg_fail
    assert "[stderr]" in msg_fail


def test_analyze_pytest_output_collects_fallback_failed_summary() -> None:
    output = """
2 failed, 5 passed
E   AssertionError: nope
core/router.py:88: AssertionError
"""
    analysis = CodeManager.analyze_pytest_output(output)
    assert analysis["has_failures"] is True
    assert analysis["failure_targets"][0]["target_path"] == "core/router.py"
    assert analysis["summary"] == "2 failed"


def test_run_shell_allow_shell_features_success_and_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manager(tmp_path)

    monkeypatch.setattr(
        "managers.code_manager.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="x" * 100, stderr=""),
    )
    ok, msg = m.run_shell("echo ok | cat", allow_shell_features=True)
    assert ok is True
    assert "ÇIKTI KIRPILDI" in msg

    def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr("managers.code_manager.subprocess.run", _boom)
    ok_boom, msg_boom = m.run_shell("echo ok", allow_shell_features=True)
    assert ok_boom is False
    assert "Kabuk hatası" in msg_boom


def test_grep_files_path_variants_and_list_directory_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manager(tmp_path)
    target = tmp_path / "one.py"
    target.write_text("print('A')\nprint('B')\n", encoding="utf-8")

    ok_file, out_file = m.grep_files("print", path=str(target), context_lines=1)
    assert ok_file is True
    assert "one.py" in out_file

    ok_missing, msg_missing = m.grep_files("print", path=str(tmp_path / "none"))
    assert ok_missing is False
    assert "Yol bulunamadı" in msg_missing

    monkeypatch.setattr(Path, "iterdir", lambda _self: (_ for _ in ()).throw(OSError("deny")))
    ok_ls, msg_ls = m.list_directory(str(tmp_path))
    assert ok_ls is False
    assert "Dizin listeleme hatası" in msg_ls


def test_validate_helpers_and_lsp_workspace_diagnostics_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manager(tmp_path)

    ok_py, _ = m.validate_python_syntax("x=1")
    bad_py, bad_py_msg = m.validate_python_syntax("def broken(:\n")
    ok_json, _ = m.validate_json('{"a":1}')
    bad_json, bad_json_msg = m.validate_json("{")

    assert ok_py is True and bad_py is False
    assert "Satır" in bad_py_msg
    assert ok_json is True and bad_json is False
    assert "JSON hatası" in bad_json_msg

    monkeypatch.setattr(m, "lsp_semantic_audit", lambda _p=None: (True, {"issues": [], "summary": "clean"}))
    ok_diag, diag_msg = m.lsp_workspace_diagnostics()
    assert ok_diag is True
    assert diag_msg == "clean"


class _Proc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, timeout: bool = False):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._timeout = timeout

    def communicate(self, _payload: bytes, timeout: int):
        if self._timeout:
            raise subprocess.TimeoutExpired(cmd="lsp", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None


def test_run_lsp_sequence_success_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _manager(tmp_path)
    py_file = tmp_path / "a.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    m.enable_lsp = False
    with pytest.raises(RuntimeError, match="ENABLE_LSP"):
        m._run_lsp_sequence(primary_path=py_file, request_method=None)

    m.enable_lsp = True
    txt_file = tmp_path / "a.txt"
    txt_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="desteklenmeyen"):
        m._run_lsp_sequence(primary_path=txt_file, request_method=None)

    monkeypatch.setattr(m, "_resolve_lsp_command", lambda _lang: ["missing-binary"])
    monkeypatch.setattr("managers.code_manager.subprocess.Popen", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(FileNotFoundError, match="LSP binary bulunamadı"):
        m._run_lsp_sequence(primary_path=py_file, request_method=None)

    monkeypatch.setattr("managers.code_manager.subprocess.Popen", lambda *_a, **_k: _Proc(timeout=True))
    with pytest.raises(RuntimeError, match="zaman aşımına"):
        m._run_lsp_sequence(primary_path=py_file, request_method=None)

    monkeypatch.setattr("managers.code_manager.subprocess.Popen", lambda *_a, **_k: _Proc(stderr=b"bad", returncode=3))
    with pytest.raises(RuntimeError, match="bad"):
        m._run_lsp_sequence(primary_path=py_file, request_method=None)

    response = _encode_lsp_message({"jsonrpc": "2.0", "id": 2, "result": []})
    monkeypatch.setattr("managers.code_manager.subprocess.Popen", lambda *_a, **_k: _Proc(stdout=response))
    messages = m._run_lsp_sequence(primary_path=py_file, request_method="textDocument/definition", request_params={})
    assert messages[0]["id"] == 2
