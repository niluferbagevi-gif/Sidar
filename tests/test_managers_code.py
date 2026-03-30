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
from pathlib import Path
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
