import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_module(module_name: str, file_path: str, stubs: dict[str, object] | None = None):
    stubs = stubs or {}
    saved = {k: sys.modules.get(k) for k in stubs}
    try:
        for k, v in stubs.items():
            sys.modules[k] = v
        spec = importlib.util.spec_from_file_location(module_name, Path(file_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k in stubs:
            if saved[k] is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = saved[k]


@pytest.fixture
def code_modules(tmp_path):
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    config_mod = _load_module("config_cm_cov", "config.py", {"dotenv": dotenv_mod})

    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = [str(Path("managers").resolve())]

    security_mod = _load_module(
        "managers.security",
        "managers/security.py",
        {"config": config_mod, "managers": managers_pkg},
    )
    code_mod = _load_module(
        "managers.code_manager",
        "managers/code_manager.py",
        {"managers": managers_pkg, "managers.security": security_mod},
    )
    return code_mod, security_mod


@pytest.fixture
def mock_security(code_modules):
    _code_mod, security_mod = code_modules
    sec = MagicMock(spec=security_mod.SecurityManager)
    sec.can_read.return_value = True
    sec.can_write.return_value = True
    sec.can_execute.return_value = True
    sec.can_run_shell.return_value = True
    sec.level = security_mod.FULL
    sec.get_safe_write_path.return_value = Path("temp/safe.py")
    return sec


@pytest.fixture
def cm(code_modules, mock_security, tmp_path):
    code_mod, _security_mod = code_modules
    with patch.object(code_mod.CodeManager, "_init_docker"):
        manager = code_mod.CodeManager(security=mock_security, base_dir=tmp_path)
        manager.docker_available = False
        return manager


def test_init_docker_wsl_loop_exception(code_modules, mock_security, tmp_path):
    code_mod, _ = code_modules

    mock_docker = types.SimpleNamespace(
        from_env=MagicMock(side_effect=Exception("from_env failed")),
        DockerClient=MagicMock(side_effect=Exception("socket failed")),
    )
    with patch.dict(sys.modules, {"docker": mock_docker}):
        cm_test = code_mod.CodeManager(security=mock_security, base_dir=tmp_path)
        assert cm_test.docker_available is False


def test_write_file_generic_exception(cm):
    with patch("pathlib.Path.mkdir", side_effect=Exception("Generic Write Error")):
        ok, msg = cm.write_file("test.py", "print('hello')", validate=False)
        assert ok is False
        assert "Yazma hatası: Generic Write Error" in msg


def test_execute_code_image_not_found(cm, code_modules):
    code_mod, _ = code_modules
    cm.docker_available = True
    cm.docker_client = MagicMock()

    class FakeImageNotFound(Exception):
        pass

    cm.docker_client.containers.run.side_effect = FakeImageNotFound("Img not found")
    fake_docker = types.SimpleNamespace(errors=types.SimpleNamespace(ImageNotFound=FakeImageNotFound))

    with patch.dict(sys.modules, {"docker": fake_docker}):
        ok, msg = cm.execute_code("print('hi')")
        assert ok is False
        assert "imajı bulunamadı" in msg


def test_execute_code_sandbox_exception(cm, code_modules):
    _code_mod, security_mod = code_modules
    cm.docker_available = True
    cm.docker_client = MagicMock()
    cm.docker_client.containers.run.side_effect = Exception("Docker Crash")
    cm.security.level = security_mod.SANDBOX

    class FakeImageNotFound(Exception):
        pass

    fake_docker = types.SimpleNamespace(errors=types.SimpleNamespace(ImageNotFound=FakeImageNotFound))
    with patch.dict(sys.modules, {"docker": fake_docker}):
        ok, msg = cm.execute_code("print('hi')")
        assert ok is False
        assert "güvenlik politikası gereği" in msg


def test_execute_code_local_no_permission(cm):
    cm.security.can_execute.return_value = False
    ok, msg = cm.execute_code_local("print(1)")
    assert ok is False
    assert "Kod çalıştırma yetkisi yok" in msg


def test_execute_code_local_timeout_unlink_exception(cm):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=10)), patch(
        "pathlib.Path.unlink", side_effect=Exception("Unlink error")
    ):
        ok, msg = cm.execute_code_local("while True: pass")
        assert ok is False
        assert "Zaman aşımı" in msg


def test_run_shell_shlex_value_error(cm):
    ok, msg = cm.run_shell('echo "unclosed', allow_shell_features=False)
    assert ok is False
    assert "Komut ayrıştırılamadı" in msg


def test_grep_files_exception(cm):
    with patch("pathlib.Path.resolve", side_effect=Exception("Grep Boom")):
        ok, msg = cm.grep_files("pattern")
        assert ok is False
        assert "Grep arama hatası" in msg


def test_list_directory_exception(cm):
    with patch("pathlib.Path.resolve", side_effect=Exception("List Boom")):
        ok, msg = cm.list_directory()
        assert ok is False
        assert "Dizin listeleme hatası" in msg


def test_audit_project_read_exception(cm, tmp_path):
    test_file = tmp_path / "bad.py"
    test_file.write_text("print('hi')", encoding="utf-8")

    with patch("pathlib.Path.read_text", side_effect=Exception("Read Boom")):
        report = cm.audit_project(root=str(tmp_path))
        assert "Okunamadı" in report


def test_audit_project_max_files_limit(cm, tmp_path):
    (tmp_path / "1.py").write_text("a=1", encoding="utf-8")
    (tmp_path / "2.py").write_text("b=2", encoding="utf-8")
    report = cm.audit_project(root=str(tmp_path), max_files=1)
    assert "Dosya limiti nedeniyle" in report


def test_status_and_repr(cm):
    cm.docker_available = True
    cm.docker_image = "test-image:latest"
    assert "Docker Sandbox Aktif" in cm.status()

    cm.docker_available = False
    assert "Subprocess Modu" in cm.status()

    rep = repr(cm)
    assert "<CodeManager" in rep
    assert "reads=0" in rep
