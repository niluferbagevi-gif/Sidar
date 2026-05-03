from pathlib import Path

from autonomous_loop import read_coverage_percent, read_junit_failures, should_heal


def test_read_coverage_percent(tmp_path: Path) -> None:
    coverage_file = tmp_path / "coverage.json"
    coverage_file.write_text('{"totals": {"percent_covered": 100.0}}', encoding="utf-8")

    assert read_coverage_percent(coverage_file) == 100.0


def test_read_junit_failures_from_testsuites(tmp_path: Path) -> None:
    junit_file = tmp_path / "results.xml"
    junit_file.write_text(
        '<testsuites><testsuite tests="4" failures="1" errors="0"/></testsuites>',
        encoding="utf-8",
    )

    assert read_junit_failures(junit_file) == (4, 1)


def test_should_heal_for_non_100_coverage() -> None:
    assert should_heal(99.9, (10, 0), 0) is True
    assert should_heal(100.0, (10, 0), 0) is False
