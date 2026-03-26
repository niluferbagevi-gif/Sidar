from pathlib import Path

import pytest

from tests.test_code_manager_runtime import CM_MOD, DummySecurity


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


def test_write_generated_test_append_surfaces_write_permission_error(manager_factory, tmp_path):
    mgr = manager_factory(can_read=True, can_write=False)
    target = tmp_path / "tests" / "test_generated.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")

    ok, msg = mgr.write_generated_test(
        str(target),
        "def test_new_case():\n    assert 1 == 1\n",
        append=True,
    )

    assert ok is False
    assert "Yazma yetkisi yok" in msg
    assert "Güvenli alternatif" in msg


def test_validate_python_syntax_reports_syntax_error_line_and_message(manager_factory):
    mgr = manager_factory(can_read=True, can_write=True)

    ok, msg = mgr.validate_python_syntax("def broken(:\n    pass\n")

    assert ok is False
    assert "Sözdizimi hatası" in msg
    assert "Satır 1" in msg


def test_analyze_pytest_output_keeps_empty_target_path_when_regex_finds_no_python_file(manager_factory):
    mgr = manager_factory(can_read=True, can_write=True)
    output = """
___________________ test_permission_denied ___________________
Traceback (most recent call last):
  File \"<stdin>\", line 1, in <module>
PermissionError: denied
=========================== short test summary info ===========================
1 failed in 0.10s
"""

    analysis = mgr.analyze_pytest_output(output)

    assert analysis["summary"] == "1 failed"
    assert analysis["failure_targets"][0]["summary"] == "pytest failure detected"
    assert analysis["failure_targets"][0]["target_path"] == ""
    assert "PermissionError" in analysis["failure_targets"][0]["details"]


def test_grep_files_rejects_blank_pattern_before_compiling_regex(manager_factory, tmp_path):
    mgr = manager_factory(can_read=True, can_write=True)
    sample = tmp_path / "sample.py"
    sample.write_text("print('hello')\n", encoding="utf-8")

    ok, msg = mgr.grep_files("", path=str(tmp_path), file_glob="*.py")

    assert ok is False
    assert "Arama kalıbı belirtilmedi" in msg