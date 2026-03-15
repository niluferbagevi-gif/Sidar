import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL


def test_code_manager_import_fallback_without_sandbox_limits(monkeypatch):
    saved = {k: sys.modules.get(k) for k in ("config", "managers", "managers.security")}
    try:
        class _Cfg:
            pass

        # from config import Config, SANDBOX_LIMITS -> ImportError branch
        monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(Config=_Cfg))

        pkg = types.ModuleType("managers")
        pkg.__path__ = [str(Path("managers").resolve())]
        monkeypatch.setitem(sys.modules, "managers", pkg)

        sec_spec = importlib.util.spec_from_file_location("managers.security", Path("managers/security.py"))
        sec_mod = importlib.util.module_from_spec(sec_spec)
        assert sec_spec and sec_spec.loader
        sec_spec.loader.exec_module(sec_mod)
        monkeypatch.setitem(sys.modules, "managers.security", sec_mod)

        code_spec = importlib.util.spec_from_file_location("managers.code_manager_fallback_test", Path("managers/code_manager.py"))
        mod = importlib.util.module_from_spec(code_spec)
        assert code_spec and code_spec.loader
        code_spec.loader.exec_module(mod)

        assert mod.SANDBOX_LIMITS == {}
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


def test_resolve_sandbox_limits_handles_invalid_cpus_and_min_bounds():
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.cfg = SimpleNamespace(SANDBOX_LIMITS={"cpus": "oops", "pids_limit": 0, "timeout": 0, "network": "NONE"})
    mgr.docker_mem_limit = "512m"
    mgr.docker_exec_timeout = 33
    mgr.docker_nano_cpus = 777

    out = mgr._resolve_sandbox_limits()
    assert out["nano_cpus"] == 777
    assert out["pids_limit"] == 64
    assert out["timeout"] == 10
    assert out["network_mode"] == "none"


def test_build_docker_cli_command_uses_limits_values():
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.docker_image = "python:3.11-alpine"

    cmd = mgr._build_docker_cli_command(
        "print(1)",
        {"memory": "128m", "cpus": "0.25", "pids_limit": 32, "network_mode": "bridge"},
    )

    assert "--memory=128m" in cmd
    assert "--cpus=0.25" in cmd
    assert "--pids-limit=32" in cmd
    assert "--network=bridge" in cmd


def test_execute_code_with_docker_cli_error_truncation_and_success(monkeypatch, tmp_path):
    mgr = object.__new__(CM_MOD.CodeManager)
    mgr.base_dir = tmp_path
    mgr.max_output_chars = 20
    mgr.docker_image = "python:3.11-alpine"

    def _nonzero(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="x" * 50, stderr="")

    monkeypatch.setattr(CM_MOD.subprocess, "run", _nonzero)
    ok, msg = mgr._execute_code_with_docker_cli("print(1)", {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 1})
    assert ok is False
    assert "Docker CLI Sandbox" in msg
    assert "ÇIKTI KIRPILDI" in msg

    def _success(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(CM_MOD.subprocess, "run", _success)
    ok2, msg2 = mgr._execute_code_with_docker_cli("print(1)", {"memory": "256m", "cpus": "0.5", "pids_limit": 64, "network_mode": "none", "timeout": 1})
    assert ok2 is True
    assert "kod çalıştı, çıktı yok" in msg2


def test_execute_code_full_mode_cli_timeout_branch(monkeypatch, tmp_path):
    sec = DummySecurity(tmp_path, can_execute=True, level=FULL)
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)
    mgr.docker_available = True

    class _ContainersBoom:
        def run(self, **kwargs):
            raise RuntimeError("sdk failed")

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=_DockerErrors))
    mgr.docker_client = SimpleNamespace(containers=_ContainersBoom())

    monkeypatch.setattr(
        mgr,
        "_execute_code_with_docker_cli",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="docker", timeout=7)),
    )

    ok, msg = mgr.execute_code("print('x')")
    assert ok is False
    assert "Zaman aşımı" in msg