import sys
import types
from pathlib import Path

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL

def _make_manager(monkeypatch, tmp_path, **security_kwargs):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    sec = DummySecurity(tmp_path, level=FULL, **security_kwargs)
    manager = CM_MOD.CodeManager(sec, tmp_path)
    manager.docker_available = False
    manager.docker_client = None
    return manager

def test_code_manager_resolve_sandbox_limits_keeps_default_nano_cpus_for_zero_cpu_value():
    manager = object.__new__(CM_MOD.CodeManager)
    manager.cfg = types.SimpleNamespace(SANDBOX_LIMITS={"cpus": "0", "pids_limit": 8, "timeout": 12, "network": "bridge"})
    manager.docker_mem_limit = "512m"
    manager.docker_exec_timeout = 20
    manager.docker_nano_cpus = 123456789

    limits = manager._resolve_sandbox_limits()

    assert limits["nano_cpus"] == 123456789
    assert limits["pids_limit"] == 8
    assert limits["timeout"] == 12
    assert limits["network_mode"] == "bridge"

def test_code_manager_execute_code_accepts_non_dict_wait_result_and_cleans_container(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path, can_execute=True)
    manager.docker_available = True

    state = {"removed": False}

    class _Container:
        status = "exited"

        def reload(self):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"docker ok"

        def wait(self, timeout=1):
            return "unexpected-status-format"

        def remove(self, force=True):
            state["removed"] = force

    manager.docker_client = types.SimpleNamespace(containers=types.SimpleNamespace(run=lambda **_kwargs: _Container()))
    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=types.SimpleNamespace(ImageNotFound=RuntimeError)))
    monkeypatch.setattr(manager, "_resolve_sandbox_limits", lambda: {"memory": "256m", "nano_cpus": 1, "pids_limit": 64, "timeout": 5, "network_mode": "none"})
    monkeypatch.setattr(manager, "_resolve_runtime", lambda: "")

    ok, message = manager.execute_code("print('ok')")

    assert ok is True
    assert "docker ok" in message
    assert state["removed"] is True

def test_code_manager_audit_project_uses_default_excludes_and_reports_syntax_errors(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path, can_shell=True)
    root = tmp_path / "audit-defaults"
    (root / ".git").mkdir(parents=True)
    (root / "good.py").write_text("value = 1\n", encoding="utf-8")
    (root / "broken.py").write_text("def bad(:\n", encoding="utf-8")
    (root / ".git" / "ignored.py").write_text("def skipped(:\n", encoding="utf-8")

    report = manager.audit_project(str(root))

    assert "Toplam Python dosyası : 2" in report
    assert "broken.py: Sözdizimi hatası" in report
    assert "ignored.py" not in report

def test_code_manager_audit_project_reports_permission_error_as_unreadable(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path, can_shell=True)
    root = tmp_path / "audit-permissions"
    root.mkdir()
    locked = root / "locked.py"
    locked.write_text("print('secret')\n", encoding="utf-8")

    original_read_text = Path.read_text

    def _deny_read(self, *args, **kwargs):
        if self == locked:
            raise PermissionError("denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _deny_read)

    report = manager.audit_project(str(root))

    assert "locked.py" in report
    assert "Okunamadı" in report
    assert "denied" in report