from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.check_coverage_exclusion_budget import collect_exclusions, main


def _write_baseline(path: Path, maximum: int) -> None:
    path.write_text(json.dumps({"maximum_production_exclusions": maximum}), encoding="utf-8")


def test_collect_exclusions_ignores_tests_and_omitted_directories(tmp_path: Path) -> None:
    (tmp_path / "core.py").write_text("value = 1  # pragma: no cover\n", encoding="utf-8")
    for directory in ("tests", "migrations", "web_ui_react"):
        path = tmp_path / directory
        path.mkdir()
        (path / "ignored.py").write_text("value = 1  # pragma: no cover\n", encoding="utf-8")

    assert collect_exclusions(tmp_path) == {"core.py": 1}


def test_exclusion_budget_is_one_way_and_fails_closed(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    source = tmp_path / "core.py"
    source.write_text("a = 1  # pragma: no cover\nb = 2  # pragma: no cover\n", encoding="utf-8")
    _write_baseline(baseline, 2)

    assert main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 0

    source.write_text(source.read_text(encoding="utf-8") + "c = 3  # pragma: no cover\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 1


def test_exclusion_budget_rejects_invalid_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    assert main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 2
