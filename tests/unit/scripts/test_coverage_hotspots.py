from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from scripts.coverage_hotspots import (
    FileCoverage,
    _normalize_path,
    format_table,
    main,
    parse_coverage_xml,
    rank_hotspots,
)


def test_parse_and_rank_end_to_end(tmp_path):
    xml = tmp_path / "coverage.xml"
    xml.write_text(
        """<?xml version='1.0'?>
<coverage><packages><package><classes>
<class filename='a.py'><lines><line number='1' hits='0'/><line number='2' hits='1'/></lines></class>
<class filename='b.py'><lines><line number='1' hits='1'/></lines></class>
</classes></package></packages></coverage>
""",
        encoding="utf-8",
    )

    rows = parse_coverage_xml(str(xml), root=str(tmp_path))
    ranked = rank_hotspots(rows, top=1)

    assert len(rows) == 2
    assert ranked[0].path == "a.py"


def test_main_success_output(monkeypatch, capsys):
    rows = [FileCoverage(path="svc.py", covered=4, missed=1)]
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", "x.xml"])
    monkeypatch.setattr(
        "scripts.coverage_hotspots.parse_coverage_xml", lambda *args, **kwargs: rows
    )

    rc = main()
    output = capsys.readouterr().out

    assert rc == 0
    assert "svc.py" in output
    assert "80.00%" in output


def test_main_module_entrypoint_exits(monkeypatch, tmp_path):
    xml = tmp_path / "empty.xml"
    xml.write_text("<?xml version='1.0'?><coverage/>", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", str(xml)])
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "coverage_hotspots.py"

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(module_path), run_name="__main__")

    assert exc.value.code == 1


def test_format_table_layout():
    table = format_table([FileCoverage(path="x.py", covered=0, missed=2)])
    assert table.splitlines()[0] == "| File | Coverage | Missed | Covered |"


def test_filecoverage_zero_total_reports_full_coverage():
    row = FileCoverage(path="empty.py", covered=0, missed=0)

    assert row.total == 0
    assert row.coverage_pct == 100.0


def test_normalize_path_converts_absolute_path_under_root(tmp_path):
    root = tmp_path / "repo"
    module = root / "pkg" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text("# sample", encoding="utf-8")

    assert _normalize_path(str(module), str(root)) == "pkg/module.py"


def test_parse_coverage_xml_ignores_missing_or_empty_filename(tmp_path):
    xml = tmp_path / "coverage.xml"
    xml.write_text(
        """<?xml version='1.0'?>
<coverage><packages><package><classes>
<class><lines><line number='1' hits='1'/></lines></class>
<class filename=''><lines><line number='1' hits='0'/></lines></class>
<class filename='kept.py'><lines><line number='1' hits='1'/></lines></class>
</classes></package></packages></coverage>
""",
        encoding="utf-8",
    )

    rows = parse_coverage_xml(str(xml), root=str(tmp_path))

    assert [row.path for row in rows] == ["kept.py"]
    assert rows[0].covered == 1
    assert rows[0].missed == 0
