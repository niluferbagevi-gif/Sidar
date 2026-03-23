from pathlib import Path
from types import SimpleNamespace

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL


def _make_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    manager = CM_MOD.CodeManager(DummySecurity(tmp_path, level=FULL), tmp_path)
    manager.docker_available = False
    manager.docker_client = None
    return manager


def test_file_uri_to_path_windows_non_drive_path_and_empty_cpu_limits(monkeypatch):
    with monkeypatch.context() as ctx:
        ctx.setattr(CM_MOD.os, "name", "nt")
        original_platform = CM_MOD.sys.platform
        ctx.setattr(CM_MOD.sys, "platform", "linux")
        converted = CM_MOD._file_uri_to_path("file:///workspace/Sidar/demo.py")
        assert str(converted).endswith("workspace\\Sidar\\demo.py")
        ctx.setattr(CM_MOD.sys, "platform", original_platform)

    manager = object.__new__(CM_MOD.CodeManager)
    manager.cfg = SimpleNamespace(SANDBOX_LIMITS={"cpus": "", "pids_limit": -1, "timeout": -2})
    manager.docker_mem_limit = "384m"
    manager.docker_exec_timeout = 19
    manager.docker_nano_cpus = 123

    limits = manager._resolve_sandbox_limits()

    assert limits["nano_cpus"] == 500000000
    assert limits["pids_limit"] == 64
    assert limits["timeout"] == 10


def test_docker_cli_and_wsl_fallback_failure_paths(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)

    monkeypatch.setattr(
        CM_MOD.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="daemon down"),
    )
    assert manager._try_docker_cli_fallback() is False

    def _timeout(*args, **kwargs):
        raise CM_MOD.subprocess.TimeoutExpired(cmd="docker info", timeout=5)

    monkeypatch.setattr(CM_MOD.subprocess, "run", _timeout)
    assert manager._try_docker_cli_fallback() is False

    docker_module = SimpleNamespace(DockerClient=lambda base_url=None: None)
    monkeypatch.setattr(CM_MOD.os, "stat", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")))
    assert manager._try_wsl_socket_fallback(docker_module) is False


def test_lsp_workspace_diagnostics_formats_issues_even_when_audit_reports_failure(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    issue = {
        "path": str(tmp_path / "demo.py"),
        "line": 7,
        "character": 4,
        "severity": 2,
        "message": "unused import",
    }
    monkeypatch.setattr(
        manager,
        "lsp_semantic_audit",
        lambda _paths=None: (False, {"issues": [issue], "summary": "tool error"}),
    )

    ok, output = manager.lsp_workspace_diagnostics([str(Path(issue["path"]))])

    assert ok is False
    assert "unused import" in output
    assert "severity=2" in output
