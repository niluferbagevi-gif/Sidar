"""managers/code_manager.py için birim testleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from managers.code_manager import (
    CodeManager,
    _LSPProtocolError,
    _decode_lsp_stream,
    _encode_lsp_message,
    _file_uri_to_path,
    _path_to_file_uri,
)


class TestLspHelpers:
    def test_encode_decode_lsp_message_roundtrip(self):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        encoded = _encode_lsp_message(payload)

        decoded = _decode_lsp_stream(encoded)

        assert decoded == [payload]

    def test_decode_lsp_stream_raises_on_truncated_body(self):
        payload = b'{"jsonrpc":"2.0"}'
        raw = b"Content-Length: 999\r\n\r\n" + payload

        with pytest.raises(_LSPProtocolError) as exc_info:
            _decode_lsp_stream(raw)
        assert "Eksik LSP mesaj gövdesi" in str(exc_info.value)

    def test_file_uri_to_path_rejects_non_file_scheme(self):
        with pytest.raises(ValueError) as exc_info:
            _file_uri_to_path("https://example.com/file.py")
        assert "Desteklenmeyen URI şeması" in str(exc_info.value)

    def test_path_to_file_uri_starts_with_file_scheme(self, tmp_path):
        sample = tmp_path / "sample.py"
        sample.write_text("print('ok')", encoding="utf-8")

        uri = _path_to_file_uri(sample)

        assert uri.startswith("file://")
        assert "sample.py" in uri


class TestCodeManagerInternalConfig:
    def test_resolve_runtime_returns_empty_when_runtime_not_allowed(self):
        cm = CodeManager.__new__(CodeManager)
        cm.docker_runtime = "nvidia"
        cm.docker_microvm_mode = "off"
        cm.docker_allowed_runtimes = ["", "runc"]

        assert cm._resolve_runtime() == ""

    def test_resolve_sandbox_limits_normalizes_invalid_values(self):
        cm = CodeManager.__new__(CodeManager)
        cm.cfg = type("Cfg", (), {"SANDBOX_LIMITS": {"cpus": "invalid", "pids_limit": 0, "timeout": 0}})()
        cm.docker_mem_limit = "128m"
        cm.docker_exec_timeout = 7
        cm.docker_nano_cpus = 123

        limits = cm._resolve_sandbox_limits()

        assert limits["memory"] in ("128m", "256m")
        assert limits["nano_cpus"] == 123
        assert limits["pids_limit"] == 64
        assert limits["timeout"] == 10


class TestWriteGeneratedTest:
    def test_write_generated_test_rejects_empty_content(self):
        cm = CodeManager.__new__(CodeManager)

        ok, message = cm.write_generated_test("tests/test_new.py", "```python\n\n```")

        assert ok is False
        assert "boş" in message.lower()

    def test_write_generated_test_returns_idempotent_when_content_exists(self, tmp_path):
        cm = CodeManager.__new__(CodeManager)
        target = tmp_path / "test_existing.py"
        current = "def test_a():\n    assert True\n"
        target.write_text(current, encoding="utf-8")
        cm.read_file = lambda _path, line_numbers=False: (True, current)
        cm.write_file = lambda *_args, **_kwargs: (False, "write should not be called")

        ok, message = cm.write_generated_test(str(target), current, append=True)

        assert ok is True
        assert "zaten mevcut" in message

    def test_write_generated_test_appends_when_new_content(self, tmp_path):
        cm = CodeManager.__new__(CodeManager)
        target = tmp_path / "test_append.py"
        current = "def test_a():\n    assert True\n"
        new_test = "def test_b():\n    assert 1 == 1"
        target.write_text(current, encoding="utf-8")
        cm.read_file = lambda _path, line_numbers=False: (True, current)

        captured = {}

        def _write_file(path: str, content: str, validate: bool = True):
            captured["path"] = path
            captured["content"] = content
            captured["validate"] = validate
            return True, "ok"

        cm.write_file = _write_file

        ok, message = cm.write_generated_test(str(target), new_test, append=True)

        assert ok is True
        assert message == "ok"
        assert captured["path"] == str(target)
        assert "def test_a()" in captured["content"]
        assert "def test_b()" in captured["content"]
        assert captured["validate"] is True
