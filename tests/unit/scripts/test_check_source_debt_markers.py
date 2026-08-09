"""Tests for the production-source debt marker quality gate."""

from __future__ import annotations

from scripts.ci import check_source_debt_markers as checker


def test_finds_python_and_typescript_comment_markers_without_matching_strings(tmp_path) -> None:
    """Only comment markers represent unresolved source debt."""
    (tmp_path / "core").mkdir()
    (tmp_path / "web_ui_react" / "src").mkdir(parents=True)
    (tmp_path / "core" / "sample.py").write_text(
        'label = "TODO is user-visible text"\n# FIXME: repair branch\n', encoding="utf-8"
    )
    (tmp_path / "web_ui_react" / "src" / "sample.ts").write_text(
        "// HACK: remove workaround\nexport const value = 1;\n", encoding="utf-8"
    )

    findings = checker.find_debt_markers(tmp_path)

    assert [(item.path, item.line) for item in findings] == [
        ("core/sample.py", 2),
        ("web_ui_react/src/sample.ts", 1),
    ]


def test_allows_todo_manager_scanner_explanation(tmp_path) -> None:
    """The scanner's explanatory comment is intentional, not deferred work."""
    manager_dir = tmp_path / "managers"
    manager_dir.mkdir()
    (manager_dir / "todo_manager.py").write_text(
        "# TODO veya FIXME kelimesini içeren satırları yakala\n", encoding="utf-8"
    )

    assert checker.find_debt_markers(tmp_path) == []


def test_main_fails_closed_and_reports_location(tmp_path, capsys) -> None:
    """CLI output identifies every marker that blocks the gate."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "worker.py").write_text("# TODO: finish worker\n", encoding="utf-8")

    assert checker.main(["--root", str(tmp_path)]) == 1
    assert "agent/worker.py:1" in capsys.readouterr().err
