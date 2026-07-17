"""Tests for the Ruff docstring and ASYNC240 debt baseline checker."""

from __future__ import annotations

from scripts.ci import check_ruff_debt_baseline as checker


def _pyproject_with_baselines(*, e501: int, d202: int, async240: int = 0) -> str:
    return (
        "[tool.sidar.ruff_debt]\n"
        f"e501_debt_baseline = {e501}\n"
        "docstring_async_debt_baseline = { "
        f"D200 = 0, D202 = {d202}, D205 = 0, D209 = 0, "
        "D212 = 0, D403 = 0, D415 = 0, D417 = 0, "
        f"ASYNC240 = {async240} "
        "}\n"
    )


def test_count_diagnostics_fills_missing_debt_codes_with_zero() -> None:
    """Diagnostic counts include every tracked code even when Ruff omits a rule."""
    counts = checker._count_diagnostics(
        [
            {"code": "D200"},
            {"code": "D200"},
            {"code": "ASYNC240"},
            {"code": "F401"},
        ]
    )

    assert counts["D200"] == 2
    assert counts["ASYNC240"] == 1
    assert counts["D417"] == 0
    assert "F401" not in counts


def test_format_counts_uses_stable_campaign_code_order() -> None:
    """Formatted CI output keeps the campaign rule order deterministic."""
    rendered = checker._format_counts({"E501": 4, "D200": 1, "D202": 2, "ASYNC240": 3})

    assert rendered.startswith("E501=4, D200=1, D202=2, D205=0")
    assert rendered.endswith("D417=0, ASYNC240=3")


def test_tightenable_counts_detects_lower_current_debt() -> None:
    current = {code: 0 for code in checker.RUFF_DEBT_CODES}
    baseline = {code: 0 for code in checker.RUFF_DEBT_CODES}
    current["E501"] = 4
    baseline["E501"] = 6
    current["D202"] = 2
    baseline["D202"] = 3

    assert checker._tightenable_counts(current, baseline) == {
        "E501": (4, 6),
        "D202": (2, 3),
    }


def test_write_tightened_baseline_uses_minimum_current_values(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject_with_baselines(e501=10, d202=20, async240=3), encoding="utf-8")
    current = {
        "E501": 7,
        "D200": 6,
        "D202": 12,
        "D205": 8,
        "D209": 1,
        "D212": 11,
        "D403": 1,
        "D415": 5,
        "D417": 1,
        "ASYNC240": 2,
    }
    baseline = checker._load_baseline(pyproject)

    checker._write_tightened_baseline(pyproject, current, baseline)

    updated = checker._load_baseline(pyproject)
    assert updated["E501"] == 7
    assert updated["D202"] == 12
    assert updated["ASYNC240"] == 2
    assert updated["D200"] == 0


def test_main_fails_when_baseline_can_be_tightened(tmp_path, monkeypatch, capsys) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject_with_baselines(e501=6, d202=3), encoding="utf-8")
    diagnostics = [{"code": "E501"} for _ in range(4)] + [{"code": "D202"} for _ in range(2)]
    monkeypatch.setattr(checker, "_run_ruff_json", lambda _codes: diagnostics)

    assert checker.main(["--pyproject", str(pyproject)]) == 1

    captured = capsys.readouterr()
    assert "baseline can be tightened" in captured.err
    assert "--update" in captured.err


def test_main_update_ratchets_pyproject_to_current_counts(tmp_path, monkeypatch, capsys) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject_with_baselines(e501=6, d202=3), encoding="utf-8")
    diagnostics = [{"code": "E501"} for _ in range(4)] + [{"code": "D202"} for _ in range(2)]
    monkeypatch.setattr(checker, "_run_ruff_json", lambda _codes: diagnostics)

    assert checker.main(["--pyproject", str(pyproject), "--update"]) == 0

    updated = checker._load_baseline(pyproject)
    assert updated["E501"] == 4
    assert updated["D202"] == 2
    assert "ratcheted" in capsys.readouterr().out
