import builtins
from pathlib import Path
from textwrap import dedent

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL


def _manager(tmp_path: Path):
    security = DummySecurity(tmp_path, can_execute=True, can_shell=True, level=FULL)
    return CM_MOD.CodeManager(security=security, base_dir=tmp_path)


def test_code_manager_analyze_pytest_output_extracts_coverage_and_failures(tmp_path):
    manager = _manager(tmp_path)
    output = """
============================= test session starts =============================
________________________________ test_demo ___________________________________
core/sample.py:12: AssertionError
---------- coverage: platform linux, python 3.12 ----------
Name                Stmts   Miss  Cover   Missing
-------------------------------------------------
core/sample.py         20      4    80%   10-12, 18
tests/test_x.py         5      0   100%
TOTAL                  25      4    84%
=========================== short test summary info ===========================
1 failed, 4 passed in 0.55s
"""
    analysis = manager.analyze_pytest_output(output)

    assert analysis["has_failures"] is True
    assert analysis["has_coverage_gaps"] is True
    assert analysis["coverage_targets"][0]["target_path"] == "core/sample.py"
    assert analysis["failure_targets"][0]["target_path"] == "core/sample.py"
    assert analysis["coverage_targets"][0]["missing_line_ranges"] == ["10-12", "18"]


def test_code_manager_analyze_pytest_output_extracts_branch_arcs(tmp_path):
    manager = _manager(tmp_path)
    output = """
---------- coverage: platform linux, python 3.12 ----------
Name                Stmts   Miss  Cover   Missing
-------------------------------------------------
core/sample.py         20      4    80%   10-12, 18, 21->24, 30->exit
TOTAL                  25      4    84%
"""
    analysis = manager.analyze_pytest_output(output)

    assert analysis["coverage_targets"][0]["missing_line_ranges"] == ["10-12", "18"]
    assert analysis["coverage_targets"][0]["missing_branch_arcs"] == ["21->24", "30->exit"]


def test_code_manager_run_pytest_and_collect_uses_sandbox_runner(tmp_path, monkeypatch):
    manager = _manager(tmp_path)

    def _fake_run_shell_in_sandbox(command, cwd=None):
        assert command == "pytest -q"
        assert cwd == str(tmp_path)
        return True, "2 passed in 0.12s"

    monkeypatch.setattr(manager, "run_shell_in_sandbox", _fake_run_shell_in_sandbox)

    result = manager.run_pytest_and_collect("pytest -q", cwd=str(tmp_path))

    assert result["success"] is True
    assert result["command"] == "pytest -q"
    assert result["analysis"]["summary"].endswith("passed")


def test_code_manager_run_pytest_and_collect_rejects_non_pytest_commands(tmp_path):
    manager = _manager(tmp_path)

    result = manager.run_pytest_and_collect("python script.py", cwd=str(tmp_path))

    assert result["success"] is False
    assert result["command"] == "python script.py"
    assert "Yalnızca pytest komutları desteklenir" in result["output"]
    assert result["analysis"]["has_failures"] is False


def test_code_manager_write_generated_test_appends_idempotently(tmp_path):
    manager = _manager(tmp_path)
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")

    ok, msg = manager.write_generated_test(
        str(target),
        "```python\ndef test_generated():\n    assert 1 == 1\n```",
        append=True,
    )
    assert ok is True
    assert "kaydedildi" in msg.lower()
    text = target.read_text(encoding="utf-8")
    assert "def test_existing()" in text
    assert "def test_generated()" in text

    ok2, msg2 = manager.write_generated_test(str(target), "def test_generated():\n    assert 1 == 1\n", append=True)
    assert ok2 is True
    assert "zaten mevcut" in msg2.lower()


def test_code_manager_write_generated_test_handles_blank_and_read_failures(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")

    ok_blank, msg_blank = manager.write_generated_test(str(target), "```python\n```", append=True)
    assert ok_blank is False
    assert "boş" in msg_blank.lower()

    monkeypatch.setattr(manager, "read_file", lambda *_args, **_kwargs: (False, "okuma başarısız"))
    ok_read, msg_read = manager.write_generated_test(str(target), "def test_new():\n    assert True\n", append=True)
    assert ok_read is False
    assert msg_read == "okuma başarısız"


def test_code_manager_write_generated_test_writes_new_file_without_append(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    captured = {}

    def _fake_write_file(path, content, *, validate):
        captured.update({"path": path, "content": content, "validate": validate})
        return True, f"kaydedildi:{path}"

    monkeypatch.setattr(manager, "write_file", _fake_write_file)

    ok, msg = manager.write_generated_test(
        str(tmp_path / "tests" / "test_generated.py"),
        "```python\ndef test_new():\n    assert True\n```",
        append=False,
    )

    assert ok is True
    assert "kaydedildi" in msg
    assert captured["content"] == "def test_new():\n    assert True\n"
    assert captured["validate"] is True


def test_code_manager_analyze_pytest_output_extracts_failure_sections(tmp_path):
    manager = _manager(tmp_path)
    output = dedent(
        """
        ============================= test session starts =============================
        ___ test runtime timeout ___
        tests/test_runtime.py:55: PermissionError
        Traceback (most recent call last):
          File "tests/test_runtime.py", line 55, in test_runtime_timeout
            raise PermissionError("denied")
        PermissionError: denied
        =========================== short test summary info ============================
        1 failed in 0.33s
        """
    )
    analysis = manager.analyze_pytest_output(output)

    assert analysis["has_failures"] is True
    assert analysis["coverage_targets"] == []
    assert analysis["failure_targets"][0]["summary"] == "test runtime timeout"
    assert analysis["failure_targets"][0]["target_path"] == "tests/test_runtime.py"
    assert "PermissionError" in analysis["failure_targets"][0]["details"]


def test_code_manager_read_file_reports_missing_directory_and_permission_errors(tmp_path, monkeypatch):
    manager = _manager(tmp_path)

    missing = tmp_path / "missing.py"
    ok_missing, msg_missing = manager.read_file(str(missing))
    assert ok_missing is False
    assert "Dosya bulunamadı" in msg_missing

    folder = tmp_path / "pkg"
    folder.mkdir()
    ok_dir, msg_dir = manager.read_file(str(folder))
    assert ok_dir is False
    assert "bir dizin" in msg_dir

    blocked = tmp_path / "blocked.py"
    blocked.write_text("print('x')\n", encoding="utf-8")

    def _raise_permission(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(builtins, "open", _raise_permission)
    ok_perm, msg_perm = manager.read_file(str(blocked))
    assert ok_perm is False
    assert "Erişim reddedildi" in msg_perm


def test_code_manager_write_file_reports_permission_and_generic_failures(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    target = tmp_path / "tests" / "test_perm.py"

    def _raise_permission(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(CM_MOD.Path, "mkdir", _raise_permission)
    ok_perm, msg_perm = manager.write_file(str(target), "print('x')\n", validate=False)
    assert ok_perm is False
    assert "Yazma erişimi reddedildi" in msg_perm

    manager2 = _manager(tmp_path)

    def _raise_runtime(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(CM_MOD.Path, "mkdir", _raise_runtime)
    ok_runtime, msg_runtime = manager2.write_file(str(target), "print('x')\n", validate=False)
    assert ok_runtime is False
    assert "Yazma hatası" in msg_runtime
    assert "disk full" in msg_runtime


def test_code_manager_write_generated_test_handles_blank_existing_file_without_extra_separator(tmp_path):
    manager = _manager(tmp_path)
    target = tmp_path / "tests" / "test_empty.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("   \n", encoding="utf-8")

    ok, msg = manager.write_generated_test(str(target), "def test_generated():\n    assert True\n", append=True)

    assert ok is True
    assert "kaydedildi" in msg.lower()
    assert target.read_text(encoding="utf-8") == "def test_generated():\n    assert True\n"
