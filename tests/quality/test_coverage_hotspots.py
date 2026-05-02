"""Quality gate tests for coverage hotspot analysis utilities."""

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


def test_filecoverage_returns_full_percent_when_total_is_zero() -> None:
    """Coverage percentage should be 100 when covered+missed is zero."""
    row = FileCoverage(path="empty.py", covered=0, missed=0)

    assert row.total == 0
    assert row.coverage_pct == 100.0


def test_normalize_path_converts_absolute_to_relative(tmp_path: Path) -> None:
    """Absolute file paths should be normalized relative to root."""
    root = tmp_path / "repo"
    abs_file = root / "pkg" / "module.py"
    abs_file.parent.mkdir(parents=True)
    abs_file.write_text("# sample", encoding="utf-8")

    rel = _normalize_path(str(abs_file), str(root))

    assert rel == "pkg/module.py"


def test_parse_coverage_xml_skips_class_without_filename(tmp_path: Path) -> None:
    """Classes without a filename attribute should be ignored."""
    xml_path = tmp_path / "coverage_missing_filename.xml"
    xml_path.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class>
          <lines>
            <line number="1" hits="1"/>
          </lines>
        </class>
        <class filename="">
          <lines>
            <line number="1" hits="0"/>
          </lines>
        </class>
        <class filename="valid.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    rows = parse_coverage_xml(str(xml_path), root=str(tmp_path))

    assert len(rows) == 1
    assert rows[0].path == "valid.py"
    assert rows[0].covered == 1
    assert rows[0].missed == 1


def test_main_returns_1_and_message_when_no_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI should return 1 with a user-facing message when coverage XML has no class files."""
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", "empty.xml"])
    monkeypatch.setattr("scripts.coverage_hotspots.parse_coverage_xml", lambda *args, **kwargs: [])

    rc = main()
    out = capsys.readouterr().out

    assert rc == 1
    assert "No files were found in coverage XML." in out


def test_main_prints_ranked_table_and_returns_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI should parse args, rank rows, and print markdown table for non-empty data."""
    rows = [
        FileCoverage(path="a.py", covered=1, missed=2),
        FileCoverage(path="b.py", covered=5, missed=0),
    ]
    monkeypatch.setattr(
        "sys.argv",
        ["coverage_hotspots.py", "--xml", "custom.xml", "--top", "1", "--root", "/tmp/proj"],
    )
    monkeypatch.setattr("scripts.coverage_hotspots.parse_coverage_xml", lambda xml, root: rows)

    rc = main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "| File | Coverage | Missed | Covered |" in out
    assert "a.py" in out
    assert "b.py" not in out




def test_normalize_path_keeps_relative_path_unchanged() -> None:
    """Relative file paths should pass through unchanged."""
    rel = _normalize_path("pkg/module.py", "/tmp/repo")

    assert rel == "pkg/module.py"


def test_parse_coverage_xml_handles_missing_lines_and_default_hits(tmp_path: Path) -> None:
    """Parser should treat missing hits as 0 and classes without lines as zero totals."""
    xml_path = tmp_path / "coverage_sparse.xml"
    xml_path.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class filename="sparse.py">
          <lines>
            <line number="1"/>
            <line number="2" hits="2"/>
          </lines>
        </class>
        <class filename="nolines.py"/>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    rows = parse_coverage_xml(str(xml_path), root=str(tmp_path))
    by_path = {row.path: row for row in rows}

    assert by_path["sparse.py"].covered == 1
    assert by_path["sparse.py"].missed == 1
    assert by_path["nolines.py"].covered == 0
    assert by_path["nolines.py"].missed == 0
def test_module_main_guard_raises_system_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Running module as a script should execute main() via __main__ guard."""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text('<?xml version="1.0" ?><coverage></coverage>', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", str(xml_path)])

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("scripts.coverage_hotspots", run_name="__main__")

    assert exc.value.code == 1
