#!/usr/bin/env python3
"""Summarize test coverage hotspots from coverage.py XML output.

Usage:
  python scripts/coverage_hotspots.py --xml coverage.xml --top 10 --root .
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Iterable
import xml.etree.ElementTree as ET


@dataclass
class FileCoverage:
    path: str
    covered: int
    missed: int

    @property
    def total(self) -> int:
        return self.covered + self.missed

    @property
    def coverage_pct(self) -> float:
        total = self.total
        if total == 0:
            return 100.0
        return (self.covered / total) * 100


def _normalize_path(raw: str, root: str) -> str:
    if os.path.isabs(raw):
        return os.path.relpath(raw, root)
    return raw


def parse_coverage_xml(xml_path: str, root: str = ".") -> list[FileCoverage]:
    root_abs = os.path.abspath(root)
    tree = ET.parse(xml_path)
    xml_root = tree.getroot()

    records: list[FileCoverage] = []
    for cls in xml_root.findall(".//class"):
        filename = cls.attrib.get("filename")
        if not filename:
            continue

        covered = 0
        missed = 0
        for line in cls.findall("./lines/line"):
            hits = int(line.attrib.get("hits", "0"))
            if hits > 0:
                covered += 1
            else:
                missed += 1

        records.append(FileCoverage(path=_normalize_path(filename, root_abs), covered=covered, missed=missed))

    return records


def rank_hotspots(files: Iterable[FileCoverage], top: int = 10) -> list[FileCoverage]:
    return sorted(files, key=lambda rec: (rec.missed, -rec.coverage_pct), reverse=True)[:top]


def format_table(files: Iterable[FileCoverage]) -> str:
    lines = [
        "| File | Coverage | Missed | Covered |",
        "|---|---:|---:|---:|",
    ]
    for rec in files:
        lines.append(f"| {rec.path} | {rec.coverage_pct:.2f}% | {rec.missed} | {rec.covered} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="List lowest-coverage files from coverage XML.")
    parser.add_argument("--xml", default="coverage.xml", help="Path to coverage XML report (default: coverage.xml)")
    parser.add_argument("--top", type=int, default=10, help="Number of hotspots to show (default: 10)")
    parser.add_argument("--root", default=".", help="Project root used to normalize paths")
    args = parser.parse_args()

    data = parse_coverage_xml(args.xml, root=args.root)
    if not data:
        print("No files were found in coverage XML.")
        return 1

    print(format_table(rank_hotspots(data, top=args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
