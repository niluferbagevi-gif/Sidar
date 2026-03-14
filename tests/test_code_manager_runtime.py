# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_modules():
    """Load security/code_manager with temporary config/dotenv stubs (no global pollution)."""
    saved = {k: sys.modules.get(k) for k in ("dotenv", "config", "managers", "managers.security")}
    try:
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

        class _DummyConfig:
            ACCESS_LEVEL = "full"
            BASE_DIR = Path(".")

        sys.modules["config"] = types.SimpleNamespace(Config=_DummyConfig)

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
        return code_mod, sec_mod
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


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


def test_init_docker_importerror_and_wsl_socket_fallback(monkeypatch, tmp_path):
    sec = DummySecurity(tmp_path)
    original_init = CM_MOD.CodeManager._init_docker
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    # ImportError branch
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docker":
            raise ImportError("no docker sdk")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    original_init(mgr)
    assert mgr.docker_available is False

    # WSL socket fallback branch: from_env fails, second socket succeeds
    class _DockerClient:
        def __init__(self, base_url=None):
            self.base_url = base_url

        def ping(self):
            if self.base_url == "unix:///mnt/wsl/docker-desktop/run/guest-services/backend.sock":
                return True
            raise RuntimeError("socket down")

    class _DockerModule:
        DockerClient = _DockerClient

        @staticmethod
        def from_env():
            raise RuntimeError("daemon down")

    monkeypatch.setattr(builtins, "__import__", real_import)
    monkeypatch.setitem(sys.modules, "docker", _DockerModule)
    mgr.docker_available = False
    mgr.docker_client = None
    original_init(mgr)
    assert mgr.docker_available is True
    assert mgr.docker_client.base_url.endswith("backend.sock")


def test_read_write_permission_and_directory_error_paths(manager_factory, monkeypatch, tmp_path):
    mgr = manager_factory(can_read=True, can_write=True)

    # read_file directory path
    ok, msg = mgr.read_file(str(tmp_path), line_numbers=False)
    assert ok is False
    assert "bir dizin" in msg

    # read_file permission error
    import builtins
    real_open = builtins.open

    def deny_read(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(builtins, "open", deny_read)
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    ok, msg = mgr.read_file(str(target), line_numbers=False)
    assert ok is False
    assert "Erişim reddedildi" in msg
    monkeypatch.setattr(builtins, "open", real_open)

    # write_file permission error
    def deny_write(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(builtins, "open", deny_write)
    ok, msg = mgr.write_file(str(tmp_path / "w.txt"), "data", validate=False)
    assert ok is False
    assert "Yazma erişimi reddedildi" in msg
    monkeypatch.setattr(builtins, "open", real_open)

    # write_file to directory path (generic exception branch)
    ok, msg = mgr.write_file(str(tmp_path), "x", validate=False)
    assert ok is False
    assert "Yazma hatası" in msg


def test_patch_file_target_not_found_and_ambiguous(manager_factory, tmp_path):
    mgr = manager_factory(can_read=True, can_write=True)
    f = tmp_path / "p.py"
    f.write_text("a = 1\na = 1\n", encoding="utf-8")

    ok, msg = mgr.patch_file(str(f), "missing", "x")
    assert ok is False
    assert "bulunamadı" in msg

    ok, msg = mgr.patch_file(str(f), "a = 1", "a = 2")
    assert ok is False
    assert "kez geçiyor" in msg


def test_execute_code_docker_happy_path_and_image_not_found(manager_factory, monkeypatch):
    mgr = manager_factory(can_execute=True, level=FULL)
    mgr.docker_available = True

    class _Container:
        def __init__(self, logs=b"hello"):
            self.status = "running"
            self._logs = logs
            self.killed = False
            self.removed = False
            self.reload_count = 0

        def reload(self):
            self.reload_count += 1
            self.status = "exited"

        def kill(self):
            self.killed = True

        def remove(self, force=False):
            self.removed = True

        def logs(self, stdout=True, stderr=True):
            return self._logs

    container = _Container()

    class _Containers:
        def run(self, **kwargs):
            assert kwargs["network_mode"] == "none"
            assert kwargs["mem_limit"] == "256m"
            assert kwargs["nano_cpus"] == 1000000000
            assert kwargs["working_dir"] == "/tmp"
            return container

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    class _DockerModule:
        errors = _DockerErrors

    monkeypatch.setitem(sys.modules, "docker", _DockerModule)

    mgr.docker_client = SimpleNamespace(containers=_Containers())
    ok, msg = mgr.execute_code("print('x')")
    assert ok is True
    assert "Docker Sandbox" in msg
    assert container.removed is True

    # ImageNotFound branch
    class _ContainersErr:
        def run(self, **kwargs):
            raise _DockerErrors.ImageNotFound("missing")

    mgr.docker_client = SimpleNamespace(containers=_ContainersErr())
    ok, msg = mgr.execute_code("print('x')")
    assert ok is False
    assert "imajı bulunamadı" in msg


def test_run_shell_timeout_parse_error_and_output_truncation(manager_factory, monkeypatch):
    mgr = manager_factory(can_shell=True)
    mgr.max_output_chars = 20

    # parse error via shlex
    monkeypatch.setattr(CM_MOD.shlex, "split", lambda _cmd: (_ for _ in ()).throw(ValueError("bad split")))
    ok, msg = mgr.run_shell('echo "unterminated')
    assert ok is False
    assert "ayrıştırılamadı" in msg

    # timeout branch
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=60)

    monkeypatch.setattr(CM_MOD.subprocess, "run", raise_timeout)
    ok, msg = mgr.run_shell("echo hi", allow_shell_features=True)
    assert ok is False
    assert "Zaman aşımı" in msg

    # long output gets truncated
    def long_output(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="a" * 200, stderr="")

    monkeypatch.setattr(CM_MOD.subprocess, "run", long_output)
    monkeypatch.setattr(CM_MOD.shlex, "split", lambda cmd: ["echo", "hi"])
    ok, msg = mgr.run_shell("echo hi")
    assert ok is True
    assert "ÇIKTI KIRPILDI" in msg


def test_execute_code_docker_exception_paths_for_sandbox_and_full(manager_factory, monkeypatch):
    mgr_sb = manager_factory(can_execute=True, level=SANDBOX)
    mgr_sb.docker_available = True

    class _ContainersBoom:
        def run(self, **kwargs):
            raise RuntimeError("container crashed")

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    class _DockerModule:
        errors = _DockerErrors

    monkeypatch.setitem(sys.modules, "docker", _DockerModule)

    mgr_sb.docker_client = SimpleNamespace(containers=_ContainersBoom())
    ok, msg = mgr_sb.execute_code("print('x')")
    assert ok is False
    assert "güvenlik politikası" in msg

    mgr_full = manager_factory(can_execute=True, level=FULL)
    mgr_full.docker_available = True
    mgr_full.docker_client = SimpleNamespace(containers=_ContainersBoom())
    monkeypatch.setattr(mgr_full, "execute_code_local", lambda code: (False, "local fallback"))
    ok, msg = mgr_full.execute_code("print('x')")
    assert ok is False
    assert msg == "local fallback"

def test_code_manager_remaining_branches_matrix(manager_factory, monkeypatch, tmp_path):
    mgr = manager_factory(can_read=False, can_write=False, can_execute=False, can_shell=False)

    # read/write/execute guard branches
    ok, msg = mgr.read_file(str(tmp_path / "x.txt"))
    assert ok is False and "Okuma yetkisi" in msg

    ok, msg = mgr.write_file(str(tmp_path / "x.py"), "print(1)")
    assert ok is False and "Güvenli alternatif" in msg

    ok, msg = mgr.execute_code_local("print('x')")
    assert ok is False and "yetkisi yok" in msg

    # explicit read_file missing + generic exception
    mgr2 = manager_factory(can_read=True, can_write=True, can_shell=True)
    ok, msg = mgr2.read_file(str(tmp_path / "missing.txt"))
    assert ok is False and "bulunamadı" in msg

    import builtins
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("open boom")))
    f = tmp_path / "r.txt"
    f.write_text("abc", encoding="utf-8")
    ok, msg = mgr2.read_file(str(f), line_numbers=False)
    assert ok is False and "Okuma hatası" in msg
    monkeypatch.setattr(builtins, "open", real_open)

    # patch_file read fail branch
    monkeypatch.setattr(mgr2, "read_file", lambda *a, **k: (False, "rfail"))
    assert mgr2.patch_file("x.py", "a", "b") == (False, "rfail")

    # docker timeout branch
    mgr3 = manager_factory(can_execute=True, level=FULL)
    mgr3.docker_available = True

    class _Container:
        status = "running"
        def reload(self):
            self.status = "running"
        def kill(self):
            return None
        def remove(self, force=False):
            return None

    class _Containers:
        def run(self, **kwargs):
            return _Container()

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=_DockerErrors))
    mgr3.docker_client = SimpleNamespace(containers=_Containers())
    mgr3.docker_exec_timeout = 0
    ok, msg = mgr3.execute_code("while True: pass")
    assert ok is False and "Zaman aşımı" in msg

    # execute_code_local generic exception branch
    monkeypatch.setattr(CM_MOD.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("subprocess boom")))
    ok, msg = mgr3.execute_code_local("print(1)")
    assert ok is False and "Subprocess çalıştırma hatası" in msg

    # run_shell empty command, stderr path, nonzero code, generic exception
    ok, msg = mgr2.run_shell("   ")
    assert ok is False and "belirtilmedi" in msg

    monkeypatch.setattr(CM_MOD.shlex, "split", lambda c: ["echo", "x"])
    monkeypatch.setattr(CM_MOD.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    ok, msg = mgr2.run_shell("echo x")
    assert ok is False and "çıkış kodu" in msg and "[stderr]" in msg

    monkeypatch.setattr(CM_MOD.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("shell boom")))
    ok, msg = mgr2.run_shell("echo x", allow_shell_features=True)
    assert ok is False and "Kabuk hatası" in msg

    # glob branches
    ok, msg = mgr2.glob_search("")
    assert ok is False and "deseni" in msg
    ok, msg = mgr2.glob_search("*.py", base_path=str(tmp_path / "none"))
    assert ok is False and "bulunamadı" in msg
    ok, msg = mgr2.glob_search("*.doesnotexist", base_path=str(tmp_path))
    assert ok is True and "bulunamadı" in msg

    # glob exception branch
    monkeypatch.setattr(Path, "glob", lambda self, pattern: (_ for _ in ()).throw(RuntimeError("glob boom")))
    ok, msg = mgr2.glob_search("*.py", base_path=str(tmp_path))
    assert ok is False and "Glob arama hatası" in msg

    # grep branches
    ok, msg = mgr2.grep_files("")
    assert ok is False and "kalıbı" in msg
    ok, msg = mgr2.grep_files("[")
    assert ok is False and "Geçersiz regex" in msg
    ok, msg = mgr2.grep_files("x", path=str(tmp_path / "nope"))
    assert ok is False and "Yol bulunamadı" in msg

    gfile = tmp_path / "g.txt"
    gfile.write_text("a\na\na", encoding="utf-8")
    ok, msg = mgr2.grep_files("a", path=str(gfile), max_results=1)
    assert ok is True and "Maksimum eşleşme" in msg

    # grep outer exception branch
    real_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda self: (_ for _ in ()).throw(RuntimeError("resolve boom")))
    ok, msg = mgr2.grep_files("a", path=str(gfile))
    assert ok is False and "Grep arama hatası" in msg
    monkeypatch.setattr(Path, "resolve", real_resolve)

    # list_directory branches + status docker on
    ok, msg = mgr2.list_directory(str(tmp_path / "no_dir"))
    assert ok is False and "bulunamadı" in msg
    ok, msg = mgr2.list_directory(str(gfile))
    assert ok is False and "dizin değil" in msg

    monkeypatch.setattr(Path, "iterdir", lambda self: (_ for _ in ()).throw(RuntimeError("iter boom")))
    ok, msg = mgr2.list_directory(str(tmp_path))
    assert ok is False and "listeleme hatası" in msg

    # audit non-py skip/max_files and clean message
    p1 = tmp_path / "a.py"
    p2 = tmp_path / "b.txt"
    p1.write_text("x=1", encoding="utf-8")
    p2.write_text("not py", encoding="utf-8")
    rep = mgr2.audit_project(str(tmp_path), max_files=1)
    assert "Dosya limiti" in rep

    mgr2.docker_available = True
    assert "Docker Sandbox Aktif" in mgr2.status()

def test_code_manager_targeted_missing_lines(manager_factory, monkeypatch, tmp_path):
    # line 233: execute_code permission guard
    mgr_guard = manager_factory(can_execute=False)
    ok, msg = mgr_guard.execute_code("print('x')")
    assert ok is False and "Kod çalıştırma yetkisi yok" in msg

    # lines 278, 288, 295: docker loop sleep + log truncation + empty-output branch
    mgr_docker = manager_factory(can_execute=True, level=FULL)
    mgr_docker.docker_available = True
    mgr_docker.max_output_chars = 5

    class _ContainerWithLongLog:
        def __init__(self):
            self.status = "running"
            self.reload_calls = 0

        def reload(self):
            self.reload_calls += 1
            if self.reload_calls >= 2:
                self.status = "exited"

        def kill(self):
            return None

        def remove(self, force=False):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"1234567890"

    class _ContainerNoLog(_ContainerWithLongLog):
        def logs(self, stdout=True, stderr=True):
            return b""

    class _Containers:
        def __init__(self):
            self._calls = 0

        def run(self, **kwargs):
            self._calls += 1
            return _ContainerWithLongLog() if self._calls == 1 else _ContainerNoLog()

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=_DockerErrors))
    monkeypatch.setattr(CM_MOD.time, "sleep", lambda _x: None)
    mgr_docker.docker_client = SimpleNamespace(containers=_Containers())

    ok, msg = mgr_docker.execute_code("print('x')")
    assert ok is True and "ÇIKTI KIRPILDI" in msg

    ok, msg = mgr_docker.execute_code("print('x')")
    assert ok is True and "çıktı üretmedi" in msg

    # lines 336-351: local success/nonzero paths
    mgr_local = manager_factory(can_execute=True, level=FULL)
    monkeypatch.setattr(
        CM_MOD.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    ok, msg = mgr_local.execute_code_local("print('ok')")
    assert ok is True and "Subprocess" in msg

    monkeypatch.setattr(
        CM_MOD.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    ok, msg = mgr_local.execute_code_local("raise SystemExit(1)")
    assert ok is False and "boom" in msg

    # lines 356-357: timeout cleanup unlink exception swallowed
    def _raise_timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="py", timeout=1)

    monkeypatch.setattr(CM_MOD.subprocess, "run", _raise_timeout)
    monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unlink err")))
    ok, msg = mgr_local.execute_code_local("while True: pass")
    assert ok is False and "Zaman aşımı" in msg

    # lines 506-507: glob path outside base skipped by ValueError
    mgr_glob = manager_factory(can_shell=True)
    base = tmp_path / "globbase"
    base.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print(1)", encoding="utf-8")

    def fake_glob(self, pattern):
        if self == base.resolve():
            return [outside.resolve()]
        return []

    monkeypatch.setattr(Path, "glob", fake_glob)
    ok, msg = mgr_glob.glob_search("*.py", base_path=str(base))
    assert ok is True and "Eşleşen dosya bulunamadı" in msg

    # line 571: grep '**'/'/' special branch
    d = tmp_path / "grepdir"
    d.mkdir()
    pyf = d / "a.py"
    pyf.write_text("needle", encoding="utf-8")
    ok, msg = mgr_glob.grep_files("needle", path=str(d), file_glob="**/*.py")
    assert ok is True and "Grep sonuçları" in msg

    # lines 584-585: read_text exception continues
    def bad_read_text(self, *a, **k):
        if self.name == "a.py":
            raise RuntimeError("read fail")
        return ""

    monkeypatch.setattr(Path, "read_text", bad_read_text)
    ok, msg = mgr_glob.grep_files("needle", path=str(d), file_glob="**/*.py")
    assert ok is True and "Eşleşme bulunamadı" in msg

    # lines 607-608: relative_to ValueError fallback rel=fp
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "needle")
    monkeypatch.setattr(Path, "relative_to", lambda self, other: (_ for _ in ()).throw(ValueError("no rel")))
    ok, msg = mgr_glob.grep_files("needle", path=str(d), file_glob="**/*.py")
    assert ok is True and "📄" in msg

    # lines 648-649: list_directory file size formatting path
    lf = tmp_path / "sz.txt"
    lf.write_text("x" * 2048, encoding="utf-8")
    ok, msg = mgr_glob.list_directory(str(tmp_path))
    assert ok is True and "KB" in msg

    # lines 675-676: validate_json decode error
    ok, msg = mgr_glob.validate_json("{broken}")
    assert ok is False and "JSON hatası" in msg

    # lines 721-722: audit_project read error collection
    ad = tmp_path / "audit"
    ad.mkdir()
    (ad / "x.py").write_text("x=1", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("cant read")))
    rep = mgr_glob.audit_project(str(ad), max_files=5)
    assert "Okunamadı" in rep


def test_init_docker_all_sockets_fail_logs_warning(monkeypatch, tmp_path):
    sec = DummySecurity(tmp_path)
    original_init = CM_MOD.CodeManager._init_docker
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    class _DockerClient:
        def __init__(self, base_url=None):
            self.base_url = base_url

        def ping(self):
            raise RuntimeError("down")

    class _DockerModule:
        DockerClient = _DockerClient

        @staticmethod
        def from_env():
            raise RuntimeError("daemon down")

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "docker":
            return _DockerModule
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    original_init(mgr)
    assert mgr.docker_available is False


def test_execute_code_local_unlink_swallow_and_truncate_branch(manager_factory, monkeypatch):
    """execute_code_local içinde unlink hatası yutma (338-339) ve çıktı kırpma (345) yollarını doğrular."""
    mgr = manager_factory(can_execute=True, level=FULL)
    mgr.max_output_chars = 8

    monkeypatch.setattr(
        CM_MOD.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="x" * 50, stderr=""),
    )

    monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unlink failed")))
    ok, msg = mgr.execute_code_local("print('x')")
    assert ok is True
    assert "ÇIKTI KIRPILDI" in msg

def test_execute_code_network_disabled_blocks_outbound_http(manager_factory, monkeypatch):
    mgr = manager_factory(can_execute=True, level=FULL)
    mgr.docker_available = True

    class _Container:
        status = "exited"

        def reload(self):
            return None

        def kill(self):
            return None

        def remove(self, force=False):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"requests.exceptions.ConnectionError: Network is unreachable"

        def wait(self, timeout=1):
            return {"StatusCode": 1}

    class _Containers:
        def run(self, **kwargs):
            assert kwargs.get("network_mode") == "none"
            return _Container()

    class _DockerErrors:
        class ImageNotFound(Exception):
            pass

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(errors=_DockerErrors))
    mgr.docker_client = SimpleNamespace(containers=_Containers())

    ok, msg = mgr.execute_code("import requests; requests.get('https://google.com')")
    assert ok is False
    assert "ConnectionError" in msg or "Network is unreachable" in msg