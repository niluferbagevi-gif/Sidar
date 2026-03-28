"""
managers/code_manager.py için birim testleri.
_path_to_file_uri, _file_uri_to_path, _encode_lsp_message, _decode_lsp_stream,
CodeManager._resolve_sandbox_limits.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path


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
