from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.code_manager import CodeManager


def _manager_for_generation(tmp_path: Path) -> CodeManager:
    manager = CodeManager.__new__(CodeManager)
    manager.base_dir = tmp_path
    manager.security = SimpleNamespace()
    manager._lock = None
    return manager


def test_write_generated_test_strips_markdown_and_writes_new_file(tmp_path: Path) -> None:
    manager = _manager_for_generation(tmp_path)

    captured: dict[str, object] = {}

    def _fake_write(path: str, content: str, validate: bool = True):
        captured["path"] = path
        captured["content"] = content
        captured["validate"] = validate
        return True, "ok"

    manager.write_file = _fake_write  # type: ignore[method-assign]

    ok, message = manager.write_generated_test(
        "tests/test_generated_example.py",
        "```python\ndef test_sample():\n    assert 1 == 1\n```",
        append=False,
    )

    assert ok is True
    assert message == "ok"
    assert captured["path"] == "tests/test_generated_example.py"
    assert captured["validate"] is True
    assert captured["content"] == "def test_sample():\n    assert 1 == 1\n"


def test_write_generated_test_is_idempotent_when_same_content_exists(tmp_path: Path) -> None:
    manager = _manager_for_generation(tmp_path)
    target = tmp_path / "tests" / "test_same.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_a():\n    assert True\n", encoding="utf-8")

    manager.read_file = lambda _path, line_numbers=False: (True, target.read_text(encoding="utf-8"))  # type: ignore[method-assign]

    def _should_not_write(*_args, **_kwargs):
        raise AssertionError("write_file should not be called for duplicate content")

    manager.write_file = _should_not_write  # type: ignore[method-assign]

    ok, message = manager.write_generated_test(str(target), "def test_a():\n    assert True", append=True)

    assert ok is True
    assert "zaten mevcut" in message


def test_analyze_pytest_output_extracts_coverage_and_failures() -> None:
    output = """
FAILED tests/test_sample.py::test_value - assert 1 == 2

core/llm_client.py  100  30  70%  10-12, 40->45
tests/test_sample.py  20  0 100%  -
TOTAL 120 30 75% -

___________ test_value ___________
E       AssertionError: boom
core/llm_client.py:123: AssertionError
================= 1 failed, 3 passed in 0.10s =================
"""

    analysis = CodeManager.analyze_pytest_output(output)

    assert analysis["has_coverage_gaps"] is True
    assert analysis["has_failures"] is True
    assert analysis["summary"] == "1 failed"
    assert analysis["coverage_targets"][0]["target_path"] == "core/llm_client.py"
    assert analysis["coverage_targets"][0]["missing_line_ranges"] == ["10-12"]
    assert analysis["coverage_targets"][0]["missing_branch_arcs"] == ["40->45"]
    assert analysis["failure_targets"][0]["target_path"] == "core/llm_client.py"


def test_run_pytest_and_collect_rejects_non_pytest_command(tmp_path: Path) -> None:
    manager = _manager_for_generation(tmp_path)

    result = manager.run_pytest_and_collect("python script.py")

    assert result["success"] is False
    assert "Yalnızca pytest" in result["output"]
    assert result["analysis"]["has_failures"] is False


def test_run_pytest_and_collect_calls_sandbox_and_analysis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _manager_for_generation(tmp_path)

    monkeypatch.setattr(
        manager,
        "run_shell_in_sandbox",
        lambda command, cwd=None: (False, "core/db.py 10 2 80% 4-5\n1 failed"),
    )

    result = manager.run_pytest_and_collect("pytest -q", cwd=str(tmp_path))

    assert result["command"] == "pytest -q"
    assert result["success"] is False
    assert result["analysis"]["has_coverage_gaps"] is True
