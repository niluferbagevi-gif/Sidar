"""Tests for hotspot coverage gate helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_hotspot_gate import check_hotspots, parse_coverage_xml


pytestmark = pytest.mark.quality_gate


COVERAGE_XML_SAMPLE = """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class filename="memory_hub.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
          </lines>
        </class>
        <class filename="jira_manager.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def test_parse_coverage_xml_extracts_percentages(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(COVERAGE_XML_SAMPLE, encoding="utf-8")

    data = parse_coverage_xml(xml_path)
    assert data["pkg/memory_hub.py"].pct == 100.0
    assert data["pkg/jira_manager.py"].pct == 50.0


def test_check_hotspots_reports_min_and_ratchet_failures(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(COVERAGE_XML_SAMPLE, encoding="utf-8")
    data = parse_coverage_xml(xml_path)

    config = {
        "hotspots": [
            {"path": "pkg/memory_hub.py", "min_coverage": 95.0, "ratchet_coverage": 100.0},
            {"path": "pkg/jira_manager.py", "min_coverage": 80.0, "ratchet_coverage": 90.0},
        ]
    }
    errors = check_hotspots(data, config)
    assert len(errors) == 2
    assert "min 80.00%" in errors[0]
    assert "ratchet 90.00%" in errors[1]


def test_hotspot_config_file_is_valid_json() -> None:
    config_path = Path(".ci/backend_hotspot_gate.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert "hotspots" in data
    assert len(data["hotspots"]) >= 1


def test_check_hotspots_resolves_prefixed_path_with_suffix_fallback(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(COVERAGE_XML_SAMPLE, encoding="utf-8")
    data = parse_coverage_xml(xml_path)

    config = {
        "hotspots": [
            {"path": "agent/pkg/jira_manager.py", "min_coverage": 40.0, "ratchet_coverage": 50.0},
        ]
    }
    errors = check_hotspots(data, config)
    assert errors == []
