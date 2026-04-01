from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from managers.code_manager import CodeManager
from managers.security import SecurityManager


def _build_manager(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(CodeManager, "_init_docker", lambda self: None)
    cfg = SimpleNamespace(ACCESS_LEVEL="full", BASE_DIR=tmp_path)
    security = SecurityManager(access_level="full", base_dir=tmp_path, cfg=cfg)
    return CodeManager(security=security, base_dir=tmp_path, cfg=cfg)


def test_code_manager_parses_and_validates_python_ast(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path, monkeypatch)

    ok, msg = manager.validate_python_syntax("def add(a, b):\n    return a + b\n")
    assert ok is True
    assert "geçerli" in msg.lower()

    bad_ok, bad_msg = manager.validate_python_syntax("def broken(:\n    pass\n")
    assert bad_ok is False
    assert "satır" in bad_msg.lower()


def test_code_manager_write_and_read_without_corrupting_file(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path, monkeypatch)
    file_path = tmp_path / "sample.py"
    original = "def x():\n    return 1\n"

    ok, _ = manager.write_file(str(file_path), original, validate=True)
    assert ok is True

    # Geçersiz içerik dosyayı bozmamalı.
    bad_ok, bad_msg = manager.write_file(str(file_path), "def oops(:\n", validate=True)
    assert bad_ok is False
    assert "kaydedilmedi" in bad_msg.lower()

    read_ok, content = manager.read_file(str(file_path), line_numbers=False)
    assert read_ok is True
    assert content == original


def test_code_manager_generated_test_append_is_idempotent(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path, monkeypatch)
    test_file = tmp_path / "tests" / "test_generated.py"
    content = "```python\ndef test_demo():\n    assert 1 == 1\n```"

    ok1, _ = manager.write_generated_test(str(test_file), content, append=True)
    ok2, msg2 = manager.write_generated_test(str(test_file), content, append=True)

    assert ok1 is True
    assert ok2 is True
    assert "zaten mevcut" in msg2.lower()

    read_ok, raw = manager.read_file(str(test_file), line_numbers=False)
    assert read_ok is True
    assert raw.count("def test_demo") == 1
