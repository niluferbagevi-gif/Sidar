from pathlib import Path
from types import SimpleNamespace

import pytest

from managers import code_manager


def test_path_to_file_uri_and_back_roundtrip() -> None:
    path = Path("pyproject.toml")
    uri = code_manager._path_to_file_uri(path)
    resolved = code_manager._file_uri_to_path(uri)
    assert str(resolved).endswith("pyproject.toml")


def test_file_uri_to_path_rejects_non_file_scheme() -> None:
    with pytest.raises(ValueError):
        code_manager._file_uri_to_path("https://example.com/a.py")


def test_encode_and_decode_lsp_messages() -> None:
    encoded = code_manager._encode_lsp_message({"id": 1, "method": "initialize"})
    decoded = code_manager._decode_lsp_stream(encoded)
    assert decoded == [{"id": 1, "method": "initialize"}]


def test_decode_lsp_stream_raises_for_truncated_body() -> None:
    with pytest.raises(code_manager._LSPProtocolError):
        code_manager._decode_lsp_stream(b"Content-Length: 10\r\n\r\n{}")


def test_resolve_runtime_uses_allowed_runtime() -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.docker_runtime = ""
    manager.docker_microvm_mode = "gvisor"
    manager.docker_allowed_runtimes = ["", "runsc", "kata-runtime"]
    assert manager._resolve_runtime() == "runsc"


def test_resolve_sandbox_limits_falls_back_for_invalid_values() -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.cfg = SimpleNamespace(
        SANDBOX_LIMITS={"memory": "128m", "cpus": "invalid", "pids_limit": 0, "timeout": 0, "network": "none"}
    )
    manager.docker_mem_limit = "256m"
    manager.docker_exec_timeout = 10
    manager.docker_nano_cpus = 123
    limits = manager._resolve_sandbox_limits()

    assert limits["memory"] == "128m"
    assert limits["nano_cpus"] == 123
    assert limits["pids_limit"] == 64
    assert limits["timeout"] == 10
    assert limits["network_mode"] == "none"


def test_execute_code_with_docker_cli_truncates_output(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.base_dir = Path.cwd()
    manager.max_output_chars = 20
    manager.docker_image = "python:3.11-alpine"

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="x" * 40, stderr="")

    monkeypatch.setattr(code_manager.subprocess, "run", _fake_run)

    ok, output = manager._execute_code_with_docker_cli("print('x')", {"memory": "128m", "cpus": "1", "pids_limit": 16, "network_mode": "none", "timeout": 1})

    assert ok is False
    assert "ÇIKTI KIRPILDI" in output
    assert "Docker CLI Sandbox" in output


def test_try_docker_cli_fallback_success(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.base_dir = Path.cwd()
    manager.docker_available = False
    manager.docker_client = object()

    monkeypatch.setattr(
        code_manager.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )

    assert manager._try_docker_cli_fallback() is True
    assert manager.docker_available is True
    assert manager.docker_client is None


def test_try_wsl_socket_fallback_skips_non_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.docker_available = False
    manager.docker_client = None

    monkeypatch.setattr(code_manager.os, "stat", lambda *_args, **_kwargs: SimpleNamespace(st_mode=0))

    class _DockerModule:
        class DockerClient:
            def __init__(self, base_url: str) -> None:
                self.base_url = base_url

            def ping(self) -> None:
                return None

    assert manager._try_wsl_socket_fallback(_DockerModule) is False
    assert manager.docker_available is False


def test_init_docker_importerror_uses_cli_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = code_manager.CodeManager.__new__(code_manager.CodeManager)
    manager.base_dir = Path.cwd()
    manager.docker_available = False
    manager.docker_client = None

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("docker missing")
        return real_import(name, *args, **kwargs)

    calls = {"cli": 0}

    def _fake_cli(_self) -> bool:
        calls["cli"] += 1
        return True

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(code_manager.CodeManager, "_try_docker_cli_fallback", _fake_cli)
    monkeypatch.setattr(code_manager.CodeManager, "_try_wsl_socket_fallback", lambda _self, _module: False)

    manager._init_docker()

    assert calls["cli"] == 1
