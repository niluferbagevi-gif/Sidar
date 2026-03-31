"""
managers/code_manager.py için birim testleri.
_path_to_file_uri, _file_uri_to_path, _encode_lsp_message, _decode_lsp_stream,
CodeManager._resolve_sandbox_limits.
"""
from __future__ import annotations

import json
import builtins
import subprocess
import sys
import tempfile
import types
from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock


def _get_cm():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DOCKER_RUNTIME = ""
        DOCKER_ALLOWED_RUNTIMES = ["", "runc"]
        DOCKER_MICROVM_MODE = "off"
        DOCKER_MEM_LIMIT = "256m"
        DOCKER_NETWORK_DISABLED = True
        DOCKER_NANO_CPUS = 1_000_000_000
        DOCKER_EXEC_TIMEOUT = 10
        ENABLE_LSP = False
        LSP_TIMEOUT_SECONDS = 15
        LSP_MAX_REFERENCES = 200
        PYTHON_LSP_SERVER = "pyright-langserver"
        TYPESCRIPT_LSP_SERVER = "typescript-language-server"

    cfg_stub.Config = _Cfg
    cfg_stub.SANDBOX_LIMITS = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10}
    sys.modules["config"] = cfg_stub

    sec_stub = types.ModuleType("managers.security")
    sec_stub.SANDBOX = 1
    sec_stub.SecurityManager = object
    sys.modules["managers.security"] = sec_stub

    if "managers.code_manager" in sys.modules:
        del sys.modules["managers.code_manager"]
    import managers.code_manager as cm
    return cm


def _make_code_manager():
    cm = _get_cm()
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_stub = types.ModuleType("config")

        class _Cfg:
            DOCKER_RUNTIME = ""
            DOCKER_ALLOWED_RUNTIMES = ["", "runc"]
            DOCKER_MICROVM_MODE = "off"
            DOCKER_MEM_LIMIT = "256m"
            DOCKER_NETWORK_DISABLED = True
            DOCKER_NANO_CPUS = 1_000_000_000
            DOCKER_EXEC_TIMEOUT = 10
            ENABLE_LSP = False
            LSP_TIMEOUT_SECONDS = 15
            LSP_MAX_REFERENCES = 200
            PYTHON_LSP_SERVER = "pyright-langserver"
            TYPESCRIPT_LSP_SERVER = "typescript-language-server"

        cfg_stub.Config = _Cfg
        cfg_stub.SANDBOX_LIMITS = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10}
        sys.modules["config"] = cfg_stub

        sec_stub = types.ModuleType("managers.security")
        sec_stub.SANDBOX = 1

        class _FakeSM:
            def __init__(self, *a, **kw):
                pass

        sec_stub.SecurityManager = _FakeSM
        sys.modules["managers.security"] = sec_stub

        if "managers.code_manager" in sys.modules:
            del sys.modules["managers.code_manager"]
        import managers.code_manager as cm2

        security = _FakeSM()
        mgr = cm2.CodeManager(
            security=security,
            base_dir=Path(tmpdir),
            cfg=_Cfg(),
        )
    return mgr, cm2


# ══════════════════════════════════════════════════════════════
# _path_to_file_uri
# ══════════════════════════════════════════════════════════════

class TestPathToFileUri:
    def test_returns_file_scheme(self):
        cm = _get_cm()
        uri = cm._path_to_file_uri(Path("/tmp/test.py"))
        assert uri.startswith("file://")

    def test_contains_path(self):
        cm = _get_cm()
        uri = cm._path_to_file_uri(Path("/home/user/code.py"))
        assert "code.py" in uri

    def test_spaces_encoded(self):
        cm = _get_cm()
        uri = cm._path_to_file_uri(Path("/tmp/my file.py"))
        assert " " not in uri


# ══════════════════════════════════════════════════════════════
# _file_uri_to_path
# ══════════════════════════════════════════════════════════════

class TestFileUriToPath:
    def test_valid_file_uri(self):
        cm = _get_cm()
        result = cm._file_uri_to_path("file:///tmp/test.py")
        assert str(result).endswith("test.py")

    def test_invalid_scheme_raises(self):
        cm = _get_cm()
        import pytest
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            cm._file_uri_to_path("http://example.com/file.py")

    def test_encoded_space_decoded(self):
        cm = _get_cm()
        result = cm._file_uri_to_path("file:///tmp/my%20file.py")
        assert "my file.py" in str(result)

    def test_windows_drive_returns_pure_windows_path_on_non_windows(self, monkeypatch):
        cm = _get_cm()
        monkeypatch.setattr(cm, "_OS_NAME", "nt")
        monkeypatch.setattr(cm.sys, "platform", "linux")

        result = cm._file_uri_to_path("file:///C:/Users/Test/file.py")

        assert isinstance(result, PureWindowsPath)
        assert str(result) == "C:\\Users\\Test\\file.py"

    def test_windows_drive_returns_path_on_win32(self, monkeypatch):
        cm = _get_cm()
        monkeypatch.setattr(cm, "_OS_NAME", "nt")
        monkeypatch.setattr(cm.sys, "platform", "win32")

        result = cm._file_uri_to_path("file:///D:/Work/repo/main.py")

        assert isinstance(result, PureWindowsPath)
        assert str(result).endswith("D:\\Work\\repo\\main.py")

    def test_windows_non_drive_path_returns_pure_windows_path(self, monkeypatch):
        cm = _get_cm()
        monkeypatch.setattr(cm, "_OS_NAME", "nt")
        monkeypatch.setattr(cm.sys, "platform", "win32")

        result = cm._file_uri_to_path("file:///Users/Test/file.py")

        assert isinstance(result, PureWindowsPath)
        assert str(result) == "Users\\Test\\file.py"


# ══════════════════════════════════════════════════════════════
# _encode_lsp_message
# ══════════════════════════════════════════════════════════════

class TestEncodeLspMessage:
    def test_returns_bytes(self):
        cm = _get_cm()
        result = cm._encode_lsp_message({"method": "initialize"})
        assert isinstance(result, bytes)

    def test_contains_content_length(self):
        cm = _get_cm()
        result = cm._encode_lsp_message({"method": "shutdown"})
        assert b"Content-Length:" in result

    def test_roundtrip(self):
        cm = _get_cm()
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        encoded = cm._encode_lsp_message(payload)
        # Body starts after \r\n\r\n
        header_end = encoded.find(b"\r\n\r\n")
        body = encoded[header_end + 4:]
        decoded = json.loads(body.decode("utf-8"))
        assert decoded["method"] == "initialize"


# ══════════════════════════════════════════════════════════════
# _decode_lsp_stream
# ══════════════════════════════════════════════════════════════

class TestDecodeLspStream:
    def test_single_message(self):
        cm = _get_cm()
        payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
        encoded = cm._encode_lsp_message(payload)
        messages = cm._decode_lsp_stream(encoded)
        assert len(messages) == 1
        assert messages[0]["id"] == 1

    def test_multiple_messages(self):
        cm = _get_cm()
        m1 = cm._encode_lsp_message({"id": 1})
        m2 = cm._encode_lsp_message({"id": 2})
        messages = cm._decode_lsp_stream(m1 + m2)
        assert len(messages) == 2
        assert messages[0]["id"] == 1
        assert messages[1]["id"] == 2

    def test_empty_bytes_returns_empty(self):
        cm = _get_cm()
        assert cm._decode_lsp_stream(b"") == []

    def test_truncated_raises(self):
        cm = _get_cm()
        payload = {"id": 1}
        encoded = cm._encode_lsp_message(payload)
        import pytest
        with pytest.raises(Exception):
            # Truncate after header so body is incomplete
            header_end = encoded.find(b"\r\n\r\n")
            cm._decode_lsp_stream(encoded[:header_end + 5])


# ══════════════════════════════════════════════════════════════
# CodeManager._resolve_sandbox_limits
# ══════════════════════════════════════════════════════════════

class TestResolveSandboxLimits:
    def test_returns_dict(self):
        mgr, cm = _make_code_manager()
        limits = mgr._resolve_sandbox_limits()
        assert isinstance(limits, dict)

    def test_memory_key_present(self):
        mgr, cm = _make_code_manager()
        limits = mgr._resolve_sandbox_limits()
        assert "memory" in limits

    def test_timeout_key_present(self):
        mgr, cm = _make_code_manager()
        limits = mgr._resolve_sandbox_limits()
        assert "timeout" in limits

    def test_pids_limit_at_least_1(self):
        mgr, cm = _make_code_manager()
        limits = mgr._resolve_sandbox_limits()
        assert limits["pids_limit"] >= 1

    def test_timeout_at_least_1(self):
        mgr, cm = _make_code_manager()
        limits = mgr._resolve_sandbox_limits()
        assert limits["timeout"] >= 1


class TestCodeManagerPermissionErrors:
    def test_read_file_permission_error_returns_access_denied(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_read=lambda _p: True)

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("no read permission")

        monkeypatch.setattr(builtins, "open", _raise_permission)
        monkeypatch.setattr("pathlib.Path.exists", lambda _path: True)
        monkeypatch.setattr("pathlib.Path.is_dir", lambda _path: False)

        ok, message = mgr.read_file("forbidden.txt")
        assert ok is False
        assert "Erişim reddedildi" in message

    def test_write_file_permission_error_returns_access_denied(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(
            can_write=lambda _p: True,
            get_safe_write_path=lambda _n: Path("/tmp/safe.txt"),
        )

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("no write permission")

        monkeypatch.setattr(builtins, "open", _raise_permission)

        ok, message = mgr.write_file("forbidden.txt", "data", validate=False)
        assert ok is False
        assert "Yazma erişimi reddedildi" in message

    def test_read_file_returns_not_found_for_missing_path(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_read=lambda _p: True)

        ok, message = mgr.read_file("missing-file.py")
        assert ok is False
        assert "Dosya bulunamadı" in message

    def test_write_file_rejects_invalid_python_when_validation_enabled(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(
            can_write=lambda _p: True,
            get_safe_write_path=lambda _n: Path("/tmp/safe.py"),
        )

        ok, message = mgr.write_file("broken.py", "def foo(:\n", validate=True)
        assert ok is False
        assert "Sözdizimi hatası" in message


class TestExecuteCodeFallbackLoops:
    def test_execute_code_timeout_kills_container(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, level=0)
        mgr.docker_available = True

        class _Container:
            status = "running"

            def reload(self):
                return None

            def kill(self):
                return None

            def remove(self, force=False):
                return None

        container = _Container()
        mgr.docker_client = types.SimpleNamespace(
            containers=types.SimpleNamespace(run=lambda **kwargs: container)
        )

        fake_time = iter([0.0, 5.0, 12.0])
        monkeypatch.setattr(cm.time, "time", lambda: next(fake_time))
        monkeypatch.setattr(cm.time, "sleep", lambda _v: None)

        ok, message = mgr.execute_code("while True: pass")
        assert ok is False
        assert "Zaman aşımı" in message

    def test_execute_code_docker_error_falls_back_to_local_after_cli_failure(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, level=0)
        mgr.docker_available = True
        mgr.docker_client = types.SimpleNamespace(
            containers=types.SimpleNamespace(run=MagicMock(side_effect=RuntimeError("daemon down")))
        )
        class _ImageNotFound(Exception):
            pass
        monkeypatch.setitem(
            sys.modules,
            "docker",
            types.SimpleNamespace(errors=types.SimpleNamespace(ImageNotFound=_ImageNotFound)),
        )

        monkeypatch.setattr(mgr, "_execute_code_with_docker_cli", MagicMock(side_effect=RuntimeError("cli failed")))
        monkeypatch.setattr(mgr, "execute_code_local", MagicMock(return_value=(True, "local fallback ok")))

        ok, message = mgr.execute_code("print('hi')")
        assert ok is True
        assert message == "local fallback ok"
        mgr.execute_code_local.assert_called_once()

    def test_execute_code_rejects_when_sandbox_mode_and_docker_unavailable(self):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, level=cm.SANDBOX)
        mgr.docker_available = False

        ok, message = mgr.execute_code("print('hi')")
        assert ok is False
        assert "güvenlik politikası gereği" in message

    def test_execute_code_local_surfaces_subprocess_errors(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True)

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("execution denied")

        monkeypatch.setattr(cm.subprocess, "run", _raise_permission)
        ok, message = mgr.execute_code_local("print('x')")
        assert ok is False
        assert "Subprocess çalıştırma hatası" in message
        assert "execution denied" in message


class TestRunShellInSandbox:
    def test_denies_when_execute_permission_missing(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: False)
        ok, message = mgr.run_shell_in_sandbox("pytest -q")
        assert ok is False
        assert "yetkisi yok" in message

    def test_blank_command_returns_error(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        ok, message = mgr.run_shell_in_sandbox("   ")
        assert ok is False
        assert "belirtilmedi" in message

    def test_invalid_cwd_returns_error(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd="/definitely/not/here")
        assert ok is False
        assert "Geçersiz çalışma dizini" in message

    def test_outside_project_cwd_rejected(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: False)
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "proje kökü dışında" in message

    def test_docker_cli_missing_returns_error(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: None)
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "Docker CLI bulunamadı" in message

    def test_timeout_returns_error(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(cm.subprocess, "run", MagicMock(side_effect=subprocess.TimeoutExpired("docker", 1)))
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "Zaman aşımı" in message

    def test_nonzero_exit_includes_stderr(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=2, stdout="line1", stderr="boom")),
        )
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "[stderr]" in message
        assert "çıkış kodu: 2" in message

    def test_unexpected_subprocess_error_returns_sandbox_error(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(cm.subprocess, "run", MagicMock(side_effect=RuntimeError("sandbox evasion detected")))
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "Sandbox komutu hatası" in message
        assert "sandbox evasion detected" in message

    def test_file_not_found_during_subprocess_returns_docker_cli_missing(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(cm.subprocess, "run", MagicMock(side_effect=FileNotFoundError("docker not found")))

        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is False
        assert "Docker CLI bulunamadı" in message

    def test_success_with_empty_output(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=0, stdout="", stderr="")),
        )
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is True
        assert "çıktı üretmedi" in message

    def test_success_with_stdout_output(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.base_dir = Path(".").resolve()
        mgr.security = types.SimpleNamespace(can_execute=lambda: True, is_path_under=lambda *_a, **_k: True)
        monkeypatch.setattr(cm.shutil, "which", lambda _name: "/usr/bin/docker")
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=0, stdout="all good", stderr="")),
        )
        ok, message = mgr.run_shell_in_sandbox("pytest -q", cwd=".")
        assert ok is True
        assert "all good" in message


class TestCodeManagerDockerCliMocking:
    def test_execute_code_with_docker_cli_truncates_large_output(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.max_output_chars = 10
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=0, stdout="x" * 50, stderr="")),
        )
        ok, output = mgr._execute_code_with_docker_cli(
            "print('x')",
            {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 10},
        )
        assert ok is True
        assert "ÇIKTI KIRPILDI" in output

    def test_build_docker_cli_command_contains_limits_and_code(self):
        mgr, _cm = _make_code_manager()
        limits = {
            "memory": "128m",
            "cpus": "0.25",
            "pids_limit": 32,
            "network_mode": "none",
            "timeout": 5,
        }
        cmd = mgr._build_docker_cli_command("print('ok')", limits)
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "--memory=128m" in cmd
        assert "--cpus=0.25" in cmd
        assert "--pids-limit=32" in cmd
        assert "--network=none" in cmd
        assert cmd[-3:] == ["python", "-c", "print('ok')"]

    def test_execute_code_with_docker_cli_returns_error_on_nonzero_exit(self, monkeypatch):
        mgr, cm = _make_code_manager()
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="traceback")),
        )
        ok, output = mgr._execute_code_with_docker_cli(
            "raise RuntimeError('boom')",
            {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 10},
        )
        assert ok is False
        assert "Docker CLI Sandbox" in output
        assert "traceback" in output

    def test_execute_code_with_docker_cli_uses_empty_output_fallback_on_error(self, monkeypatch):
        mgr, cm = _make_code_manager()
        monkeypatch.setattr(
            cm.subprocess,
            "run",
            MagicMock(return_value=types.SimpleNamespace(returncode=2, stdout="", stderr="")),
        )
        ok, output = mgr._execute_code_with_docker_cli(
            "print('x')",
            {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 10},
        )
        assert ok is False
        assert "(çıktı yok)" in output


class TestReadWritePermissionAndErrorEdges:
    def test_read_file_denied_when_security_rejects_path(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_read=lambda _path: False)
        ok, message = mgr.read_file("secret.py")
        assert ok is False
        assert "Okuma yetkisi yok" in message

    def test_read_file_permission_error_surface_message(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_read=lambda _path: True)
        target = Path(cm.__file__).resolve()

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(builtins, "open", _raise_permission)
        ok, message = mgr.read_file(str(target))
        assert ok is False
        assert "Erişim reddedildi" in message

    def test_write_file_denied_when_security_rejects_path(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: False,
            get_safe_write_path=lambda filename: Path("/safe") / filename,
        )
        ok, message = mgr.write_file("blocked/test.py", "print('x')")
        assert ok is False
        assert "Yazma yetkisi yok" in message
        assert "/safe/test.py" in message

    def test_write_file_permission_error_surface_message(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            get_safe_write_path=lambda filename: Path("/safe") / filename,
        )

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(builtins, "open", _raise_permission)
        ok, message = mgr.write_file("test_denied.txt", "abc", validate=False)
        assert ok is False
        assert "Yazma erişimi reddedildi" in message


class TestPytestOutputAnalysis:
    def test_extracts_coverage_targets_and_branch_arcs(self):
        mgr, _cm = _make_code_manager()
        sample = (
            "web_server.py 2406 1576 31% 100->exit, 152-165, 400\n"
            "tests/test_web_server.py 10 0 100% -\n"
            "TOTAL 2416 1576 35% ...\n"
        )
        result = mgr.analyze_pytest_output(sample)
        assert result["has_coverage_gaps"] is True
        assert result["coverage_targets"][0]["target_path"] == "web_server.py"
        assert "100->exit" in result["coverage_targets"][0]["missing_branch_arcs"]

    def test_extracts_failure_target_from_traceback_block(self):
        mgr, _cm = _make_code_manager()
        sample = (
            "tests/test_core_db.py:123: AssertionError\n"
            "=========================== short test summary info ===========================\n"
            "1 failed, 10 passed in 0.12s\n"
        )
        result = mgr.analyze_pytest_output(sample)
        assert result["has_failures"] is True
        assert result["failure_targets"][0]["target_path"] == "tests/test_core_db.py"

    def test_run_pytest_and_collect_rejects_non_pytest_commands(self):
        mgr, _cm = _make_code_manager()
        result = mgr.run_pytest_and_collect(command="echo hello")
        assert result["success"] is False
        assert "Yalnızca pytest" in result["output"]


class TestCodeManagerFileIOWithTmpPath:
    def test_write_and_read_file_roundtrip_without_line_numbers(self, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "roundtrip.py"
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            can_read=lambda _path: True,
            get_safe_write_path=lambda filename: tmp_path / filename,
        )

        ok_write, _msg = mgr.write_file(str(target), "print('ok')\n", validate=True)
        ok_read, content = mgr.read_file(str(target), line_numbers=False)

        assert ok_write is True
        assert ok_read is True
        assert content == "print('ok')\n"

    def test_write_generated_test_appends_once_and_is_idempotent(self, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "tests" / "test_sample.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            can_read=lambda _path: True,
            get_safe_write_path=lambda filename: tmp_path / filename,
        )

        snippet = "```python\ndef test_new_case():\n    assert 1 == 1\n```"
        ok_first, msg_first = mgr.write_generated_test(str(target), snippet, append=True)
        ok_second, msg_second = mgr.write_generated_test(str(target), snippet, append=True)
        final_content = target.read_text(encoding="utf-8")

        assert ok_first is True
        assert "kaydedildi" in msg_first
        assert ok_second is True
        assert "zaten mevcut" in msg_second
        assert final_content.count("def test_new_case") == 1

    def test_write_generated_test_rejects_empty_content(self, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "tests" / "test_empty.py"
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            can_read=lambda _path: True,
            get_safe_write_path=lambda filename: tmp_path / filename,
        )

        ok, message = mgr.write_generated_test(str(target), "   ", append=True)
        assert ok is False
        assert "boş" in message.lower()


class TestCodeManagerMissingPathAndAstEdges:
    def test_read_file_returns_not_found_for_missing_file(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_read=lambda _path: True)

        ok, message = mgr.read_file("olmayan_dosya.py")
        assert ok is False
        assert "Dosya bulunamadı" in message

    def test_list_directory_returns_error_for_missing_directory(self):
        mgr, _cm = _make_code_manager()
        ok, message = mgr.list_directory("olmayan_dizin")
        assert ok is False
        assert "Dizin bulunamadı" in message

    def test_write_file_creates_missing_parent_directory(self, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "nested" / "deeper" / "created.py"
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            get_safe_write_path=lambda filename: tmp_path / filename,
        )

        ok, message = mgr.write_file(str(target), "x = 1\n", validate=True)
        assert ok is True
        assert "başarıyla kaydedildi" in message
        assert target.exists()

    def test_write_file_rejects_invalid_python_syntax_and_does_not_create_file(self, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "broken.py"
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            get_safe_write_path=lambda filename: tmp_path / filename,
        )

        ok, message = mgr.write_file(str(target), "def broken(:\n    pass\n", validate=True)
        assert ok is False
        assert "Sözdizimi hatası" in message
        assert not target.exists()

    def test_validate_python_syntax_reports_line_for_ast_edge_case(self):
        mgr, _cm = _make_code_manager()
        code = "x = 1\nif True print('x')\n"
        ok, message = mgr.validate_python_syntax(code)
        assert ok is False
        assert "Satır" in message


class TestCodeManagerShellGrepAndLspEdges:
    def test_run_shell_blocks_shell_features_when_disabled(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_run_shell=lambda: True)
        ok, message = mgr.run_shell("echo test | cat", allow_shell_features=False)
        assert ok is False
        assert "shell operatörleri içeriyor" in message

    def test_run_shell_invalid_split_returns_parse_error(self):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_run_shell=lambda: True)
        ok, message = mgr.run_shell("echo 'unterminated", allow_shell_features=False)
        assert ok is False
        assert "Komut ayrıştırılamadı" in message

    def test_run_shell_timeout_returns_timeout_message(self, monkeypatch):
        mgr, cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(can_run_shell=lambda: True)

        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="x", timeout=60)

        monkeypatch.setattr(cm.subprocess, "run", _raise_timeout)
        ok, message = mgr.run_shell("python -c \"while True: pass\"")
        assert ok is False
        assert "Zaman aşımı" in message

    def test_grep_files_invalid_regex_returns_error(self):
        mgr, _cm = _make_code_manager()
        ok, message = mgr.grep_files(pattern="(", path=".")
        assert ok is False
        assert "Geçersiz regex kalıbı" in message

    def test_lsp_semantic_audit_returns_no_targets_for_unknown_extension(self, tmp_path):
        mgr, _cm = _make_code_manager()
        non_code = tmp_path / "note.txt"
        non_code.write_text("hello", encoding="utf-8")
        ok, payload = mgr.lsp_semantic_audit(paths=[str(non_code)])
        assert ok is False
        assert payload["status"] == "no-targets"

    def test_lsp_semantic_audit_returns_tool_error_when_lsp_raises(self, tmp_path, monkeypatch):
        mgr, _cm = _make_code_manager()
        py_file = tmp_path / "sample.py"
        py_file.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(mgr, "_run_lsp_sequence", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("lsp offline")))
        ok, payload = mgr.lsp_semantic_audit(paths=[str(py_file)])
        assert ok is False
        assert payload["status"] == "tool-error"
        assert "lsp offline" in payload["summary"].lower()


class TestCodeManagerFsAndAstErrorEdges:
    def test_write_file_returns_permission_error_when_parent_mkdir_denied(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        mgr.security = types.SimpleNamespace(
            can_write=lambda _path: True,
            get_safe_write_path=lambda filename: Path("/safe") / filename,
        )

        def _raise_permission(*_args, **_kwargs):
            raise PermissionError("mkdir denied")

        monkeypatch.setattr("pathlib.Path.mkdir", _raise_permission)
        ok, message = mgr.write_file("nested/file.py", "x = 1\n", validate=True)
        assert ok is False
        assert "Yazma erişimi reddedildi" in message

    def test_list_directory_returns_error_when_iterdir_permission_denied(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        monkeypatch.setattr("pathlib.Path.exists", lambda _path: True)
        monkeypatch.setattr("pathlib.Path.is_dir", lambda _path: True)
        monkeypatch.setattr(
            "pathlib.Path.iterdir",
            lambda _path: (_ for _ in ()).throw(PermissionError("dir denied")),
        )

        ok, message = mgr.list_directory(".")
        assert ok is False
        assert "Dizin listeleme hatası" in message

    def test_audit_project_reports_unreadable_python_file(self, tmp_path, monkeypatch):
        mgr, _cm = _make_code_manager()
        broken_file = tmp_path / "broken.py"
        broken_file.write_text("print('ok')\n", encoding="utf-8")

        original_read_text = Path.read_text

        def _read_text(path_obj, *args, **kwargs):
            if path_obj == broken_file:
                raise PermissionError("read denied")
            return original_read_text(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _read_text)
        report = mgr.audit_project(root=str(tmp_path))
        assert "Hatalı" in report
        assert "Okunamadı" in report

    def test_lsp_workspace_diagnostics_reports_file_not_found_for_missing_binary(self, tmp_path, monkeypatch):
        mgr, _cm = _make_code_manager()
        py_file = tmp_path / "sample.py"
        py_file.write_text("x = 1\n", encoding="utf-8")
        mgr.enable_lsp = True
        mgr.python_lsp_server = "pyright-langserver"

        monkeypatch.setattr(
            mgr,
            "_run_lsp_sequence",
            lambda **_kwargs: (_ for _ in ()).throw(FileNotFoundError("LSP binary bulunamadı: pyright-langserver")),
        )

        ok, message = mgr.lsp_workspace_diagnostics(paths=[str(py_file)])
        assert ok is False
        assert "LSP binary bulunamadı" in message


class TestCodeManagerGeneratedTestPermissionEdges:
    def test_write_generated_test_returns_error_when_existing_file_cannot_be_read(self, monkeypatch, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "tests" / "test_blocked.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_old():\n    assert True\n", encoding="utf-8")

        monkeypatch.setattr(mgr, "read_file", lambda *_a, **_k: (False, "[OpenClaw] Erişim reddedildi"))
        ok, message = mgr.write_generated_test(str(target), "def test_new():\n    assert True\n", append=True)

        assert ok is False
        assert "Erişim reddedildi" in message

    def test_write_generated_test_surfaces_write_permission_error(self, monkeypatch, tmp_path):
        mgr, _cm = _make_code_manager()
        target = tmp_path / "tests" / "test_denied.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_old():\n    assert True\n", encoding="utf-8")

        monkeypatch.setattr(mgr, "read_file", lambda *_a, **_k: (True, "def test_old():\n    assert True\n"))
        monkeypatch.setattr(mgr, "write_file", lambda *_a, **_k: (False, "[OpenClaw] Yazma erişimi reddedildi"))
        ok, message = mgr.write_generated_test(str(target), "def test_new():\n    assert True\n", append=True)

        assert ok is False
        assert "Yazma erişimi reddedildi" in message


class TestCodeManagerPatchFileFailureModes:
    def test_patch_file_returns_not_found_error_when_target_block_missing(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        monkeypatch.setattr(mgr, "read_file", lambda *_a, **_k: (True, "def a():\n    return 1\n"))

        ok, message = mgr.patch_file("dummy.py", "def missing():\n    pass", "def replaced():\n    pass")

        assert ok is False
        assert "Hedef kod bloğu" in message
        assert "bulunamadı" in message

    def test_patch_file_returns_ambiguous_error_when_target_block_repeats(self, monkeypatch):
        mgr, _cm = _make_code_manager()
        repeated = "x = 1\nx = 1\n"
        monkeypatch.setattr(mgr, "read_file", lambda *_a, **_k: (True, repeated))

        ok, message = mgr.patch_file("dummy.py", "x = 1", "x = 2")

        assert ok is False
        assert "kez geçiyor" in message

# ===== MERGED FROM tests/test_managers_code_extra.py =====

import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _extra_get_cm():
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DOCKER_RUNTIME = ""
        DOCKER_ALLOWED_RUNTIMES = ["", "runc"]
        DOCKER_MICROVM_MODE = "off"
        DOCKER_MEM_LIMIT = "256m"
        DOCKER_NETWORK_DISABLED = True
        DOCKER_NANO_CPUS = 1_000_000_000
        DOCKER_EXEC_TIMEOUT = 10
        DOCKER_REQUIRED = False
        ENABLE_LSP = False
        LSP_TIMEOUT_SECONDS = 15
        LSP_MAX_REFERENCES = 200
        PYTHON_LSP_SERVER = "pyright-langserver"
        TYPESCRIPT_LSP_SERVER = "typescript-language-server"
        SANDBOX_LIMITS = {}

        def __getattr__(self, name):
            return None

    cfg_stub.Config = _Cfg
    cfg_stub.SANDBOX_LIMITS = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10}
    sys.modules["config"] = cfg_stub

    sec_stub = types.ModuleType("managers.security")
    sec_stub.SANDBOX = 1

    class _FakeSM:
        level = 2  # Not SANDBOX
        def can_read(self, path): return True
        def can_write(self, path): return True
        def can_execute(self): return True
        def get_safe_write_path(self, name): return Path("/tmp") / name
        def is_path_under(self, path, base): return True

    sec_stub.SecurityManager = _FakeSM
    sys.modules["managers.security"] = sec_stub

    if "managers.code_manager" in sys.modules:
        del sys.modules["managers.code_manager"]
    import managers.code_manager as cm
    return cm


def _extra_make_code_manager(tmpdir=None):
    cm = _extra_get_cm()
    base = Path(tmpdir) if tmpdir else Path(tempfile.mkdtemp())
    cfg = cm.sys.modules["config"].Config()

    class _FakeSM:
        level = 2
        def can_read(self, path): return True
        def can_write(self, path): return True
        def can_execute(self): return True
        def get_safe_write_path(self, name): return base / name
        def is_path_under(self, path, b): return True

    with patch.object(cm.CodeManager, "_init_docker"):
        manager = cm.CodeManager(
            security=_FakeSM(),
            base_dir=base,
            cfg=cfg,
        )
        manager.docker_available = False
        manager.docker_client = None
    return manager, base, cm


# ══════════════════════════════════════════════════════════════
# _path_to_file_uri / _file_uri_to_path (40-56)
# ══════════════════════════════════════════════════════════════

class Extra_TestUriHelpers:
    def test_path_to_file_uri(self):
        cm = _extra_get_cm()
        result = cm._path_to_file_uri(Path("/tmp/test.py"))
        assert result.startswith("file://")
        assert "test.py" in result

    def test_file_uri_to_path_posix(self):
        cm = _extra_get_cm()
        result = cm._file_uri_to_path("file:///tmp/test.py")
        assert str(result).endswith("test.py")

    def test_file_uri_invalid_scheme(self):
        cm = _extra_get_cm()
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            cm._file_uri_to_path("http:///tmp/test.py")


# ══════════════════════════════════════════════════════════════
# _decode_lsp_stream (65-86) — incomplete body error
# ══════════════════════════════════════════════════════════════

class Extra_TestDecodeLSPStream:
    def test_valid_message(self):
        cm = _extra_get_cm()
        import json
        body = json.dumps({"method": "test"}).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        raw = header + body
        messages = cm._decode_lsp_stream(raw)
        assert len(messages) == 1
        assert messages[0]["method"] == "test"

    def test_no_header_separator(self):
        cm = _extra_get_cm()
        messages = cm._decode_lsp_stream(b"no separator here")
        assert messages == []

    def test_incomplete_body_raises(self):
        cm = _extra_get_cm()
        # Create a message claiming 100 bytes but only providing 10
        raw = b"Content-Length: 100\r\n\r\n" + b"tooshort"
        with pytest.raises(cm._LSPProtocolError):
            cm._decode_lsp_stream(raw)


# ══════════════════════════════════════════════════════════════
# _resolve_runtime() (142-152)
# ══════════════════════════════════════════════════════════════

class Extra_TestResolveRuntime:
    def test_gvisor_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.docker_microvm_mode = "gvisor"
            manager.docker_runtime = ""
            manager.docker_allowed_runtimes = ["", "runsc"]
            result = manager._resolve_runtime()
            assert result == "runsc"

    def test_kata_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.docker_microvm_mode = "kata"
            manager.docker_runtime = ""
            manager.docker_allowed_runtimes = ["", "kata-runtime"]
            result = manager._resolve_runtime()
            assert result == "kata-runtime"

    def test_not_in_allowed_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.docker_runtime = "custom_runtime"
            manager.docker_allowed_runtimes = ["", "runc"]
            result = manager._resolve_runtime()
            assert result == ""


# ══════════════════════════════════════════════════════════════
# _try_docker_cli_fallback() (246-265)
# ══════════════════════════════════════════════════════════════

class Extra_TestTryDockerCliFallback:
    def test_docker_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1)
            with patch("subprocess.run", return_value=mock_result):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0)
            with patch("subprocess.run", return_value=mock_result):
                result = manager._try_docker_cli_fallback()
            assert result is True
            assert manager.docker_available is True

    def test_docker_cli_timeout_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker info", 5)):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_cli_permission_error_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=PermissionError("permission denied")):
                result = manager._try_docker_cli_fallback()
            assert result is False


class Extra_TestTryWslSocketFallback:
    def test_returns_false_when_socket_stat_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            docker_module = types.SimpleNamespace(DockerClient=MagicMock())

            with patch.object(cm.os, "stat", side_effect=OSError("missing")):
                result = manager._try_wsl_socket_fallback(docker_module)

            assert result is False
            assert manager.docker_available is False

    def test_returns_true_when_valid_socket_and_ping_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            fake_client = types.SimpleNamespace(ping=MagicMock())
            docker_module = types.SimpleNamespace(DockerClient=MagicMock(return_value=fake_client))
            fake_stat = types.SimpleNamespace(st_mode=0o140000)

            with patch.object(cm.os, "stat", return_value=fake_stat), patch.object(cm.stat, "S_ISSOCK", return_value=True):
                result = manager._try_wsl_socket_fallback(docker_module)

            assert result is True
            assert manager.docker_available is True
            assert manager.docker_client is fake_client

    def test_tries_next_socket_when_ping_fails_with_connection_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            failing_client = types.SimpleNamespace(ping=MagicMock(side_effect=Exception("Connection refused")))
            healthy_client = types.SimpleNamespace(ping=MagicMock())
            docker_module = types.SimpleNamespace(
                DockerClient=MagicMock(side_effect=[failing_client, healthy_client])
            )
            fake_stat = types.SimpleNamespace(st_mode=0o140000)

            with patch.object(cm.os, "stat", return_value=fake_stat), patch.object(cm.stat, "S_ISSOCK", return_value=True):
                result = manager._try_wsl_socket_fallback(docker_module)

            assert result is True
            assert manager.docker_available is True
            assert manager.docker_client is healthy_client


# ══════════════════════════════════════════════════════════════
# read_file() — (326, 336-342, 346-349)
# ══════════════════════════════════════════════════════════════

class Extra_TestReadFile:
    def test_read_file_success_with_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\ny = 2\n")
            ok, content = manager.read_file(str(test_file))
            assert ok is True
            assert "1\t" in content

    def test_read_file_no_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\n")
            ok, content = manager.read_file(str(test_file), line_numbers=False)
            assert ok is True
            assert content == "x = 1\n"

    def test_read_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.read_file("/nonexistent/file.py")
            assert ok is False
            assert "bulunamadı" in msg

    def test_read_file_is_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.read_file(tmpdir)
            assert ok is False
            assert "dizin" in msg

    def test_read_file_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.security.can_read = lambda p: False
            ok, msg = manager.read_file("/tmp/file.py")
            assert ok is False

    def test_read_file_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\n")
            with patch("builtins.open", side_effect=PermissionError):
                ok, msg = manager.read_file(str(test_file))
            assert ok is False
            assert "reddedildi" in msg


# ══════════════════════════════════════════════════════════════
# write_file() — (387-390)
# ══════════════════════════════════════════════════════════════

class Extra_TestWriteFile:
    def test_write_file_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "output.txt"
            ok, msg = manager.write_file(str(target), "content here")
            assert ok is True
            assert target.read_text() == "content here"

    def test_write_file_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.security.can_write = lambda p: False
            ok, msg = manager.write_file("/tmp/file.txt", "content")
            assert ok is False

    def test_write_file_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "bad.py"
            ok, msg = manager.write_file(str(target), "def broken(:\n", validate=True)
            assert ok is False
            assert "Sözdizimi" in msg

    def test_write_file_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "file.txt"
            with patch("builtins.open", side_effect=PermissionError):
                ok, msg = manager.write_file(str(target), "content")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# write_generated_test() (404-431)
# ══════════════════════════════════════════════════════════════

class Extra_TestWriteGeneratedTest:
    def test_append_to_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "tests/test_extra.py"
            target.parent.mkdir()
            target.write_text("# existing content\n")
            ok, msg = manager.write_generated_test(str(target), "def test_new(): pass")
            assert ok is True

    def test_idempotent_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "test_extra.py"
            target.write_text("def test_existing(): pass\n")
            ok, msg = manager.write_generated_test(str(target), "def test_existing(): pass")
            assert ok is True
            assert "zaten mevcut" in msg

    def test_empty_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.write_generated_test("/tmp/test.py", "")
            assert ok is False
            assert "boş" in msg


# ══════════════════════════════════════════════════════════════
# patch_file() (437-461)
# ══════════════════════════════════════════════════════════════

class Extra_TestPatchFile:
    def test_patch_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\ny = 2\n")
            ok, msg = manager.patch_file(str(target), "x = 1", "x = 10")
            assert ok is True
            assert target.read_text() == "x = 10\ny = 2\n"

    def test_patch_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\n")
            ok, msg = manager.patch_file(str(target), "z = 99", "z = 100")
            assert ok is False
            assert "bulunamadı" in msg

    def test_patch_multiple_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\nx = 1\n")
            ok, msg = manager.patch_file(str(target), "x = 1", "x = 2")
            assert ok is False
            assert "2 kez" in msg

    def test_patch_read_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.patch_file("/nonexistent/file.py", "old", "new")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# execute_code_local() (590-648)
# ══════════════════════════════════════════════════════════════

class Extra_TestExecuteCodeLocal:
    def test_local_execution_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
            with patch("subprocess.run", return_value=mock_result) as run_mock:
                ok, output = manager.execute_code_local("print('hello')")
            run_mock.assert_called_once()
            assert ok is True
            assert "hello" in output

    def test_local_execution_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, output = manager.execute_code_local("raise ValueError('test error')")
            assert ok is False

    def test_local_execution_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.execute_code_local("print('x')")
            assert ok is False

    def test_local_execution_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.docker_exec_timeout = 1
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
                ok, msg = manager.execute_code_local("while True: pass")
            assert ok is False
            assert "Zaman aşımı" in msg

    def test_local_execution_output_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.max_output_chars = 10
            mock_result = MagicMock(returncode=0, stdout=("x" * 100), stderr="")
            with patch("subprocess.run", return_value=mock_result) as run_mock:
                ok, output = manager.execute_code_local("print('x' * 100)")
            run_mock.assert_called_once()
            assert ok is True
            assert "KIRPILDI" in output


# ══════════════════════════════════════════════════════════════
# execute_code() — no docker paths (475-490)
# ══════════════════════════════════════════════════════════════

class Extra_TestExecuteCode:
    def test_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.execute_code("print('x')")
            assert ok is False

    def test_no_docker_fallback_to_local(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.docker_available = False
            manager.security.level = 2  # Not SANDBOX
            with patch.object(manager, "execute_code_local", return_value=(True, "fallback-ok")) as local_exec:
                ok, output = manager.execute_code("print('fallback')")
            local_exec.assert_called_once_with("print('fallback')")
            assert ok is True
            assert "fallback-ok" in output


# ══════════════════════════════════════════════════════════════
# run_shell_in_sandbox() (654-728)
# ══════════════════════════════════════════════════════════════

class Extra_TestRunShellInSandbox:
    def test_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False

    def test_empty_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.run_shell_in_sandbox("")
            assert ok is False

    def test_docker_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("shutil.which", return_value=None):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False
            assert "bulunamadı" in msg

    def test_timeout_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)):
                ok, msg = manager.run_shell_in_sandbox("sleep 100")
            assert ok is False
            assert "Zaman aşımı" in msg

    def test_filenotfounderror(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", side_effect=FileNotFoundError):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False

    def test_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="output\n", stderr="")
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", return_value=mock_result):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is True
            assert "output" in msg

    def test_failed_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1, stdout="", stderr="error\n")
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", return_value=mock_result):
                ok, msg = manager.run_shell_in_sandbox("bad_command")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# analyze_pytest_output() (730-797)
# ══════════════════════════════════════════════════════════════

class Extra_TestAnalyzePytestOutput:
    def test_parse_coverage_data(self):
        cm = _extra_get_cm()
        output = (
            "core/module.py     100    20    50   80%   30-50\n"
            "tests/test_a.py     50     5    90%\n"
            "TOTAL              150    25    83%\n"
        )
        result = cm.CodeManager.analyze_pytest_output(output)
        assert "findings" in result

    def test_parse_failure(self):
        cm = _extra_get_cm()
        output = (
            "FAILED tests/test_core.py::TestFoo::test_bar - AssertionError\n"
            "1 failed in 0.5s\n"
        )
        result = cm.CodeManager.analyze_pytest_output(output)
        assert "1 failed" in result.get("summary", "")

    def test_empty_output(self):
        cm = _extra_get_cm()
        result = cm.CodeManager.analyze_pytest_output("")
        assert result is not None


# ══════════════════════════════════════════════════════════════
# validate_python_syntax() (around line 722)
# ══════════════════════════════════════════════════════════════

class Extra_TestValidatePythonSyntax:
    def test_valid_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.validate_python_syntax("x = 1\ny = 2\n")
            assert ok is True

    def test_invalid_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            ok, msg = manager.validate_python_syntax("def broken(:\n    pass\n")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# _execute_code_with_docker_cli() (201-218)
# ══════════════════════════════════════════════════════════════

class Extra_TestExecuteCodeWithDockerCLI:
    def test_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("print('hello')", limits)
            assert ok is True

    def test_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1, stdout="", stderr="error")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("bad code", limits)
            assert ok is False

    def test_output_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _extra_make_code_manager(tmpdir)
            manager.max_output_chars = 5
            mock_result = MagicMock(returncode=0, stdout="x" * 100, stderr="")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("print('x'*100)", limits)
            assert "KIRPILDI" in output
