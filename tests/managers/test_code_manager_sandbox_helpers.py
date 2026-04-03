from __future__ import annotations

import subprocess
from pathlib import Path, PosixPath
from types import SimpleNamespace

import pytest

import managers.code_manager as code_manager
from managers.code_manager import CodeManager, _LSPProtocolError


def _build_manager(tmp_path: Path) -> CodeManager:
    manager = CodeManager.__new__(CodeManager)
    manager.base_dir = tmp_path
    manager.cfg = SimpleNamespace(SANDBOX_LIMITS={})
    manager.docker_mem_limit = "256m"
    manager.docker_exec_timeout = 10
    manager.docker_nano_cpus = 1_000_000_000
    manager.max_output_chars = 40
    manager.docker_image = "python:3.11-alpine"
    manager.docker_client = None
    manager.docker_available = False
    return manager


def test_file_uri_roundtrip_and_invalid_scheme(tmp_path: Path) -> None:
    source = tmp_path / "a" / "b.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('ok')", encoding="utf-8")

    uri = code_manager._path_to_file_uri(source)
    restored = code_manager._file_uri_to_path(uri)

    assert uri.startswith("file://")
    assert isinstance(restored, PosixPath)
    assert Path(restored) == source.resolve()

    with pytest.raises(ValueError, match="Desteklenmeyen URI şeması"):
        code_manager._file_uri_to_path("https://example.com/file.py")


def test_decode_lsp_stream_parses_messages_and_detects_truncated_body() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialized"}
    encoded = code_manager._encode_lsp_message(payload)

    decoded = code_manager._decode_lsp_stream(encoded)
    assert decoded == [payload]

    with pytest.raises(_LSPProtocolError, match="Eksik LSP mesaj gövdesi"):
        code_manager._decode_lsp_stream(b"Content-Length: 5\r\n\r\n{}")


def test_resolve_sandbox_limits_normalizes_invalid_values(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    manager.cfg = SimpleNamespace(
        SANDBOX_LIMITS={
            "memory": "512m",
            "cpus": "invalid-cpu",
            "pids_limit": 0,
            "timeout": 0,
            "network": "HOST",
        }
    )

    limits = manager._resolve_sandbox_limits()

    assert limits["memory"] == "512m"
    assert limits["nano_cpus"] == 1_000_000_000
    assert limits["pids_limit"] == 64
    assert limits["timeout"] == 10
    assert limits["network_mode"] == "host"


def test_execute_code_with_docker_cli_handles_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)
    limits = {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 5}

    def _fake_run_success(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="x" * 100, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run_success)
    ok_success, out_success = manager._execute_code_with_docker_cli("print('ok')", limits)

    assert ok_success is True
    assert "REPL Çıktısı" in out_success
    assert "ÇIKTI KIRPILDI" in out_success

    def _fake_run_fail(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="fatal error")

    monkeypatch.setattr(subprocess, "run", _fake_run_fail)
    ok_fail, out_fail = manager._execute_code_with_docker_cli("raise Exception()", limits)

    assert ok_fail is False
    assert "REPL Hatası" in out_fail
    assert "fatal error" in out_fail


def test_try_docker_cli_fallback_enables_cli_mode_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )

    assert manager._try_docker_cli_fallback() is True
    assert manager.docker_available is True
    assert manager.docker_client is None


def test_try_docker_cli_fallback_returns_false_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker info", timeout=5)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    assert manager._try_docker_cli_fallback() is False
