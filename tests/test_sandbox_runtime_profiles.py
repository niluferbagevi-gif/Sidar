from pathlib import Path

from managers.code_manager import CodeManager
from managers.security import SecurityManager


class _Cfg:
    DOCKER_RUNTIME = ""
    DOCKER_ALLOWED_RUNTIMES = ["", "runc", "runsc", "kata-runtime"]
    DOCKER_MICROVM_MODE = "off"
    DOCKER_MEM_LIMIT = "256m"
    DOCKER_NETWORK_DISABLED = True
    DOCKER_NANO_CPUS = 1_000_000_000


def _make_manager(monkeypatch, mode: str, runtime: str = "") -> CodeManager:
    monkeypatch.setattr(CodeManager, "_init_docker", lambda self: None)
    cfg = _Cfg()
    cfg.DOCKER_MICROVM_MODE = mode
    cfg.DOCKER_RUNTIME = runtime
    sec = SecurityManager(access_level="sandbox", base_dir=Path("."))
    return CodeManager(security=sec, base_dir=Path("."), cfg=cfg)


def test_runtime_defaults_to_runsc_for_gvisor(monkeypatch):
    mgr = _make_manager(monkeypatch, mode="gvisor")
    assert mgr._resolve_runtime() == "runsc"


def test_runtime_defaults_to_kata_for_kata_mode(monkeypatch):
    mgr = _make_manager(monkeypatch, mode="kata")
    assert mgr._resolve_runtime() == "kata-runtime"


def test_runtime_rejects_non_allowlisted_runtime(monkeypatch):
    mgr = _make_manager(monkeypatch, mode="off", runtime="evil-runtime")
    assert mgr._resolve_runtime() == ""