import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)
if "config" not in sys.modules:
    class _DummyConfig:
        ACCESS_LEVEL = "full"
        BASE_DIR = Path(".")

    sys.modules["config"] = types.SimpleNamespace(Config=_DummyConfig)


def _load_modules():
    if "managers" not in sys.modules:
        pkg = types.ModuleType("managers")
        pkg.__path__ = [str(Path("managers").resolve())]
        sys.modules["managers"] = pkg

    sec_spec = importlib.util.spec_from_file_location("managers.security", Path("managers/security.py"))
    sec_mod = importlib.util.module_from_spec(sec_spec)
    assert sec_spec and sec_spec.loader
    sec_spec.loader.exec_module(sec_mod)
    sys.modules["managers.security"] = sec_mod

    code_spec = importlib.util.spec_from_file_location("managers.code_manager", Path("managers/code_manager.py"))
    code_mod = importlib.util.module_from_spec(code_spec)
    assert code_spec and code_spec.loader
    code_spec.loader.exec_module(code_mod)
    sys.modules["managers.code_manager"] = code_mod
    return code_mod, sec_mod


CM_MOD, SEC_MOD = _load_modules()
FULL = SEC_MOD.FULL
SANDBOX = SEC_MOD.SANDBOX


class DummySecurity:
    def __init__(self, base_dir: Path, *, can_read=True, can_write=True, can_execute=True, can_shell=True, level=FULL):
        self.base_dir = base_dir
        self._can_read = can_read
        self._can_write = can_write
        self._can_execute = can_execute
        self._can_shell = can_shell
        self.level = level

    def can_read(self, path=None):
        return self._can_read

    def can_write(self, path):
        return self._can_write

    def can_execute(self):
        return self._can_execute

    def can_run_shell(self):
        return self._can_shell

    def get_safe_write_path(self, filename):
        return self.base_dir / "temp" / filename


@pytest.fixture
def manager_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)

    def _make(**kwargs):
        sec = DummySecurity(tmp_path, **kwargs)
        mgr = CM_MOD.CodeManager(sec, tmp_path)
        mgr.docker_available = False
        mgr.docker_client = None
        return mgr

    return _make


def test_read_write_patch_and_metrics(manager_factory, tmp_path):
    mgr = manager_factory(can_shell=True)

    target = tmp_path / "sample.py"
    ok, msg = mgr.write_file(str(target), "a = 1\n", validate=True)
    assert ok is True
    assert "başarıyla kaydedildi" in msg

    ok, content = mgr.read_file(str(target), line_numbers=True)
    assert ok is True
    assert "1\ta = 1" in content

    ok, _ = mgr.patch_file(str(target), "a = 1", "a = 2")
    assert ok is True
    assert target.read_text(encoding="utf-8") == "a = 2\n"

    metrics = mgr.get_metrics()
    assert metrics["files_read"] >= 1
    assert metrics["files_written"] >= 2


def test_write_file_rejects_invalid_python_and_no_write_permission(manager_factory, tmp_path):
    mgr = manager_factory(can_write=True)
    bad_py = tmp_path / "bad.py"
    ok, msg = mgr.write_file(str(bad_py), "def broken(:\n", validate=True)
    assert ok is False
    assert "Sözdizimi hatası" in msg

    mgr2 = manager_factory(can_write=False)
    blocked = tmp_path / "x.txt"
    ok, msg = mgr2.write_file(str(blocked), "data", validate=False)
    assert ok is False
    assert "Yazma yetkisi yok" in msg


def test_execute_code_paths_and_local_timeout(manager_factory, monkeypatch):
    mgr_sandbox = manager_factory(can_execute=True, level=SANDBOX)
    ok, msg = mgr_sandbox.execute_code("print('x')")
    assert ok is False
    assert "yerel (unsafe) çalıştırma engellendi" in msg

    mgr_full = manager_factory(can_execute=True, level=FULL)
    called = {"local": 0}

    def fake_local(code):
        called["local"] += 1
        return True, "ok"

    monkeypatch.setattr(mgr_full, "execute_code_local", fake_local)
    ok, msg = mgr_full.execute_code("print('x')")
    assert ok is True and msg == "ok"
    assert called["local"] == 1

    mgr_timeout = manager_factory(can_execute=True, level=FULL)

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(CM_MOD.subprocess, "run", raise_timeout)
    ok, msg = mgr_timeout.execute_code_local("while True: pass")
    assert ok is False
    assert "Zaman aşımı" in msg


def test_run_shell_guards_and_success_output(manager_factory, monkeypatch):
    mgr_no_shell = manager_factory(can_shell=False)
    ok, msg = mgr_no_shell.run_shell("echo hi")
    assert ok is False
    assert "Kabuk komutu çalıştırma yetkisi yok" in msg

    mgr = manager_factory(can_shell=True)
    ok, msg = mgr.run_shell("echo hi | cat", allow_shell_features=False)
    assert ok is False
    assert "shell operatörleri" in msg

    called = {}

    def fake_run(cmd, shell, capture_output, text, timeout, cwd, env):
        called["cmd"] = cmd
        called["shell"] = shell
        return SimpleNamespace(returncode=0, stdout="out\n", stderr="")

    monkeypatch.setattr(CM_MOD.subprocess, "run", fake_run)
    ok, msg = mgr.run_shell("echo hello")
    assert ok is True
    assert "out" in msg
    assert called["shell"] is False
    assert isinstance(called["cmd"], list)


def test_glob_grep_and_list_directory(manager_factory, tmp_path):
    mgr = manager_factory(can_shell=True)

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print('hello')\nneedle\n", encoding="utf-8")
    (src / "b.txt").write_text("NEEDLE\n", encoding="utf-8")

    ok, glob_out = mgr.glob_search("**/*.py", str(tmp_path))
    assert ok is True
    assert "a.py" in glob_out

    ok, grep_out = mgr.grep_files("needle", path=str(tmp_path), file_glob="*.py", context_lines=1)
    assert ok is True
    assert "Grep sonuçları" in grep_out
    assert "a.py" in grep_out

    ok, no_match = mgr.grep_files("not_found", path=str(tmp_path), file_glob="*.py")
    assert ok is True
    assert "Eşleşme bulunamadı" in no_match

    ok, listing = mgr.list_directory(str(tmp_path))
    assert ok is True
    assert "📁" in listing
    assert "src/" in listing


def test_validation_audit_status_and_repr(manager_factory, tmp_path):
    mgr = manager_factory(can_shell=True)

    ok, py_msg = mgr.validate_python_syntax("x = 1")
    assert ok is True
    assert "geçerli" in py_msg.lower()

    ok, json_msg = mgr.validate_json('{"a": 1}')
    assert ok is True
    assert "Geçerli JSON" in json_msg

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "bad.py").write_text("def oops(:\n", encoding="utf-8")

    report = mgr.audit_project(str(pkg), max_files=10)
    assert "Toplam Python dosyası" in report
    assert "Hatalı" in report

    assert "CodeManager:" in mgr.status()
    assert "<CodeManager" in repr(mgr)
