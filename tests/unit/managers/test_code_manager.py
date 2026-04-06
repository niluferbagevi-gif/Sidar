from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import managers.code_manager as cm
from managers.security import FULL, SANDBOX


class DummySecurity:
    def __init__(self):
        self.level = FULL
        self.read_ok = True
        self.write_ok = True
        self.exec_ok = True
        self.shell_ok = True

    def can_read(self, _path):
        return self.read_ok

    def can_write(self, _path):
        return self.write_ok

    def can_execute(self):
        return self.exec_ok

    def can_run_shell(self):
        return self.shell_ok

    def is_path_under(self, path_str, base):
        return Path(path_str).resolve().is_relative_to(Path(base).resolve())

    def get_safe_write_path(self, filename):
        return Path("/safe") / filename


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(cm.CodeManager, "_init_docker", lambda self: None)
    sec = DummySecurity()
    cfg = SimpleNamespace(
        DOCKER_RUNTIME="",
        DOCKER_ALLOWED_RUNTIMES=["", "runc", "runsc", "kata-runtime"],
        DOCKER_MICROVM_MODE="off",
        DOCKER_MEM_LIMIT="256m",
        DOCKER_NETWORK_DISABLED=True,
        DOCKER_NANO_CPUS=1_000_000_000,
        ENABLE_LSP=True,
        LSP_TIMEOUT_SECONDS=1,
        LSP_MAX_REFERENCES=3,
        PYTHON_LSP_SERVER="pyright-langserver",
        TYPESCRIPT_LSP_SERVER="typescript-language-server",
        SANDBOX_LIMITS={"memory": "128m", "cpus": "0.25", "pids_limit": 32, "network": "none", "timeout": 2},
    )
    m = cm.CodeManager(sec, tmp_path, docker_image="python:3.11-alpine", docker_exec_timeout=1, cfg=cfg)
    m.docker_available = False
    m.docker_client = None
    return m


def test_lsp_message_codec_roundtrip_and_protocol_error():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    encoded = cm._encode_lsp_message(payload)
    decoded = cm._decode_lsp_stream(encoded)
    assert decoded == [payload]

    truncated = encoded[:-2]
    with pytest.raises(cm._LSPProtocolError):
        cm._decode_lsp_stream(truncated)


def test_file_uri_helpers_and_invalid_scheme(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print(1)", encoding="utf-8")
    uri = cm._path_to_file_uri(f)
    assert uri.startswith("file://")
    restored = cm._file_uri_to_path(uri)
    assert str(restored).endswith("a.py")

    with pytest.raises(ValueError):
        cm._file_uri_to_path("http://x")


def test_runtime_and_limits_resolution(manager):
    manager.docker_runtime = "unknown"
    assert manager._resolve_runtime() == ""

    manager.docker_runtime = ""
    manager.docker_microvm_mode = "runsc"
    assert manager._resolve_runtime() == "runsc"

    manager.cfg.SANDBOX_LIMITS = {"cpus": "bad", "pids_limit": 0, "timeout": 0}
    limits = manager._resolve_sandbox_limits()
    assert limits["memory"] == "256m"
    assert limits["pids_limit"] == 64
    assert limits["timeout"] == 10


def test_build_and_execute_docker_cli_command(manager, monkeypatch):
    limits = {"memory": "128m", "cpus": "0.5", "pids_limit": 10, "network_mode": "none", "timeout": 1}
    cmd = manager._build_docker_cli_command("print(1)", limits)
    assert cmd[:3] == ["docker", "run", "--rm"]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    ok, out = manager._execute_code_with_docker_cli("print(1)", limits)
    assert ok and "REPL Çıktısı" in out


def test_try_docker_cli_fallback(manager, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert manager._try_docker_cli_fallback() is True
    assert manager.docker_available is True


def test_read_and_write_and_generated_test(manager, tmp_path, monkeypatch):
    p = tmp_path / "x.py"
    p.write_text("a\n", encoding="utf-8")
    ok, txt = manager.read_file(str(p), line_numbers=True)
    assert ok and "1\ta" in txt

    manager.security.read_ok = False
    ok, msg = manager.read_file(str(p))
    assert not ok and "Okuma yetkisi yok" in msg
    manager.security.read_ok = True

    ok, msg = manager.write_file(str(p), "def x(:\n", validate=True)
    assert not ok and "Sözdizimi hatası" in msg

    monkeypatch.setattr(cm.shutil, "which", lambda _n: None)
    ok, _ = manager.write_file(str(p), "def x():\n    return 1\n", validate=True)
    assert ok

    test_file = tmp_path / "test_sample.py"
    ok, _ = manager.write_generated_test(str(test_file), "```python\n\ndef test_a():\n    assert 1\n```", append=False)
    assert ok and "def test_a" in test_file.read_text(encoding="utf-8")
    ok, msg = manager.write_generated_test(str(test_file), "def test_a():\n    assert 1", append=True)
    assert ok and "zaten mevcut" in msg


def test_patch_file_paths(manager, tmp_path):
    p = tmp_path / "p.txt"
    p.write_text("hello world", encoding="utf-8")
    ok, _ = manager.patch_file(str(p), "hello", "bye")
    assert ok
    ok, msg = manager.patch_file(str(p), "not-found", "x")
    assert not ok and "bulunamadı" in msg


def test_execute_code_without_docker_branches(manager, monkeypatch):
    manager.security.exec_ok = False
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "yetkisi yok" in msg

    manager.security.exec_ok = True
    manager.security.level = SANDBOX
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "güvenlik politikası" in msg

    manager.security.level = FULL
    monkeypatch.setattr(cm.Config, "DOCKER_REQUIRED", True, raising=False)
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "DOCKER_REQUIRED=true" in msg

    monkeypatch.setattr(cm.Config, "DOCKER_REQUIRED", False, raising=False)
    monkeypatch.setattr(manager, "execute_code_local", lambda _c: (True, "local"))
    ok, msg = manager.execute_code("print(1)")
    assert ok and msg == "local"


def test_execute_code_with_mocked_docker_success(manager, monkeypatch):
    manager.docker_available = True

    class FakeContainer:
        def __init__(self):
            self.status = "exited"

        def reload(self):
            return None

        def logs(self, **_kwargs):
            return b"hello"

        def wait(self, timeout=1):
            return {"StatusCode": 0}

        def remove(self, force=False):
            return None

    fake_client = SimpleNamespace(containers=SimpleNamespace(run=lambda **_kwargs: FakeContainer()))
    manager.docker_client = fake_client

    fake_docker = ModuleType("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=RuntimeError)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)

    ok, msg = manager.execute_code("print(1)")
    assert ok and "Docker Sandbox" in msg


def test_execute_code_local_timeout_and_success(manager, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    ok, msg = manager.execute_code_local("print('x')")
    assert ok and "Subprocess" in msg

    def _raise_timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    ok, msg = manager.execute_code_local("while True: pass")
    assert not ok and "Zaman aşımı" in msg


def test_run_shell_in_sandbox(manager, tmp_path, monkeypatch):
    manager.security.exec_ok = False
    ok, _ = manager.run_shell_in_sandbox("echo 1")
    assert not ok
    manager.security.exec_ok = True

    ok, _ = manager.run_shell_in_sandbox("   ")
    assert not ok

    monkeypatch.setattr(cm.shutil, "which", lambda _n: None)
    ok, msg = manager.run_shell_in_sandbox("echo 1")
    assert not ok and "Docker CLI bulunamadı" in msg

    monkeypatch.setattr(cm.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    ok, out = manager.run_shell_in_sandbox("echo 1", cwd=str(tmp_path))
    assert ok and out == "ok"


def test_analyze_pytest_output_and_run_pytest_collect(manager, monkeypatch):
    sample = """managers/code_manager.py  100 10 90% 1-2, 5->7
___ test_fail ___
E AssertionError
foo.py:10: in test_fail
= 1 failed, 2 passed in 0.10s =
"""
    parsed = manager.analyze_pytest_output(sample)
    assert parsed["has_failures"] is True
    assert parsed["has_coverage_gaps"] is True

    result = manager.run_pytest_and_collect("python -m pip")
    assert result["success"] is False

    monkeypatch.setattr(manager, "run_shell_in_sandbox", lambda *_a, **_k: (True, sample))
    ok_result = manager.run_pytest_and_collect("pytest -q")
    assert ok_result["success"] is True


def test_run_shell_paths(manager, monkeypatch, tmp_path):
    manager.security.shell_ok = False
    ok, _ = manager.run_shell("echo 1")
    assert not ok
    manager.security.shell_ok = True

    ok, _ = manager.run_shell("echo 1 | cat")
    assert not ok

    ok, msg = manager.run_shell("rm -rf /tmp/x", allow_shell_features=True)
    assert not ok and "Engellendi" in msg

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="hello", stderr=""),
    )
    ok, out = manager.run_shell("echo hello", cwd=str(tmp_path))
    assert ok and out == "hello"


def test_glob_grep_list_validate_and_metrics(manager, tmp_path):
    (tmp_path / "a.py").write_text("print('x')\nneedle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")

    ok, msg = manager.glob_search("*.py", base_path=str(tmp_path))
    assert ok and "a.py" in msg

    ok, msg = manager.grep_files("needle", path=str(tmp_path), file_glob="*.py", context_lines=1)
    assert ok and "eşleşme" in msg

    ok, msg = manager.list_directory(str(tmp_path))
    assert ok and "📁" in msg

    assert manager.validate_python_syntax("x=1")[0] is True
    assert manager.validate_json(json.dumps({"a": 1}))[0] is True

    report = manager.audit_project(root=str(tmp_path), max_files=10)
    assert "Sidar Denetim Raporu" in report
    metrics = manager.get_metrics()
    assert "syntax_checks" in metrics
    assert "CodeManager" in manager.status()
    assert "<CodeManager" in repr(manager)


def test_lsp_core_helpers_and_extracts(manager, tmp_path, monkeypatch):
    py = tmp_path / "x.py"
    py.write_text("value = 1\n", encoding="utf-8")

    assert manager._detect_language_id(py) == "python"
    assert manager._resolve_lsp_command("python")[-1] == "--stdio"
    resolved = manager._normalize_lsp_path(str(py))
    assert resolved == py.resolve()

    payload = manager._build_lsp_initialize_payload(tmp_path)
    assert payload["method"] == "initialize"

    msgs = [{"id": 2, "result": [{"uri": cm._path_to_file_uri(py), "range": {"start": {"line": 0, "character": 1}}}]}, {"method": "x"}]
    result, notes = manager._extract_lsp_result(msgs)
    assert isinstance(result, list) and len(notes) == 1

    formatted = manager._format_lsp_locations(result, limit=1)
    assert "satır" in formatted

    pos = manager._position_params(py, 1, 2)
    assert pos["position"]["line"] == 1

    summary = manager._summarize_lsp_diagnostic_entries([
        {"severity": 1},
        {"severity": 2},
        {"severity": 3},
    ])
    assert summary["decision"] == "REJECT"

    monkeypatch.setattr(manager, "lsp_semantic_audit", lambda _paths=None: (True, {"issues": [], "summary": "clean"}))
    ok, text = manager.lsp_workspace_diagnostics()
    assert ok and "clean" in text


def test_lsp_workspace_edit_and_rename(manager, tmp_path, monkeypatch):
    fp = tmp_path / "ren.py"
    fp.write_text("name = 1\nprint(name)\n", encoding="utf-8")
    edit = {
        "changes": {
            cm._path_to_file_uri(fp): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 4},
                    },
                    "newText": "item",
                }
            ]
        }
    }
    ok, msg = manager._apply_workspace_edit(edit)
    assert ok and "Değişen dosya" in msg
    assert fp.read_text(encoding="utf-8").startswith("item")

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_k: [{"id": 2, "result": {"changes": {cm._path_to_file_uri(fp): []}}}],
    )
    ok, dry = manager.lsp_rename_symbol(str(fp), 0, 0, "new_name", apply=False)
    assert ok and "dry-run" in dry


def test_lsp_semantic_audit_paths(manager, tmp_path, monkeypatch):
    p = tmp_path / "x.py"
    p.write_text("x=1\n", encoding="utf-8")
    manager.base_dir = tmp_path

    notifications = [
        {
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": cm._path_to_file_uri(p),
                "diagnostics": [
                    {
                        "range": {"start": {"line": 0, "character": 0}},
                        "severity": 2,
                        "message": "warn",
                    }
                ],
            },
        }
    ]
    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_k: notifications)
    ok, report = manager.lsp_semantic_audit([str(p)])
    assert ok and report["issues"][0]["message"] == "warn"
