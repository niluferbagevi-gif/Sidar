"""CodeManager güvenlik/perf iyileştirmeleri için regresyon testleri."""

from pathlib import Path
import importlib.util
import sys
import types


def _load_security_and_code_manager():
    pkg = types.ModuleType("managers")
    pkg.__path__ = [str(Path("managers").resolve())]
    sys.modules.setdefault("managers", pkg)

    sec_spec = importlib.util.spec_from_file_location("managers.security", "managers/security.py")
    sec_mod = importlib.util.module_from_spec(sec_spec)
    sys.modules["managers.security"] = sec_mod
    sec_spec.loader.exec_module(sec_mod)

    cm_spec = importlib.util.spec_from_file_location("managers.code_manager", "managers/code_manager.py")
    cm_mod = importlib.util.module_from_spec(cm_spec)
    sys.modules["managers.code_manager"] = cm_mod
    cm_spec.loader.exec_module(cm_mod)

    return sec_mod.SecurityManager, cm_mod.CodeManager


def test_run_shell_rejects_shell_metachar(tmp_path):
    SecurityManager, CodeManager = _load_security_and_code_manager()
    sec = SecurityManager("full", tmp_path)
    mgr = CodeManager(sec, tmp_path)

    ok, out = mgr.run_shell("echo ok && echo unsafe")

    assert ok is False
    assert "metachar" in out


def test_run_shell_simple_command_with_shell_false(tmp_path):
    SecurityManager, CodeManager = _load_security_and_code_manager()
    sec = SecurityManager("full", tmp_path)
    mgr = CodeManager(sec, tmp_path)

    ok, out = mgr.run_shell("echo sidar")

    assert ok is True
    assert "sidar" in out


def test_audit_project_skips_vendor_like_dirs(tmp_path):
    SecurityManager, CodeManager = _load_security_and_code_manager()
    sec = SecurityManager("full", tmp_path)
    mgr = CodeManager(sec, tmp_path)

    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "good.py").write_text("print('ok')\n", encoding="utf-8")

    (tmp_path / "node_modules").mkdir(parents=True)
    (tmp_path / "node_modules" / "bad.py").write_text("def oops(:\n", encoding="utf-8")

    report = mgr.audit_project(str(tmp_path))

    assert "Toplam Python dosyası : 1" in report
    assert "Atlanan dizinler" in report
    assert "node_modules" in report