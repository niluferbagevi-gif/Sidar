import builtins
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


def test_init_docker_importerror_returns_after_wsl_socket_fallback(monkeypatch, tmp_path):
    manager = object.__new__(CM_MOD.CodeManager)
    manager.base_dir = tmp_path
    manager.docker_available = False
    manager.docker_client = None

    sentinel_docker = object()
    monkeypatch.setitem(sys.modules, "docker", sentinel_docker)

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docker":
            raise ImportError("docker missing")
        return real_import(name, globals, locals, fromlist, level)

    seen = []
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda docker_mod: seen.append(docker_mod) or True)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: (_ for _ in ()).throw(AssertionError("cli fallback should not run")))

    CM_MOD.CodeManager._init_docker(manager)

    assert seen == [sentinel_docker]


def test_init_docker_importerror_logs_warning_when_all_fallbacks_fail(monkeypatch, tmp_path):
    manager = object.__new__(CM_MOD.CodeManager)
    manager.base_dir = tmp_path
    manager.docker_available = False
    manager.docker_client = None

    monkeypatch.delitem(sys.modules, "docker", raising=False)
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docker":
            raise ImportError("docker missing")
        return real_import(name, globals, locals, fromlist, level)

    warnings = []
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(manager, "_try_wsl_socket_fallback", lambda _docker_mod: False)
    monkeypatch.setattr(manager, "_try_docker_cli_fallback", lambda: False)
    monkeypatch.setattr(CM_MOD.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    CM_MOD.CodeManager._init_docker(manager)

    assert warnings == ["Docker SDK kurulu değil. (pip install docker)"]
    assert manager.docker_available is False
    assert manager.docker_client is None


def test_resolve_sandbox_limits_converts_positive_cpu_value_to_nano_cpus():
    manager = object.__new__(CM_MOD.CodeManager)
    manager.cfg = types.SimpleNamespace(SANDBOX_LIMITS={"cpus": "1.25", "pids_limit": 8, "timeout": 12, "network": "bridge"})
    manager.docker_mem_limit = "256m"
    manager.docker_exec_timeout = 10
    manager.docker_nano_cpus = 111

    limits = manager._resolve_sandbox_limits()

    assert limits["cpus"] == "1.25"
    assert limits["nano_cpus"] == 1_250_000_000


def test_strip_markdown_code_fences_handles_missing_and_present_closing_fence():
    stripped_open_only = CM_MOD.CodeManager._strip_markdown_code_fences("```python\nprint('x')")
    stripped_closed = CM_MOD.CodeManager._strip_markdown_code_fences("```python\nprint('x')\n```")

    assert stripped_open_only == "print('x')"
    assert stripped_closed == "print('x')"


def test_execute_code_does_not_force_network_none_when_bridge_mode_is_selected(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path, can_execute=True)
    manager.docker_available = True
    captured = {}

    class _Container:
        status = "exited"

        def reload(self):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"bridge ok"

        def wait(self, timeout=1):
            return {"StatusCode": 0}

        def remove(self, force=True):
            return None

    def _run_container(**kwargs):
        captured.update(kwargs)
        return _Container()

    manager.docker_client = types.SimpleNamespace(containers=types.SimpleNamespace(run=_run_container))
    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=types.SimpleNamespace(ImageNotFound=RuntimeError)))
    monkeypatch.setattr(manager, "_resolve_sandbox_limits", lambda: {"memory": "256m", "nano_cpus": 5, "pids_limit": 64, "timeout": 5, "network_mode": "bridge"})
    monkeypatch.setattr(manager, "_resolve_runtime", lambda: "")
    manager.docker_network_disabled = False

    ok, message = manager.execute_code("print('bridge')")

    assert ok is True
    assert "bridge ok" in message
    assert "network_mode" not in captured


def test_apply_workspace_edit_ignores_document_changes_without_uri(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)

    ok, output = manager._apply_workspace_edit({
        "documentChanges": [
            {
                "textDocument": {},
                "edits": [{"newText": "ignored"}],
            }
        ]
    })

    assert ok is False
    assert output == "Workspace edit boş döndü."


def test_audit_project_respects_custom_exclude_dirs(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path, can_shell=True)
    root = tmp_path / "audit-custom-exclude"
    (root / "skipme").mkdir(parents=True)
    (root / "keep").mkdir()
    (root / "skipme" / "ignored.py").write_text("def bad(:\n", encoding="utf-8")
    (root / "keep" / "good.py").write_text("value = 1\n", encoding="utf-8")

    report = manager.audit_project(str(root), exclude_dirs=["skipme"])

    assert "Toplam Python dosyası : 1" in report
    assert "ignored.py" not in report
    assert "Tüm dosyalar sözdizimi açısından temiz" in report
