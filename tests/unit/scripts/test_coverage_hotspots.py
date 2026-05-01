from pathlib import Path

from scripts import coverage_hotspots as ch


def _write_xml(tmp_path: Path, body: str) -> Path:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(body, encoding="utf-8")
    return xml_path


def test_parse_coverage_xml_counts_hits_and_misses(tmp_path: Path) -> None:
    xml = _write_xml(
        tmp_path,
        """
<coverage>
  <packages>
    <package>
      <classes>
        <class filename="src/a.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="3" hits="2"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip(),
    )

    rows = ch.parse_coverage_xml(str(xml), root=str(tmp_path))
    assert len(rows) == 1
    assert rows[0].path == "src/a.py"
    assert rows[0].covered == 2
    assert rows[0].missed == 1


def test_parse_coverage_xml_skips_entries_without_filename(tmp_path: Path) -> None:
    xml = _write_xml(
        tmp_path,
        """
<coverage>
  <packages>
    <package>
      <classes>
        <class>
          <lines>
            <line number="1" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip(),
    )
    assert ch.parse_coverage_xml(str(xml), root=str(tmp_path)) == []


def test_rank_hotspots_orders_by_missed_then_coverage() -> None:
    rows = [
        ch.FileCoverage(path="a.py", covered=10, missed=2),
        ch.FileCoverage(path="b.py", covered=5, missed=5),
        ch.FileCoverage(path="c.py", covered=1, missed=5),
    ]
    ranked = ch.rank_hotspots(rows, top=2)
    assert [r.path for r in ranked] == ["c.py", "b.py"]


def test_format_table_renders_markdown() -> None:
    out = ch.format_table([ch.FileCoverage(path="src/a.py", covered=4, missed=1)])
    assert "| File | Coverage | Missed | Covered |" in out
    assert "| src/a.py | 80.00% | 1 | 4 |" in out


def test_main_returns_1_when_no_files(monkeypatch) -> None:
    monkeypatch.setattr(ch, "parse_coverage_xml", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", "none.xml"])
    assert ch.main() == 1


def test_main_prints_ranked_table_and_returns_0(monkeypatch, capsys) -> None:
    rows = [
        ch.FileCoverage(path="src/a.py", covered=8, missed=2),
        ch.FileCoverage(path="src/b.py", covered=2, missed=8),
    ]
    monkeypatch.setattr(ch, "parse_coverage_xml", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr("sys.argv", ["coverage_hotspots.py", "--xml", "cov.xml", "--top", "1"])

    rc = ch.main()
    captured = capsys.readouterr().out

    assert rc == 0
    assert "src/b.py" in captured
    assert "src/a.py" not in captured
