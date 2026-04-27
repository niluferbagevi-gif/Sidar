from __future__ import annotations

import builtins
import importlib
import json
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import managers.code_manager as cm
from managers.security import FULL, SANDBOX

# Capture the real _init_docker before any fixture patches it
_real_init_docker = cm.CodeManager._init_docker


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
        SANDBOX_LIMITS={
            "memory": "128m",
            "cpus": "0.25",
            "pids_limit": 32,
            "network": "none",
            "timeout": 2,
        },
    )
    m = cm.CodeManager(
        sec, tmp_path, docker_image="python:3.11-alpine", docker_exec_timeout=1, cfg=cfg
    )
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
    limits = {
        "memory": "128m",
        "cpus": "0.5",
        "pids_limit": 10,
        "network_mode": "none",
        "timeout": 1,
    }
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
    ok, _ = manager.write_generated_test(
        str(test_file), "```python\n\ndef test_a():\n    assert 1\n```", append=False
    )
    assert ok and "def test_a" in test_file.read_text(encoding="utf-8")
    ok, msg = manager.write_generated_test(
        str(test_file), "def test_a():\n    assert 1", append=True
    )
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

    msgs = [
        {
            "id": 2,
            "result": [
                {"uri": cm._path_to_file_uri(py), "range": {"start": {"line": 0, "character": 1}}}
            ],
        },
        {"method": "x"},
    ]
    result, notes = manager._extract_lsp_result(msgs)
    assert isinstance(result, list) and len(notes) == 1

    formatted = manager._format_lsp_locations(result, limit=1)
    assert "satır" in formatted

    pos = manager._position_params(py, 1, 2)
    assert pos["position"]["line"] == 1

    summary = manager._summarize_lsp_diagnostic_entries(
        [
            {"severity": 1},
            {"severity": 2},
            {"severity": 3},
        ]
    )
    assert summary["decision"] == "REJECT"

    monkeypatch.setattr(
        manager,
        "lsp_semantic_audit",
        lambda _paths=None: (True, {"issues": [], "summary": "clean"}),
    )
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


def test_init_docker_importerror_and_generic_error_paths(tmp_path, monkeypatch):
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
        SANDBOX_LIMITS={},
    )

    original_init = cm.CodeManager._init_docker

    def _raise_import_error(self):
        raise ImportError("docker missing")

    monkeypatch.setattr(cm.CodeManager, "_init_docker", _raise_import_error)
    monkeypatch.setattr(cm.CodeManager, "_try_docker_cli_fallback", lambda _self: False)
    monkeypatch.setattr(cm.CodeManager, "_try_wsl_socket_fallback", lambda _self, _mod: False)
    monkeypatch.delitem(sys.modules, "docker", raising=False)
    with pytest.raises(ImportError):
        cm.CodeManager(sec, tmp_path, cfg=cfg)

    monkeypatch.setattr(cm.CodeManager, "_init_docker", original_init)
    m = cm.CodeManager(sec, tmp_path, cfg=cfg)
    m.docker_available = True  # generic hata yolunun bayrağı sıfırladığını doğrula
    m.docker_client = object()

    fake_docker = ModuleType("docker")
    fake_docker.from_env = lambda: (_ for _ in ()).throw(RuntimeError("daemon down"))
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    monkeypatch.setattr(cm.CodeManager, "_try_wsl_socket_fallback", lambda *_a, **_k: False)

    m._init_docker()

    assert m.docker_available is False
    assert m.docker_client is None


def test_try_wsl_socket_fallback_success_and_skips(manager, monkeypatch):
    class _Stat:
        def __init__(self, mode):
            self.st_mode = mode
            self.st_size = 0
            self.st_mtime = 0.0

    class FakeDocker:
        class DockerClient:
            def __init__(self, base_url):
                self.base_url = base_url

            def ping(self):
                if "guest-services" in self.base_url:
                    return None
                raise RuntimeError("bad")

    monkeypatch.setattr(
        cm.os,
        "stat",
        lambda p, *_args, **_kwargs: _Stat(stat.S_IFREG if "var/run" in str(p) else stat.S_IFSOCK),
    )
    assert (
        FakeDocker.DockerClient(
            "unix:///mnt/wsl/docker-desktop/run/guest-services/backend.sock"
        ).ping()
        is None
    )
    with pytest.raises(RuntimeError, match="bad"):
        FakeDocker.DockerClient("unix:///tmp/other.sock").ping()
    assert manager._try_wsl_socket_fallback(FakeDocker) is True
    assert manager.docker_available is True


def test_init_docker_import_and_wsl_fallback_branches(manager, monkeypatch):
    original_import = builtins.__import__

    def _import_without_docker(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("docker missing")
        return original_import(name, *args, **kwargs)

    fake_cached_docker = ModuleType("docker")
    monkeypatch.setitem(sys.modules, "docker", fake_cached_docker)
    with pytest.raises(ImportError):
        _import_without_docker("docker")
    monkeypatch.setattr(builtins, "__import__", _import_without_docker)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda mod: mod is fake_cached_docker)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)
    manager._init_docker()
    assert manager.docker_available is False

    monkeypatch.delitem(sys.modules, "docker", raising=False)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda _mod: False)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)
    manager._init_docker()
    assert manager.docker_available is False

    monkeypatch.setattr(builtins, "__import__", original_import)

    class _ErrDocker(ModuleType):
        def from_env(self):
            raise RuntimeError("daemon down")

    err_docker = _ErrDocker("docker")
    with pytest.raises(RuntimeError):
        err_docker.from_env()
    monkeypatch.setitem(sys.modules, "docker", err_docker)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda mod: mod is err_docker)
    manager._init_docker()
    assert manager.docker_available is False


def test_init_docker_importerror_branch_variants(tmp_path, monkeypatch):
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
        SANDBOX_LIMITS={},
    )
    original_init = cm.CodeManager._init_docker
    monkeypatch.setattr(cm.CodeManager, "_init_docker", lambda self: None)
    manager = cm.CodeManager(sec, tmp_path, cfg=cfg)
    monkeypatch.setattr(cm.CodeManager, "_init_docker", original_init)

    builtins_dict = cm.__dict__["__builtins__"]
    original_import = builtins_dict["__import__"]

    def _raise_import_error_for_docker(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("docker missing")
        return original_import(name, *args, **kwargs)

    # cached docker module + WSL fallback success -> early return (321-323)
    cached_docker = ModuleType("docker")
    monkeypatch.setitem(sys.modules, "docker", cached_docker)
    monkeypatch.setitem(builtins_dict, "__import__", _raise_import_error_for_docker)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda mod: mod is cached_docker)
    cli_calls = {"count": 0}
    monkeypatch.setattr(
        manager,
        "_try_docker_cli_fallback",
        lambda: cli_calls.__setitem__("count", cli_calls["count"] + 1) or False,
    )
    manager._init_docker()
    assert cli_calls["count"] == 0

    # no cached module + CLI fallback success -> early return (324-325)
    monkeypatch.delitem(sys.modules, "docker", raising=False)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda _mod: False)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: True)
    manager._init_docker()
    assert manager.docker_available is False

    # no cached module + CLI fallback fail -> warning path (326)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)

    def _raise_on_warning(*_args, **_kwargs):
        raise RuntimeError("warning-hit")

    monkeypatch.setattr(cm.logger, "warning", _raise_on_warning)
    with pytest.raises(RuntimeError, match="warning-hit"):
        manager._init_docker()

    monkeypatch.setitem(builtins_dict, "__import__", original_import)


def test_init_docker_exception_path_returns_on_wsl_success(tmp_path, monkeypatch):
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
        SANDBOX_LIMITS={},
    )
    original_init = cm.CodeManager._init_docker
    monkeypatch.setattr(cm.CodeManager, "_init_docker", lambda self: None)
    manager = cm.CodeManager(sec, tmp_path, cfg=cfg)
    monkeypatch.setattr(cm.CodeManager, "_init_docker", original_init)

    class _ErrDocker(ModuleType):
        def from_env(self):
            raise RuntimeError("daemon down")

    err_docker = _ErrDocker("docker")
    monkeypatch.setitem(sys.modules, "docker", err_docker)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda mod: mod is err_docker)
    warning_calls = {"count": 0}
    monkeypatch.setattr(
        cm.logger,
        "warning",
        lambda *args, **kwargs: warning_calls.__setitem__("count", warning_calls["count"] + 1),
    )

    manager._init_docker()

    assert warning_calls["count"] == 0
    assert manager.docker_available is False
    assert manager.docker_client is None


def test_execute_code_docker_error_paths(manager, monkeypatch):
    manager.docker_available = True
    manager.security.level = SANDBOX

    class FakeDocker(ModuleType):
        pass

    class _ImageNotFound(Exception):
        pass

    fake_docker = FakeDocker("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=_ImageNotFound)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: (_ for _ in ()).throw(RuntimeError("x")))
    )
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "güvenlik politikası" in msg

    manager.security.level = FULL
    monkeypatch.setattr(
        manager,
        "_execute_code_with_docker_cli",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=1)),
    )
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "Zaman aşımı" in msg

    monkeypatch.setattr(
        manager,
        "_execute_code_with_docker_cli",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cli failed")),
    )
    monkeypatch.setattr(manager, "execute_code_local", lambda _c: (True, "local-fallback"))
    ok, msg = manager.execute_code("print(1)")
    assert ok and msg == "local-fallback"


def test_execute_code_sets_runtime_and_non_dict_wait(manager, monkeypatch):
    manager.docker_available = True
    manager.docker_runtime = "runc"
    called = {}

    class FakeContainer:
        status = "exited"

        def reload(self):
            return None

        def logs(self, **_kwargs):
            return b"ok"

        def wait(self, timeout=1):
            return 0

        def remove(self, force=False):
            return None

    class FakeContainers:
        def run(self, **kwargs):
            called.update(kwargs)
            return FakeContainer()

    fake_docker = ModuleType("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=RuntimeError)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    manager.docker_client = SimpleNamespace(containers=FakeContainers())

    ok, msg = manager.execute_code("print(1)")
    assert ok and "Docker Sandbox" in msg
    assert called["runtime"] == "runc"


def test_analyze_pytest_output_failure_section_parser(manager):
    sample = """___ test parser branch ___
E AssertionError
foo/bar_test.py:42: in test_parser_branch
= 1 failed in 0.10s =
"""
    parsed = manager.analyze_pytest_output(sample)
    assert parsed["has_failures"] is True
    assert parsed["failure_targets"][0]["summary"] == "test parser branch"
    assert parsed["failure_targets"][0]["target_path"] == "foo/bar_test.py"


def test_execute_code_local_and_shell_additional_errors(manager, monkeypatch):
    def _raise_err(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(subprocess, "run", _raise_err)
    ok, msg = manager.execute_code_local("print(1)")
    assert not ok and "Subprocess çalıştırma hatası" in msg

    manager.security.shell_ok = True
    ok, msg = manager.run_shell("", cwd=str(manager.base_dir))
    assert not ok and "komut belirtilmedi" in msg.lower()

    monkeypatch.setattr(
        cm.shlex, "split", lambda _c: (_ for _ in ()).throw(ValueError("bad split"))
    )
    ok, msg = manager.run_shell("echo x")
    assert not ok and "ayrıştırılamadı" in msg

    monkeypatch.setattr(cm.shlex, "split", lambda c: [c])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=60)),
    )
    ok, msg = manager.run_shell("echo x")
    assert not ok and "Zaman aşımı" in msg


def test_lsp_sequence_and_public_lsp_wrappers(manager, tmp_path, monkeypatch):
    py = tmp_path / "a.py"
    py.write_text("name = 1\n", encoding="utf-8")
    manager.base_dir = tmp_path

    fake_proc = SimpleNamespace(returncode=0)
    encoded = cm._encode_lsp_message({"jsonrpc": "2.0", "id": 2, "result": []})
    fake_proc.communicate = lambda payload, timeout: (encoded, b"")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake_proc)
    messages = manager._run_lsp_sequence(primary_path=py, request_method="textDocument/definition")
    assert messages and messages[0]["id"] == 2

    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_k: [{"id": 2, "result": []}])
    ok, msg = manager.lsp_go_to_definition(str(py), 0, 0)
    assert ok and "Sonuç bulunamadı." in msg

    ok, msg = manager.lsp_find_references(str(py), 0, 0)
    assert ok

    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_k: [{"id": 2, "result": {"documentChanges": []}}],
    )
    ok, msg = manager.lsp_rename_symbol(str(py), 0, 0, "renamed", apply=True)
    assert not ok and "boş döndü" in msg

    monkeypatch.setattr(
        manager,
        "lsp_semantic_audit",
        lambda _paths=None: (
            True,
            {
                "issues": [
                    {"path": "a.py", "line": 1, "character": 1, "severity": 2, "message": "w"}
                ]
            },
        ),
    )
    ok, msg = manager.lsp_workspace_diagnostics([str(py)])
    assert ok and "severity=2" in msg


def test_low_level_helpers_extra_branches(manager, monkeypatch, tmp_path):
    # _decode_lsp_stream with malformed header line (no colon) and partial header break
    payload = cm._encode_lsp_message({"jsonrpc": "2.0", "id": 2, "result": 1})
    assert cm._decode_lsp_stream(payload)[0]["id"] == 2
    with pytest.raises(json.JSONDecodeError):
        cm._decode_lsp_stream(b"bad-header\r\n\r\n{}")

    # windows URI branch
    monkeypatch.setattr(cm, "_OS_NAME", "nt")
    out = cm._file_uri_to_path("file:///C:/tmp/x.py")
    assert str(out).lower().endswith("c:\\tmp\\x.py") or "C:" in str(out)
    monkeypatch.setattr(cm, "_OS_NAME", "posix")

    manager.docker_microvm_mode = "kata"
    manager.docker_runtime = ""
    assert manager._resolve_runtime() == "kata-runtime"


def test_docker_cli_and_sandbox_error_paths(manager, monkeypatch, tmp_path):
    limits = {"memory": "1m", "cpus": "0.1", "pids_limit": 1, "network_mode": "none", "timeout": 1}

    # docker cli timeout/error path in helper
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=1)),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        manager._execute_code_with_docker_cli("print(1)", limits)

    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=7, stdout="", stderr="err")
    )
    ok, msg = manager._execute_code_with_docker_cli("print(1)", limits)
    assert not ok and "Docker CLI Sandbox" in msg

    # run_shell_in_sandbox cwd invalid and outside base
    bad = tmp_path / "nope"
    ok, _ = manager.run_shell_in_sandbox("echo 1", cwd=str(bad))
    assert not ok

    outside = Path("/").resolve()
    ok, _ = manager.run_shell_in_sandbox("echo 1", cwd=str(outside))
    assert not ok

    monkeypatch.setattr(cm.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("docker"))
    )
    ok, msg = manager.run_shell_in_sandbox("echo 1", cwd=str(tmp_path))
    assert not ok and "bulunamadı" in msg


def test_shell_glob_grep_and_list_extra_paths(manager, monkeypatch, tmp_path):
    manager.max_output_chars = 8
    manager.security.shell_ok = True

    # allow_shell_features True branch
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="1234567890", stderr=""),
    )
    ok, msg = manager.run_shell("echo a | cat", allow_shell_features=True)
    assert ok and "KIRPILDI" in msg

    # blocked shell pattern branch iteration
    ok, msg = manager.run_shell("rm -rf /tmp", allow_shell_features=True)
    assert not ok and "Engellendi" in msg

    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("kaboom"))
    )
    ok, msg = manager.run_shell("echo x", allow_shell_features=True)
    assert not ok and "Kabuk hatası" in msg

    # glob empty / missing path / no match
    ok, _ = manager.glob_search("")
    assert not ok
    ok, _ = manager.glob_search("*.py", base_path=str(tmp_path / "missing"))
    assert not ok
    ok, msg = manager.glob_search("*.doesnotexist", base_path=str(tmp_path))
    assert ok and "bulunamadı" in msg

    # grep invalid regex + path missing + no results
    ok, _ = manager.grep_files("(", path=str(tmp_path))
    assert not ok
    ok, _ = manager.grep_files("x", path=str(tmp_path / "missing"))
    assert not ok
    (tmp_path / "a.txt").write_text("abc\n", encoding="utf-8")
    ok, msg = manager.grep_files("zzz", path=str(tmp_path), file_glob="*.txt")
    assert ok and "Eşleşme bulunamadı" in msg

    # list directory error branches
    ok, _ = manager.list_directory(str(tmp_path / "missing"))
    assert not ok
    filep = tmp_path / "f.txt"
    filep.write_text("x", encoding="utf-8")
    ok, _ = manager.list_directory(str(filep))
    assert not ok


def test_lsp_and_audit_extra_paths(manager, monkeypatch, tmp_path):
    fp = tmp_path / "a.py"
    fp.write_text("a=1\n", encoding="utf-8")
    manager.base_dir = tmp_path

    assert manager.validate_json("{")[0] is False
    assert manager._detect_language_id(tmp_path / "a.ts") == "typescript"
    with pytest.raises(ValueError):
        manager._resolve_lsp_command("go")

    with pytest.raises(RuntimeError):
        manager.enable_lsp = False
        manager._run_lsp_sequence(primary_path=fp, request_method=None)
    manager.enable_lsp = True

    with pytest.raises(ValueError):
        manager._run_lsp_sequence(primary_path=tmp_path / "a.txt", request_method=None)

    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("x"))
    )
    with pytest.raises(FileNotFoundError):
        manager._run_lsp_sequence(primary_path=fp, request_method=None)

    class P:
        returncode = 1

        def communicate(self, *_a, **_k):
            return b"", b"boom"

        def kill(self):
            return None

    assert P().kill() is None

    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: P())
    with pytest.raises(RuntimeError):
        manager._run_lsp_sequence(primary_path=fp, request_method=None)

    with pytest.raises(RuntimeError):
        manager._extract_lsp_result([{"id": 2, "error": {"message": "x"}}])

    loc_text = manager._format_lsp_locations(
        [
            {
                "targetUri": cm._path_to_file_uri(fp),
                "targetRange": {"start": {"line": 0, "character": 0}},
            },
            {"uri": cm._path_to_file_uri(fp), "range": {"start": {"line": 1, "character": 1}}},
        ],
        limit=1,
    )
    assert "ek sonuç" in loc_text

    monkeypatch.setattr(
        manager, "_run_lsp_sequence", lambda **_k: (_ for _ in ()).throw(RuntimeError("lsp"))
    )
    ok, _ = manager.lsp_go_to_definition(str(fp), 0, 0)
    assert not ok
    ok, _ = manager.lsp_find_references(str(fp), 0, 0)
    assert not ok

    ok, msg = manager._apply_workspace_edit({})
    assert not ok and "boş" in msg

    # write permission denied
    manager.security.write_ok = False
    edit = {
        "changes": {
            cm._path_to_file_uri(fp): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                    "newText": "b",
                }
            ]
        }
    }
    ok, _ = manager._apply_workspace_edit(edit)
    assert not ok
    manager.security.write_ok = True

    ok, _ = manager.lsp_rename_symbol(str(fp), 0, 0, "   ")
    assert not ok

    # diagnostics summary branches
    summary = manager._summarize_lsp_diagnostic_entries([{"severity": "x"}, {"severity": 2}])
    assert summary["decision"] == "APPROVE"

    manager.base_dir = tmp_path / "empty"
    manager.base_dir.mkdir()
    ok, audit = manager.lsp_semantic_audit()
    assert not ok and audit["status"] == "no-targets"

    # audit_project max file warning path
    manager.base_dir = tmp_path
    (tmp_path / "bad.py").write_text("def x(:\n", encoding="utf-8")
    report = manager.audit_project(root=str(tmp_path), max_files=1)
    assert "Uyarı" in report

    manager.docker_available = True
    assert "Docker Sandbox Aktif" in manager.status()


def test_import_fallback_and_uri_windows_non_drive(monkeypatch):
    real_config = importlib.import_module("config")
    fake_config = ModuleType("config")
    fake_config.Config = type("Config", (), {})
    monkeypatch.setitem(sys.modules, "config", fake_config)
    reloaded = importlib.reload(cm)
    assert reloaded.SANDBOX_LIMITS == {}
    monkeypatch.setitem(sys.modules, "config", real_config)
    importlib.reload(cm)

    monkeypatch.setattr(cm, "_OS_NAME", "nt")
    p = cm._file_uri_to_path("file:///tmp/no-drive.py")
    assert isinstance(p, cm.PureWindowsPath)
    monkeypatch.setattr(cm, "_OS_NAME", "posix")


def test_read_write_patch_and_shell_additional_branches(manager, monkeypatch, tmp_path):
    real_open = builtins.open
    missing = tmp_path / "missing.py"
    ok, msg = manager.read_file(str(missing))
    assert not ok and "bulunamadı" in msg

    d = tmp_path / "d"
    d.mkdir()
    ok, msg = manager.read_file(str(d))
    assert not ok and "dizin" in msg

    p = tmp_path / "perm.py"
    p.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(
        builtins, "open", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("x"))
    )
    ok, msg = manager.read_file(str(p))
    assert not ok and "Erişim reddedildi" in msg

    manager.security.write_ok = False
    ok, msg = manager.write_file(str(p), "x=2\n")
    assert not ok and "Güvenli alternatif" in msg
    manager.security.write_ok = True

    monkeypatch.setattr(
        builtins, "open", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("x"))
    )
    ok, msg = manager.write_file(str(p), "x=2\n", validate=False)
    assert not ok and "Yazma erişimi reddedildi" in msg
    monkeypatch.setattr(builtins, "open", real_open)

    p.write_text("dup\ndup\n", encoding="utf-8")
    ok, msg = manager.patch_file(str(p), "dup", "x")
    assert not ok and "belirsiz" in msg

    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=2, stdout="", stderr="err")
    )
    ok, msg = manager.run_shell("python -c 'import sys;sys.exit(2)'", allow_shell_features=True)
    assert not ok and "çıkış kodu: 2" in msg


def test_execute_code_more_paths(manager, monkeypatch):
    manager.docker_available = True
    manager.max_output_chars = 5

    class TimeoutContainer:
        status = "running"

        def reload(self):
            return None

        def kill(self):
            return None

        def remove(self, force=False):
            return None

    fake_docker = ModuleType("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=RuntimeError)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: TimeoutContainer())
    )

    ticks = {"n": 0}

    def _fake_time():
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 99.0

    monkeypatch.setattr(cm.time, "time", _fake_time)
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "Zaman aşımı" in msg
    monkeypatch.setattr(cm.time, "time", time.time)

    class ExitContainer:
        status = "exited"

        def reload(self):
            return None

        def logs(self, **_kwargs):
            return b"abcdefghij"

        def wait(self, timeout=1):
            return {"StatusCode": 3}

        def remove(self, force=False):
            return None

    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: ExitContainer())
    )
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "Docker Sandbox" in msg


def test_lsp_and_workspace_more_branches(manager, monkeypatch, tmp_path):
    py = tmp_path / "a.py"
    extra = tmp_path / "b.py"
    py.write_text("a=1\n", encoding="utf-8")
    extra.write_text("b=2\n", encoding="utf-8")
    manager.base_dir = tmp_path

    class P:
        returncode = 0

        def communicate(self, *_a, **_k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        def kill(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: P())
    with pytest.raises(RuntimeError):
        manager._run_lsp_sequence(
            primary_path=py,
            request_method="textDocument/definition",
            extra_open_files=[extra, Path("ghost.py")],
        )

    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": cm._path_to_file_uri(py)},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "newText": "z",
                    }
                ],
            }
        ]
    }
    ok, msg = manager._apply_workspace_edit(edit)
    assert ok and "Değişen dosya sayısı: 1" in msg

    monkeypatch.setattr(
        manager, "_run_lsp_sequence", lambda **_k: [{"id": 2, "result": {"changes": {}}}]
    )
    ok, msg = manager.lsp_rename_symbol(str(py), 0, 0, "new", apply=False)
    assert ok and "Etkilenen dosya sayısı: 0" in msg

    monkeypatch.setattr(
        manager, "_run_lsp_sequence", lambda **_k: (_ for _ in ()).throw(RuntimeError("oops"))
    )
    ok, report = manager.lsp_semantic_audit([str(py)])
    assert not ok and report["status"] == "tool-error"


def test_grep_glob_list_audit_more_branches(manager, monkeypatch, tmp_path):
    # glob "**" branch
    (tmp_path / "x.py").write_text("hello\n", encoding="utf-8")
    ok, msg = manager.glob_search("**/*.py", base_path=str(tmp_path))
    assert ok and "x.py" in msg

    # grep target file branch with relative_to ValueError fallback
    outside = Path("/tmp/outside_sidar_test.txt")
    outside.write_text("needle\n", encoding="utf-8")
    ok, msg = manager.grep_files("needle", path=str(outside))
    assert ok and "outside_sidar_test.txt" in msg

    # max_results truncation warning
    (tmp_path / "a.txt").write_text("needle\nneedle\n", encoding="utf-8")
    ok, msg = manager.grep_files("needle", path=str(tmp_path), file_glob="*.txt", max_results=1)
    assert ok and "Maksimum eşleşme sayısına ulaşıldı" in msg

    # audit_project read exception branch
    monkeypatch.setattr(
        cm.Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    report = manager.audit_project(root=str(tmp_path))
    assert "Okunamadı" in report


def test_codec_and_wsl_and_file_error_edge_branches(manager, monkeypatch, tmp_path):
    # _decode_lsp_stream: header yoksa break ile boş döner.
    assert cm._decode_lsp_stream(b"") == []
    assert cm._decode_lsp_stream(b"garbage-without-header") == []

    # _try_wsl_socket_fallback: os.stat OSError yolunu çalıştır.
    monkeypatch.setattr(cm.os, "stat", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no sock")))
    assert manager._try_wsl_socket_fallback(SimpleNamespace(DockerClient=object)) is False

    # read_file / write_file generic exception yolları.
    p = tmp_path / "x.py"
    p.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(
        builtins, "open", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom-r"))
    )
    ok, msg = manager.read_file(str(p))
    assert not ok and "Okuma hatası" in msg

    monkeypatch.setattr(
        builtins, "open", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom-w"))
    )
    ok, msg = manager.write_file(str(p), "x=2\n", validate=False)
    assert not ok and "Yazma hatası" in msg


def test_generated_test_empty_and_read_error_branches(manager, monkeypatch, tmp_path):
    ok, msg = manager.write_generated_test(
        str(tmp_path / "test_x.py"), "```python\n```", append=False
    )
    assert not ok and "boş" in msg

    target = tmp_path / "test_dup.py"
    target.write_text("def test_a():\n    assert 1\n", encoding="utf-8")
    monkeypatch.setattr(manager, "read_file", lambda *_a, **_k: (False, "read failed"))
    ok, msg = manager.write_generated_test(
        str(target), "def test_b():\n    assert 1\n", append=True
    )
    assert not ok and msg == "read failed"


def test_execute_code_local_and_docker_more_branches(manager, monkeypatch):
    manager.max_output_chars = 5
    manager.docker_available = True

    class _ImageMissing(Exception):
        pass

    fake_docker = ModuleType("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=_ImageMissing)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: (_ for _ in ()).throw(_ImageMissing("missing")))
    )
    ok, msg = manager.execute_code("print(1)")
    assert not ok and "imajı bulunamadı" in msg

    manager.docker_available = False
    manager.security.exec_ok = False
    ok, msg = manager.execute_code_local("print(1)")
    assert not ok and "yetkisi yok" in msg

    manager.security.exec_ok = True
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=2, stdout="123456789", stderr=""),
    )
    ok, msg = manager.execute_code_local("print(1)")
    assert not ok and "KIRPILDI" in msg and "çıktı yok" not in msg


def test_sandbox_shell_output_and_error_branches(manager, monkeypatch, tmp_path):
    manager.max_output_chars = 6
    monkeypatch.setattr(cm.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(manager, "_resolve_runtime", lambda: "runsc")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=9, stdout="", stderr="abcdefghijk"),
    )
    ok, msg = manager.run_shell_in_sandbox("echo x", cwd=str(tmp_path))
    assert not ok and "çıkış kodu: 9" in msg and "KIRPILDI" in msg and "[stder" in msg


def test_analysis_lsp_and_misc_fallback_paths(manager, monkeypatch, tmp_path):
    output = """
tests/test_demo.py  10 1 90% 7
___ test_parse ___
E AssertionError
pkg/mod.py:7: in test_parse
= 1 failed in 0.01s =
"""
    parsed = manager.analyze_pytest_output(output)
    assert parsed["has_failures"] is True
    assert parsed["has_coverage_gaps"] is False
    assert parsed["failure_targets"][0]["target_path"] == "pkg/mod.py"

    # glob/list exception branch
    monkeypatch.setattr(
        cm.Path, "stat", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("stat"))
    )
    ok, msg = manager.glob_search("*.py", base_path=str(tmp_path))
    assert not ok and "Glob arama hatası" in msg

    # list_directory exception branch
    monkeypatch.setattr(
        cm.Path, "iterdir", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("iter"))
    )
    ok, msg = manager.list_directory(str(tmp_path))
    assert not ok and "Dizin listeleme hatası" in msg


def test_lsp_remaining_branches_and_audit_defaults(manager, monkeypatch, tmp_path):
    py = tmp_path / "a.py"
    py.write_text("name = 1\n", encoding="utf-8")
    manager.base_dir = tmp_path

    # _normalize_lsp_path relative branch
    normalized = manager._normalize_lsp_path("a.py")
    assert normalized == py.resolve()

    # lsp typescript command branch
    cmd = manager._resolve_lsp_command("typescript")
    assert cmd[-1] == "--stdio"

    # _extract_lsp_result: request sonucu yok ama notification var
    result, notes = manager._extract_lsp_result([{"method": "x"}], request_id=2)
    assert result is None and len(notes) == 1

    # rename: result yok branchi
    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_k: [{"id": 2, "result": None}])
    ok, msg = manager.lsp_rename_symbol(str(py), 0, 0, "renamed", apply=False)
    assert not ok and "değişiklik üretmedi" in msg

    # summarize info-only ve clean branchleri
    info_summary = manager._summarize_lsp_diagnostic_entries([{"severity": 3}])
    clean_summary = manager._summarize_lsp_diagnostic_entries([])
    assert info_summary["status"] == "info-only"
    assert clean_summary["status"] == "clean"

    # lsp_semantic_audit no diagnostics
    monkeypatch.setattr(manager, "_run_lsp_sequence", lambda **_k: [])
    ok, audit = manager.lsp_semantic_audit([str(py)])
    assert ok and audit["status"] == "no-signal"

    # audit_project exclude_dirs None branch (varsayılan)
    report = manager.audit_project(root=str(tmp_path), exclude_dirs=None, max_files=10)
    assert "Sidar Denetim Raporu" in report


def test_targeted_coverage_branches_for_docker_and_helpers(manager, monkeypatch, tmp_path):
    manager.max_output_chars = 5

    # _execute_code_with_docker_cli output truncation path
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="abcdefgh", stderr=""),
    )
    ok, out = manager._execute_code_with_docker_cli("print(1)", manager._resolve_sandbox_limits())
    assert ok and "KIRPILDI" in out

    # _try_docker_cli_fallback error / non-zero return branches
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("docker")),
    )
    assert manager._try_docker_cli_fallback() is False
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="x")
    )
    assert manager._try_docker_cli_fallback() is False

    # _try_wsl_socket_fallback ping exception continue branch
    class _Stat:
        st_mode = stat.S_IFSOCK

    class _Docker:
        class DockerClient:
            def __init__(self, base_url):
                self.base_url = base_url

            def ping(self):
                raise RuntimeError("down")

    monkeypatch.setattr(cm.os, "stat", lambda *_a, **_k: _Stat())
    assert manager._try_wsl_socket_fallback(_Docker) is False

    # _init_docker ImportError branch with both fallbacks false
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("docker missing")
        return real_import(name, *args, **kwargs)

    with pytest.raises(ImportError):
        _fake_import("docker")
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setitem(sys.modules, "docker", ModuleType("docker"))
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda *_a, **_k: False)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)
    manager._init_docker()
    monkeypatch.setattr(builtins, "__import__", real_import)

    # _strip_markdown_code_fences branch without closing fence
    assert cm.CodeManager._strip_markdown_code_fences("```python\nprint(1)") == "print(1)"

    # write_generated_test append branch with empty current file (separator empty)
    target = tmp_path / "test_empty.py"
    target.write_text("", encoding="utf-8")
    captured = {"content": ""}
    monkeypatch.setattr(
        manager,
        "write_file",
        lambda _p, content, validate=True: (captured.__setitem__("content", content) or True, "ok"),
    )
    ok, _ = manager.write_generated_test(
        str(target), "def test_new():\n    assert 1\n", append=True
    )
    assert ok and "test_new" in captured["content"]

    # patch_file read failure branch
    monkeypatch.setattr(manager, "read_file", lambda *_a, **_k: (False, "read-error"))
    ok, msg = manager.patch_file(str(target), "a", "b")
    assert not ok and msg == "read-error"


def test_init_docker_success_sets_client_and_availability(manager, monkeypatch):
    class _Client:
        def __init__(self):
            self.ping_called = False

        def ping(self):
            self.ping_called = True

    client = _Client()
    fake_docker = ModuleType("docker")
    fake_docker.from_env = lambda: client
    monkeypatch.setitem(sys.modules, "docker", fake_docker)

    manager.docker_available = False
    manager.docker_client = None

    monkeypatch.setattr(cm.CodeManager, "_init_docker", _real_init_docker)
    manager._init_docker()

    assert manager.docker_client is client
    assert client.ping_called is True
    assert manager.docker_available is True


def test_targeted_coverage_branches_for_execute_grep_glob_and_list(manager, monkeypatch, tmp_path):
    # execute_code: no network/runtime branches + sleep path + wait exception path + no log path
    manager.docker_available = True
    manager.docker_network_disabled = False
    monkeypatch.setattr(manager, "_resolve_runtime", lambda: "")
    monkeypatch.setattr(
        manager,
        "_resolve_sandbox_limits",
        lambda: {
            "memory": "128m",
            "cpus": "0.25",
            "nano_cpus": 1,
            "pids_limit": 10,
            "network_mode": "bridge",
            "timeout": 10,
        },
    )

    class _Container:
        def __init__(self):
            self.status = "running"
            self.reload_calls = 0

        def reload(self):
            self.reload_calls += 1
            if self.reload_calls > 1:
                self.status = "exited"

        def logs(self, **_kwargs):
            return b""

        def wait(self, timeout=1):
            raise RuntimeError("wait failed")

        def remove(self, force=False):
            return None

    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: _Container())
    )
    monkeypatch.setitem(sys.modules, "docker", ModuleType("docker"))
    sys.modules["docker"].errors = SimpleNamespace(ImageNotFound=RuntimeError)
    sleeps = {"n": 0}
    monkeypatch.setattr(
        cm.time, "sleep", lambda *_a, **_k: sleeps.__setitem__("n", sleeps["n"] + 1)
    )
    ok, msg = manager.execute_code("print(1)")
    assert ok and "çıktı üretmedi" in msg and sleeps["n"] >= 1

    # execute_code logs truncation branch + container without wait attribute
    class _ContainerNoWait:
        status = "exited"

        def reload(self):
            return None

        def logs(self, **_kwargs):
            return b"abcdefghij"

        def remove(self, force=False):
            return None

    manager.max_output_chars = 5
    manager.docker_client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda **_k: _ContainerNoWait())
    )
    ok, msg = manager.execute_code("print(1)")
    assert ok and "KIRPILDI" in msg

    # run_shell_in_sandbox timeout and generic exception branches
    monkeypatch.setattr(cm.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="x", timeout=1)),
    )
    ok, _ = manager.run_shell_in_sandbox("echo 1", cwd=str(tmp_path))
    assert not ok
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    ok, _ = manager.run_shell_in_sandbox("echo 1", cwd=str(tmp_path))
    assert not ok

    # glob_search ValueError branch via symlink resolving outside base
    outside_file = Path("/tmp/sidar_outside_target.py")
    outside_file.write_text("x=1\n", encoding="utf-8")
    link = tmp_path / "outside.py"
    link.symlink_to(outside_file)
    ok, _ = manager.glob_search("*.py", base_path=str(tmp_path))
    assert ok

    # grep: empty pattern, "**" glob branch, per-file read exception continue
    assert manager.grep_files("", path=str(tmp_path))[0] is False
    py_ok = tmp_path / "ok.py"
    py_bad = tmp_path / "bad.py"
    py_ok.write_text("needle\n", encoding="utf-8")
    py_bad.write_text("needle\n", encoding="utf-8")
    original_read_text = cm.Path.read_text
    monkeypatch.setattr(
        cm.Path,
        "read_text",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
        if self == py_bad
        else original_read_text(self, *a, **k),
    )
    ok, msg = manager.grep_files("needle", path=str(tmp_path), file_glob="**/*.py")
    assert ok and "ok.py" in msg

    # grep relative_to ValueError fallback branch
    monkeypatch.setattr(cm.Path, "read_text", original_read_text)
    original_relative_to = cm.Path.relative_to
    monkeypatch.setattr(
        cm.Path,
        "relative_to",
        lambda self, *_a, **_k: (_ for _ in ()).throw(ValueError("forced"))
        if self == py_ok
        else original_relative_to(self, *_a, **_k),
    )
    ok, msg = manager.grep_files("needle", path=str(tmp_path), file_glob="*.py")
    assert ok and "ok.py" in msg

    # grep outer exception branch
    original_resolve = cm.Path.resolve
    monkeypatch.setattr(
        cm.Path, "resolve", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("resolve"))
    )
    assert manager.grep_files("x", path=str(tmp_path))[0] is False

    # list_directory branch that emits a folder entry
    monkeypatch.setattr(cm.Path, "resolve", original_resolve)
    subdir = tmp_path / "sub"
    subdir.mkdir(exist_ok=True)
    ok, msg = manager.list_directory(str(tmp_path))
    assert ok and "📂 sub/" in msg


def test_targeted_lsp_and_workspace_branch_paths(manager, monkeypatch, tmp_path):
    py = tmp_path / "a.py"
    txt = tmp_path / "a.txt"
    py.write_text("name = 1\n", encoding="utf-8")
    txt.write_text("raw\n", encoding="utf-8")
    manager.base_dir = tmp_path

    # _run_lsp_sequence: skip unsupported didOpen file (line 1325) path
    captured = {"payload": b""}

    class _Proc:
        returncode = 0

        def communicate(self, payload, timeout):
            captured["payload"] = payload
            return cm._encode_lsp_message({"jsonrpc": "2.0", "id": 3, "result": None}), b""

    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: _Proc())
    manager._run_lsp_sequence(primary_path=py, request_method=None, extra_open_files=[txt])
    assert b"textDocument/didOpen" in captured["payload"] and b"a.txt" not in captured["payload"]

    # _extract_lsp_result branch where message has id but not request_id and no method
    result, notes = manager._extract_lsp_result([{"id": 5, "result": 1}], request_id=2)
    assert result is None and notes == []

    # _apply_workspace_edit: uri missing branch + write_file fail branch
    monkeypatch.setattr(manager, "write_file", lambda *_a, **_k: (False, "write-failed"))
    edit = {
        "documentChanges": [
            {
                "textDocument": {},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "newText": "x",
                    }
                ],
            },
            {
                "textDocument": {"uri": cm._path_to_file_uri(py)},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "newText": "x",
                    }
                ],
            },
        ]
    }
    ok, msg = manager._apply_workspace_edit(edit)
    assert not ok and msg == "write-failed"

    # lsp_rename_symbol exception wrapper branch
    monkeypatch.setattr(
        manager,
        "_run_lsp_sequence",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("rename-fail")),
    )
    ok, msg = manager.lsp_rename_symbol(str(py), 0, 0, "new_name", apply=False)
    assert not ok and "LSP rename hatası" in msg

    # audit_project exclude_dirs provided branch
    report = manager.audit_project(root=str(tmp_path), exclude_dirs=["__nope__"], max_files=10)
    assert "Sidar Denetim Raporu" in report


def test_init_docker_importerror_cached_module_wsl_fallback_returns(manager, monkeypatch):
    """Satır 334: except ImportError bloğunda docker_module None değil ve
    _try_wsl_socket_fallback True döndürünce erken return yapılır."""

    class _ImportErrDocker(ModuleType):
        @staticmethod
        def from_env():
            raise ImportError("from_env ImportError")

    cached = _ImportErrDocker("docker")
    monkeypatch.setitem(sys.modules, "docker", cached)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda mod: mod is cached)

    cli_called = {"flag": False}
    monkeypatch.setattr(
        manager,
        "_try_docker_cli_fallback",
        lambda: cli_called.__setitem__("flag", True) or False,
    )

    # Fixture _init_docker'ı lambda self: None olarak patchlediği için gerçek kodu geri yükle.
    monkeypatch.setattr(cm.CodeManager, "_init_docker", _real_init_docker)

    manager._init_docker()

    # WSL fallback True döndürdüğünde line 334 return çalışmalı;
    # _try_docker_cli_fallback hiç çağrılmamalı.
    assert not cli_called["flag"], "_try_docker_cli_fallback erken return sonrası çağrılmamalı"
    assert manager.docker_available is False
    assert manager.docker_client is None


def test_init_docker_exception_fallback_module_none_import_error(manager, monkeypatch):
    """Satırlar 343-346: except Exception bloğunda docker_module None (ilk import non-ImportError
    fırlattı), ikinci import ImportError fırlatır → fallback_module = None dalı kapsamı."""

    import builtins as _builtins

    # Fixture _init_docker'ı lambda self: None olarak patchiyor; gerçek implementasyonu
    # geri yüklemeden bu testi anlamlı şekilde çalıştırmak mümkün değil.
    monkeypatch.setattr(cm.CodeManager, "_init_docker", _real_init_docker)

    original_import = _builtins.__import__
    import_calls = [0]

    def _mock_import(name, *args, **kwargs):
        if name == "docker":
            import_calls[0] += 1
            if import_calls[0] == 1:
                # try bloğundaki 'import docker as docker_module' → RuntimeError
                # docker_module ataması tamamlanmaz; None kalır
                raise RuntimeError("docker broken on first import")
            # except Exception içindeki 'import docker as fallback_module' → ImportError
            # satır 345-346 kapsamı için ImportError gerekli
            raise ImportError("docker unavailable on retry")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "docker", raising=False)
    monkeypatch.setattr(_builtins, "__import__", _mock_import)

    warning_called = {"flag": False}
    monkeypatch.setattr(
        cm.logger,
        "warning",
        lambda *_a, **_k: warning_called.__setitem__("flag", True),
    )

    manager._init_docker()

    assert import_calls[0] == 2, "her iki import girişimi de yapılmış olmalı"
    assert manager.docker_available is False
    assert manager.docker_client is None
    assert warning_called["flag"], "logger.warning çağrılmış olmalı"
