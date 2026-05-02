from __future__ import annotations

import runpy

import pytest

from scripts.coverage_hotspots import FileCoverage, format_table, main, parse_coverage_xml, rank_hotspots


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
    monkeypatch.setattr("scripts.coverage_hotspots.parse_coverage_xml", lambda *args, **kwargs: rows)

    rc = main()
    output = capsys.readouterr().out

    assert rc == 0
    assert "svc.py" in output
    assert "80.00%" in output


def test_main_module_entrypoint_exits(monkeypatch, tmp_path):
    xml = tmp_path / "empty.xml"
    xml.write_text("<?xml version='1.0'?><coverage/>", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", str(xml)])

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("scripts.coverage_hotspots", run_name="__main__")

    assert exc.value.code == 1


def test_format_table_layout():
    table = format_table([FileCoverage(path="x.py", covered=0, missed=2)])
    assert table.splitlines()[0] == "| File | Coverage | Missed | Covered |"
    