from __future__ import annotations

import json
from pathlib import Path

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


def test_ratchet_coverage_gate_updates_coveragerc_preserving_comments(tmp_path: Path) -> None:
    coveragerc = tmp_path / ".coveragerc"
    coverage_json = tmp_path / "coverage.json"
    coveragerc.write_text(
        "[run]\nbranch = True\n\n[report]\nfail_under = 5\nshow_missing = True\n",
        encoding="utf-8",
    )
    _write_coverage_json(coverage_json, 23.7)

    result = ratchet_coverage_gate(coveragerc_path=coveragerc, coverage_json_path=coverage_json)

    assert result.updated is True
    assert result.current_gate == 5
    assert result.target_gate == 20
    assert read_fail_under(coveragerc) == 20
    assert "show_missing = True" in coveragerc.read_text(encoding="utf-8")


def test_ratchet_coverage_gate_leaves_gate_when_not_improved(tmp_path: Path) -> None:
    coveragerc = tmp_path / ".coveragerc"
    coverage_json = tmp_path / "coverage.json"
    coveragerc.write_text("[report]\nfail_under = 30\n", encoding="utf-8")
    _write_coverage_json(coverage_json, 31.1)

    result = ratchet_coverage_gate(coveragerc_path=coveragerc, coverage_json_path=coverage_json)

    assert result.updated is False
    assert result.target_gate == 30
    assert read_fail_under(coveragerc) == 30
