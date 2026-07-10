from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.coverage_ratchet import (
    compute_next_gate,
    ratchet_coverage_gate,
    read_fail_under,
)


def _write_coverage_json(path: Path, percent: float) -> None:
    path.write_text(json.dumps({"totals": {"percent_covered": percent}}), encoding="utf-8")


def test_compute_next_gate_raises_to_reached_step_without_overshooting() -> None:
    assert compute_next_gate(12.4, 5, step=5, min_gate=5) == 10
    assert compute_next_gate(15.0, 10, step=5, min_gate=5) == 15


def test_compute_next_gate_never_decreases_existing_gate() -> None:
    assert compute_next_gate(84.9, 90, step=5, min_gate=5) == 90


def test_default_one_percent_step_promotes_high_coverage_without_exact_lock() -> None:
    assert compute_next_gate(99.04, 95, min_gate=5) == 99


def test_coarse_five_percent_step_keeps_gate_at_reached_floor() -> None:
    assert compute_next_gate(99.04, 95, step=5, min_gate=5) == 95


def test_hundredth_percent_step_locks_to_measured_coverage() -> None:
    assert compute_next_gate(99.04, 95, step=0.01, min_gate=5) == 99.04


def test_ratchet_coverage_gate_updates_coverage_config_preserving_comments(tmp_path: Path) -> None:
    coverage_config = tmp_path / "pyproject.toml"
    coverage_json = tmp_path / "coverage.json"
    coverage_config.write_text(
        "[tool.coverage.run]\nbranch = true\n\n[tool.coverage.report]\nfail_under = 5\nshow_missing = true\n",
        encoding="utf-8",
    )
    _write_coverage_json(coverage_json, 23.7)

    result = ratchet_coverage_gate(
        coverage_config_path=coverage_config, coverage_json_path=coverage_json
    )

    assert result.updated is True
    assert result.current_gate == 5
    assert result.target_gate == 23
    assert read_fail_under(coverage_config) == 23
    assert "show_missing = true" in coverage_config.read_text(encoding="utf-8")


def test_ratchet_coverage_gate_leaves_gate_when_next_one_percent_step_not_reached(
    tmp_path: Path,
) -> None:
    coverage_config = tmp_path / "pyproject.toml"
    coverage_json = tmp_path / "coverage.json"
    coverage_config.write_text("[tool.coverage.report]\nfail_under = 30\n", encoding="utf-8")
    _write_coverage_json(coverage_json, 30.9)

    result = ratchet_coverage_gate(
        coverage_config_path=coverage_config, coverage_json_path=coverage_json
    )

    assert result.updated is False
    assert result.target_gate == 30
    assert read_fail_under(coverage_config) == 30


def test_parse_percentage_rejects_invalid_and_clamps() -> None:
    from scripts.coverage_ratchet import _parse_percentage

    assert _parse_percentage("150%", field_name="x") == 100.0
    for value in (None, "not-a-number", float("inf"), -0.1):
        with pytest.raises(ValueError):
            _parse_percentage(value, field_name="x")


def test_read_total_coverage_validates_totals_and_display_fallback(tmp_path: Path) -> None:
    from scripts.coverage_ratchet import read_total_coverage

    coverage_json = tmp_path / "coverage.json"
    coverage_json.write_text(
        json.dumps({"totals": {"percent_covered_display": "42.50"}}), encoding="utf-8"
    )
    assert read_total_coverage(coverage_json) == 42.5

    coverage_json.write_text(json.dumps({"totals": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="totals alanı"):
        read_total_coverage(coverage_json)

    coverage_json.write_text(json.dumps({"totals": {"covered_lines": 1}}), encoding="utf-8")
    with pytest.raises(ValueError, match="percent_covered"):
        read_total_coverage(coverage_json)


def test_compute_next_gate_validates_step_and_gate_order() -> None:
    with pytest.raises(ValueError, match="step"):
        compute_next_gate(10, 5, step=0)
    with pytest.raises(ValueError, match="min_gate"):
        compute_next_gate(10, 5, min_gate=90, max_gate=80)
    assert compute_next_gate(99.9, 95, step=0.5, max_gate=99) == 99


def test_write_fail_under_inserts_into_existing_and_missing_report_sections(tmp_path: Path) -> None:
    from scripts.coverage_ratchet import write_fail_under

    coverage_config = tmp_path / "pyproject.toml"
    coverage_config.write_text(
        "[tool.coverage.report]\nshow_missing = true\n"
        '[tool.coverage.html]\ndirectory = "htmlcov"\n',
        encoding="utf-8",
    )
    write_fail_under(coverage_config, 12.5)
    assert "fail_under = 12.5\n[tool.coverage.html]" in coverage_config.read_text(encoding="utf-8")

    coverage_config.write_text("[tool.coverage.run]\nbranch = true", encoding="utf-8")
    write_fail_under(coverage_config, 7)
    assert coverage_config.read_text(encoding="utf-8").endswith(
        "\n[tool.coverage.report]\nfail_under = 7\n"
    )


def test_main_prints_updated_and_unchanged_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.coverage_ratchet import main

    coverage_config = tmp_path / "pyproject.toml"
    coverage_json = tmp_path / "coverage.json"
    coverage_config.write_text("[tool.coverage.report]\nfail_under = 5\n", encoding="utf-8")
    _write_coverage_json(coverage_json, 10.1)

    assert (
        main(["--coverage-config", str(coverage_config), "--coverage-json", str(coverage_json)])
        == 0
    )
    assert "Coverage gate ratcheted" in capsys.readouterr().out

    assert (
        main(["--coverage-config", str(coverage_config), "--coverage-json", str(coverage_json)])
        == 0
    )
    assert "Coverage gate unchanged" in capsys.readouterr().out


def test_write_fail_under_appends_to_report_at_end(tmp_path: Path) -> None:
    from scripts.coverage_ratchet import write_fail_under

    coverage_config = tmp_path / "pyproject.toml"
    coverage_config.write_text(
        "[tool.coverage.run]\nbranch = true\n\n[tool.coverage.report]\n", encoding="utf-8"
    )
    write_fail_under(coverage_config, 8)
    assert coverage_config.read_text(encoding="utf-8").endswith(
        "[tool.coverage.report]\nfail_under = 8\n"
    )


def test_write_fail_under_adds_missing_report_after_newline_terminated_file(tmp_path: Path) -> None:
    from scripts.coverage_ratchet import write_fail_under

    coverage_config = tmp_path / "pyproject.toml"
    coverage_config.write_text("[tool.coverage.run]\nbranch = true\n", encoding="utf-8")
    write_fail_under(coverage_config, 9)
    assert "\n[tool.coverage.report]\nfail_under = 9\n" in coverage_config.read_text(
        encoding="utf-8"
    )


def test_ensure_html_dark_mode_css_adds_missing_html_section(tmp_path: Path) -> None:
    from scripts.coverage_ratchet import ensure_html_dark_mode_css

    coverage_config = tmp_path / "pyproject.toml"
    coverage_config.write_text("[tool.coverage.report]\nfail_under = 5\n", encoding="utf-8")

    changed = ensure_html_dark_mode_css(coverage_config)

    assert changed is True
    content = coverage_config.read_text(encoding="utf-8")
    assert "[tool.coverage.html]" in content
    assert 'extra_css = "assets/dark_mode.css"' in content


def test_ratchet_coverage_gate_enforces_dark_mode_css(tmp_path: Path) -> None:
    coverage_config = tmp_path / "pyproject.toml"
    coverage_json = tmp_path / "coverage.json"
    coverage_config.write_text(
        '[tool.coverage.report]\nfail_under = 5\n[tool.coverage.html]\ndirectory = "htmlcov"\n',
        encoding="utf-8",
    )
    _write_coverage_json(coverage_json, 6.2)

    ratchet_coverage_gate(coverage_config_path=coverage_config, coverage_json_path=coverage_json)

    assert 'extra_css = "assets/dark_mode.css"' in coverage_config.read_text(encoding="utf-8")


def test_ninety_nine_gate_does_not_require_hundred_until_measurement_reaches_it() -> None:
    assert compute_next_gate(99.58, 99, step=1, min_gate=5, max_gate=100) == 99
    assert compute_next_gate(100.0, 99, step=1, min_gate=5, max_gate=100) == 100


def test_daily_cap_keeps_ninety_nine_gate_even_with_hundred_percent_measurement() -> None:
    assert compute_next_gate(98.42, 99, step=1, min_gate=5, max_gate=99) == 99
    assert compute_next_gate(100.0, 99, step=1, min_gate=5, max_gate=99) == 99


def test_campaign_cap_can_opt_in_to_hundred_percent_gate() -> None:
    assert compute_next_gate(100.0, 99, step=1, min_gate=5, max_gate=100) == 100
