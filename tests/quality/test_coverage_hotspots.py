"""Quality gate tests for coverage hotspot analysis utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.coverage_hotspots import format_table, parse_coverage_xml, rank_hotspots


pytestmark = pytest.mark.quality_gate


COVERAGE_XML_SAMPLE = """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class filename="core/rag.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="3" hits="0"/>
          </lines>
        </class>
        <class filename="core/db.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


@pytest.fixture
def sample_coverage_xml(tmp_path: Path) -> str:
    """Write sample coverage XML and return its file path."""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(COVERAGE_XML_SAMPLE, encoding="utf-8")
    return str(xml_path)


def test_parse_coverage_xml_extracts_counts(sample_coverage_xml: str, tmp_path: Path) -> None:
    """Parser should extract covered/missed counts per file."""
    rows = parse_coverage_xml(sample_coverage_xml, root=str(tmp_path))

    assert len(rows) == 2
    by_path = {row.path: row for row in rows}
    assert by_path["core/rag.py"].covered == 1
    assert by_path["core/rag.py"].missed == 2
    assert by_path["core/db.py"].covered == 3
    assert by_path["core/db.py"].missed == 0


def test_rank_hotspots_prioritizes_most_missed(sample_coverage_xml: str, tmp_path: Path) -> None:
    """Hotspot ranking should prioritize files with higher missed line counts."""
    rows = parse_coverage_xml(sample_coverage_xml, root=str(tmp_path))
    ranked = rank_hotspots(rows, top=1)

    assert len(ranked) == 1
    assert ranked[0].path == "core/rag.py"


def test_format_table_outputs_markdown_headers(sample_coverage_xml: str, tmp_path: Path) -> None:
    """Formatter should emit a compact markdown table consumable by CI reports."""
    rows = rank_hotspots(parse_coverage_xml(sample_coverage_xml, root=str(tmp_path)), top=2)
    table = format_table(rows)

    assert "| File | Coverage | Missed | Covered |" in table
    assert "core/rag.py" in table
    assert "core/db.py" in table
