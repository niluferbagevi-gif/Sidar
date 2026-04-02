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
