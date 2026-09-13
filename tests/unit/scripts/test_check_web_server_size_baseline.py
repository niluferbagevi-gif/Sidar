"""Tests for the web_server.py size-ratchet checker."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci import check_web_server_size_baseline as checker


def _write_baseline(path: Path, maximum: object) -> None:
    path.write_text(json.dumps({"maximum_lines": maximum}), encoding="utf-8")


def test_count_lines_returns_zero_for_missing_file(tmp_path: Path) -> None:
    assert checker.count_lines(tmp_path / "missing.py") == 0


def test_count_lines_counts_source_lines(tmp_path: Path) -> None:
    target = tmp_path / "web_server.py"
    target.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

    assert checker.count_lines(target) == 3


def test_size_budget_passes_at_or_below_maximum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    target = tmp_path / "web_server.py"
    target.write_text("a = 1\nb = 2\n", encoding="utf-8")
    _write_baseline(baseline, 2)

    assert checker.main(["--target", str(target), "--baseline", str(baseline)]) == 0


def test_size_budget_is_one_way_and_fails_closed(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    target = tmp_path / "web_server.py"
    target.write_text("a = 1\nb = 2\n", encoding="utf-8")
    _write_baseline(baseline, 2)

    assert checker.main(["--target", str(target), "--baseline", str(baseline)]) == 0

    target.write_text(target.read_text(encoding="utf-8") + "c = 3\n", encoding="utf-8")
    assert checker.main(["--target", str(target), "--baseline", str(baseline)]) == 1


def test_size_budget_rejects_missing_baseline_key(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_size_budget_rejects_invalid_json(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("not json", encoding="utf-8")

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_size_budget_rejects_negative_maximum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, -1)

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_size_budget_rejects_bool_maximum(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, True)

    assert checker.main(["--baseline", str(baseline)]) == 2


def test_committed_baseline_matches_real_web_server_line_count() -> None:
    """The committed baseline must never lag behind (or exceed) reality unnoticed."""
    baseline = json.loads(checker.DEFAULT_BASELINE.read_text(encoding="utf-8"))
    maximum = baseline["maximum_lines"]
    actual = checker.count_lines(checker.TARGET_PATH)

    assert actual <= maximum, (
        f"web_server.py has grown to {actual} lines, past the committed budget of "
        f"{maximum}; move new logic into web/routes/* instead of raising this baseline"
    )
    assert checker.main([]) == 0
