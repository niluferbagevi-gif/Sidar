from __future__ import annotations

from pathlib import Path

import pytest

from scripts.coverage_hotspots import format_table, parse_coverage_xml, rank_hotspots


def test_parse_and_rank_hotspots(tmp_path: Path) -> None:
    xml = """<?xml version=\"1.0\" ?>
<coverage>
  <packages>
    <package>
      <classes>
        <class filename=\"core/a.py\">
          <lines>
            <line number=\"1\" hits=\"1\"/>
            <line number=\"2\" hits=\"0\"/>
            <line number=\"3\" hits=\"0\"/>
          </lines>
        </class>
        <class filename=\"core/b.py\">
          <lines>
            <line number=\"1\" hits=\"1\"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""
    report = tmp_path / "coverage.xml"
    report.write_text(xml, encoding="utf-8")

    data = parse_coverage_xml(str(report), root=str(tmp_path))
    ranked = rank_hotspots(data, top=1)

    assert len(data) == 2
    assert ranked[0].path == "core/a.py"
    assert ranked[0].missed == 2
    assert ranked[0].coverage_pct == pytest.approx(100 / 3)


def test_format_table_renders_markdown(tmp_path: Path) -> None:
    xml = """<?xml version=\"1.0\" ?>
<coverage>
  <packages>
    <package>
      <classes>
        <class filename=\"web_server.py\">
          <lines>
            <line number=\"1\" hits=\"0\"/>
            <line number=\"2\" hits=\"1\"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""
    report = tmp_path / "coverage.xml"
    report.write_text(xml, encoding="utf-8")

    rows = rank_hotspots(parse_coverage_xml(str(report), root=str(tmp_path)), top=5)
    output = format_table(rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "web_server.py" in output
    assert "50.00%" in output
