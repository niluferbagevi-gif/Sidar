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
        <class filename="agent/core/memory_hub.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
          </lines>
        </class>
        <class filename="managers/jira_manager.py">
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
    assert data["agent/core/memory_hub.py"].pct == 100.0
    assert data["managers/jira_manager.py"].pct == 50.0


def test_parse_coverage_xml_uses_package_name_for_bare_filenames(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="agent.core">
      <classes>
        <class filename="__init__.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
    <package name="core">
      <classes>
        <class filename="__init__.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    data = parse_coverage_xml(xml_path)

    assert data["agent/core/__init__.py"].pct == 50.0
    assert data["core/__init__.py"].pct == 100.0


def test_check_hotspots_reports_min_and_ratchet_failures(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(COVERAGE_XML_SAMPLE, encoding="utf-8")
    data = parse_coverage_xml(xml_path)

    config = {
        "hotspots": [
            {"path": "agent/core/memory_hub.py", "min_coverage": 95.0, "ratchet_coverage": 100.0},
            {"path": "managers/jira_manager.py", "min_coverage": 80.0, "ratchet_coverage": 90.0},
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
