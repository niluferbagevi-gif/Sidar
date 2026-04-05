#!/usr/bin/env python3
"""Fail CI when backend coverage hotspots regress below agreed thresholds."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass
class FileCoverage:
    covered: int
    missed: int

    @property
    def total(self) -> int:
        return self.covered + self.missed

    @property
    def pct(self) -> float:
        total = self.total
        if total == 0:
            return 100.0
        return (self.covered / total) * 100


def parse_coverage_xml(xml_path: Path) -> dict[str, FileCoverage]:
    tree = ET.parse(xml_path)
    xml_root = tree.getroot()
    files: dict[str, FileCoverage] = {}

    for cls in xml_root.findall(".//class"):
        filename = cls.attrib.get("filename")
        if not filename:
            continue

        covered = 0
        missed = 0
        for line in cls.findall("./lines/line"):
            if int(line.attrib.get("hits", "0")) > 0:
                covered += 1
            else:
                missed += 1
        files[filename] = FileCoverage(covered=covered, missed=missed)

    return files


def check_hotspots(
    current: dict[str, FileCoverage],
    config: dict[str, list[dict[str, float | str]]],
) -> list[str]:
    errors: list[str] = []
    for hotspot in config.get("hotspots", []):
        path = str(hotspot["path"])
        min_coverage = float(hotspot.get("min_coverage", 0.0))
        ratchet_coverage = float(hotspot.get("ratchet_coverage", min_coverage))

        record = current.get(path)
        if record is None:
            errors.append(f"{path}: coverage.xml içinde bulunamadı.")
            continue

        pct = record.pct
        if pct < min_coverage:
            errors.append(f"{path}: coverage {pct:.2f}% < min {min_coverage:.2f}%")
        if pct < ratchet_coverage:
            errors.append(f"{path}: coverage {pct:.2f}% < ratchet {ratchet_coverage:.2f}%")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Backend hotspot coverage gate")
    parser.add_argument("--xml", default="coverage.xml", help="coverage.xml path")
    parser.add_argument(
        "--config",
        default=".ci/backend_hotspot_gate.json",
        help="Hotspot policy JSON path",
    )
    args = parser.parse_args()

    xml_path = Path(args.xml)
    config_path = Path(args.config)

    if not xml_path.exists():
        print(f"❌ coverage report bulunamadı: {xml_path}")
        return 1
    if not config_path.exists():
        print(f"❌ hotspot config bulunamadı: {config_path}")
        return 1

    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    coverage_map = parse_coverage_xml(xml_path)
    errors = check_hotspots(coverage_map, config)

    if errors:
        print("❌ Hotspot coverage quality gate başarısız:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("✅ Hotspot coverage quality gate başarılı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
