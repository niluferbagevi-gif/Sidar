"""
managers/code_manager.py için ek testler — eksik satırları kapsar.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


def _make_code_manager(tmpdir=None):
    cm = _get_cm()
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

class TestUriHelpers:
    def test_path_to_file_uri(self):
        cm = _get_cm()
        result = cm._path_to_file_uri(Path("/tmp/test.py"))
        assert result.startswith("file://")
        assert "test.py" in result

    def test_file_uri_to_path_posix(self):
        cm = _get_cm()
        result = cm._file_uri_to_path("file:///tmp/test.py")
        assert str(result).endswith("test.py")

    def test_file_uri_invalid_scheme(self):
        cm = _get_cm()
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            cm._file_uri_to_path("http:///tmp/test.py")


# ══════════════════════════════════════════════════════════════
# _decode_lsp_stream (65-86) — incomplete body error
# ══════════════════════════════════════════════════════════════

class TestDecodeLSPStream:
    def test_valid_message(self):
        cm = _get_cm()
        import json
        body = json.dumps({"method": "test"}).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        raw = header + body
        messages = cm._decode_lsp_stream(raw)
        assert len(messages) == 1
        assert messages[0]["method"] == "test"

    def test_no_header_separator(self):
        cm = _get_cm()
        messages = cm._decode_lsp_stream(b"no separator here")
        assert messages == []

    def test_incomplete_body_raises(self):
        cm = _get_cm()
        # Create a message claiming 100 bytes but only providing 10
        raw = b"Content-Length: 100\r\n\r\n" + b"tooshort"
        with pytest.raises(cm._LSPProtocolError):
            cm._decode_lsp_stream(raw)


# ══════════════════════════════════════════════════════════════
# _resolve_runtime() (142-152)
# ══════════════════════════════════════════════════════════════

class TestResolveRuntime:
    def test_gvisor_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.docker_microvm_mode = "gvisor"
            manager.docker_runtime = ""
            manager.docker_allowed_runtimes = ["", "runsc"]
            result = manager._resolve_runtime()
            assert result == "runsc"

    def test_kata_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.docker_microvm_mode = "kata"
            manager.docker_runtime = ""
            manager.docker_allowed_runtimes = ["", "kata-runtime"]
            result = manager._resolve_runtime()
            assert result == "kata-runtime"

    def test_not_in_allowed_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.docker_runtime = "custom_runtime"
            manager.docker_allowed_runtimes = ["", "runc"]
            result = manager._resolve_runtime()
            assert result == ""


# ══════════════════════════════════════════════════════════════
# _try_docker_cli_fallback() (246-265)
# ══════════════════════════════════════════════════════════════

class TestTryDockerCliFallback:
    def test_docker_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1)
            with patch("subprocess.run", return_value=mock_result):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0)
            with patch("subprocess.run", return_value=mock_result):
                result = manager._try_docker_cli_fallback()
            assert result is True
            assert manager.docker_available is True

    def test_docker_cli_timeout_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker info", 5)):
                result = manager._try_docker_cli_fallback()
            assert result is False

    def test_docker_cli_permission_error_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("subprocess.run", side_effect=PermissionError("permission denied")):
                result = manager._try_docker_cli_fallback()
            assert result is False


class TestTryWslSocketFallback:
    def test_returns_false_when_socket_stat_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            docker_module = types.SimpleNamespace(DockerClient=MagicMock())

            with patch.object(cm.os, "stat", side_effect=OSError("missing")):
                result = manager._try_wsl_socket_fallback(docker_module)

            assert result is False
            assert manager.docker_available is False

    def test_returns_true_when_valid_socket_and_ping_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
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
            manager, base, cm = _make_code_manager(tmpdir)
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

class TestReadFile:
    def test_read_file_success_with_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\ny = 2\n")
            ok, content = manager.read_file(str(test_file))
            assert ok is True
            assert "1\t" in content

    def test_read_file_no_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\n")
            ok, content = manager.read_file(str(test_file), line_numbers=False)
            assert ok is True
            assert content == "x = 1\n"

    def test_read_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.read_file("/nonexistent/file.py")
            assert ok is False
            assert "bulunamadı" in msg

    def test_read_file_is_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.read_file(tmpdir)
            assert ok is False
            assert "dizin" in msg

    def test_read_file_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.security.can_read = lambda p: False
            ok, msg = manager.read_file("/tmp/file.py")
            assert ok is False

    def test_read_file_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("x = 1\n")
            with patch("builtins.open", side_effect=PermissionError):
                ok, msg = manager.read_file(str(test_file))
            assert ok is False
            assert "reddedildi" in msg


# ══════════════════════════════════════════════════════════════
# write_file() — (387-390)
# ══════════════════════════════════════════════════════════════

class TestWriteFile:
    def test_write_file_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "output.txt"
            ok, msg = manager.write_file(str(target), "content here")
            assert ok is True
            assert target.read_text() == "content here"

    def test_write_file_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.security.can_write = lambda p: False
            ok, msg = manager.write_file("/tmp/file.txt", "content")
            assert ok is False

    def test_write_file_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "bad.py"
            ok, msg = manager.write_file(str(target), "def broken(:\n", validate=True)
            assert ok is False
            assert "Sözdizimi" in msg

    def test_write_file_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "file.txt"
            with patch("builtins.open", side_effect=PermissionError):
                ok, msg = manager.write_file(str(target), "content")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# write_generated_test() (404-431)
# ══════════════════════════════════════════════════════════════

class TestWriteGeneratedTest:
    def test_append_to_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "tests/test_extra.py"
            target.parent.mkdir()
            target.write_text("# existing content\n")
            ok, msg = manager.write_generated_test(str(target), "def test_new(): pass")
            assert ok is True

    def test_idempotent_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "test_extra.py"
            target.write_text("def test_existing(): pass\n")
            ok, msg = manager.write_generated_test(str(target), "def test_existing(): pass")
            assert ok is True
            assert "zaten mevcut" in msg

    def test_empty_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.write_generated_test("/tmp/test.py", "")
            assert ok is False
            assert "boş" in msg


# ══════════════════════════════════════════════════════════════
# patch_file() (437-461)
# ══════════════════════════════════════════════════════════════

class TestPatchFile:
    def test_patch_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\ny = 2\n")
            ok, msg = manager.patch_file(str(target), "x = 1", "x = 10")
            assert ok is True
            assert target.read_text() == "x = 10\ny = 2\n"

    def test_patch_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\n")
            ok, msg = manager.patch_file(str(target), "z = 99", "z = 100")
            assert ok is False
            assert "bulunamadı" in msg

    def test_patch_multiple_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            target = Path(tmpdir) / "code.py"
            target.write_text("x = 1\nx = 1\n")
            ok, msg = manager.patch_file(str(target), "x = 1", "x = 2")
            assert ok is False
            assert "2 kez" in msg

    def test_patch_read_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.patch_file("/nonexistent/file.py", "old", "new")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# execute_code_local() (590-648)
# ══════════════════════════════════════════════════════════════

class TestExecuteCodeLocal:
    def test_local_execution_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
            with patch("subprocess.run", return_value=mock_result) as run_mock:
                ok, output = manager.execute_code_local("print('hello')")
            run_mock.assert_called_once()
            assert ok is True
            assert "hello" in output

    def test_local_execution_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, output = manager.execute_code_local("raise ValueError('test error')")
            assert ok is False

    def test_local_execution_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.execute_code_local("print('x')")
            assert ok is False

    def test_local_execution_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.docker_exec_timeout = 1
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
                ok, msg = manager.execute_code_local("while True: pass")
            assert ok is False
            assert "Zaman aşımı" in msg

    def test_local_execution_output_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
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

class TestExecuteCode:
    def test_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.execute_code("print('x')")
            assert ok is False

    def test_no_docker_fallback_to_local(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
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

class TestRunShellInSandbox:
    def test_no_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.security.can_execute = lambda: False
            ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False

    def test_empty_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.run_shell_in_sandbox("")
            assert ok is False

    def test_docker_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("shutil.which", return_value=None):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False
            assert "bulunamadı" in msg

    def test_timeout_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)):
                ok, msg = manager.run_shell_in_sandbox("sleep 100")
            assert ok is False
            assert "Zaman aşımı" in msg

    def test_filenotfounderror(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", side_effect=FileNotFoundError):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is False

    def test_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="output\n", stderr="")
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", return_value=mock_result):
                ok, msg = manager.run_shell_in_sandbox("ls")
            assert ok is True
            assert "output" in msg

    def test_failed_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1, stdout="", stderr="error\n")
            with patch("shutil.which", return_value="/usr/bin/docker"), \
                 patch("subprocess.run", return_value=mock_result):
                ok, msg = manager.run_shell_in_sandbox("bad_command")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# analyze_pytest_output() (730-797)
# ══════════════════════════════════════════════════════════════

class TestAnalyzePytestOutput:
    def test_parse_coverage_data(self):
        cm = _get_cm()
        output = (
            "core/module.py     100    20    50   80%   30-50\n"
            "tests/test_a.py     50     5    90%\n"
            "TOTAL              150    25    83%\n"
        )
        result = cm.CodeManager.analyze_pytest_output(output)
        assert "findings" in result

    def test_parse_failure(self):
        cm = _get_cm()
        output = (
            "FAILED tests/test_core.py::TestFoo::test_bar - AssertionError\n"
            "1 failed in 0.5s\n"
        )
        result = cm.CodeManager.analyze_pytest_output(output)
        assert "1 failed" in result.get("summary", "")

    def test_empty_output(self):
        cm = _get_cm()
        result = cm.CodeManager.analyze_pytest_output("")
        assert result is not None


# ══════════════════════════════════════════════════════════════
# validate_python_syntax() (around line 722)
# ══════════════════════════════════════════════════════════════

class TestValidatePythonSyntax:
    def test_valid_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.validate_python_syntax("x = 1\ny = 2\n")
            assert ok is True

    def test_invalid_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            ok, msg = manager.validate_python_syntax("def broken(:\n    pass\n")
            assert ok is False


# ══════════════════════════════════════════════════════════════
# _execute_code_with_docker_cli() (201-218)
# ══════════════════════════════════════════════════════════════

class TestExecuteCodeWithDockerCLI:
    def test_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("print('hello')", limits)
            assert ok is True

    def test_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            mock_result = MagicMock(returncode=1, stdout="", stderr="error")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("bad code", limits)
            assert ok is False

    def test_output_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, base, cm = _make_code_manager(tmpdir)
            manager.max_output_chars = 5
            mock_result = MagicMock(returncode=0, stdout="x" * 100, stderr="")
            limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "timeout": 10, "network_mode": "none"}
            with patch("subprocess.run", return_value=mock_result):
                ok, output = manager._execute_code_with_docker_cli("print('x'*100)", limits)
            assert "KIRPILDI" in output
