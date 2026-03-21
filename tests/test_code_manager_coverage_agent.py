from pathlib import Path

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
