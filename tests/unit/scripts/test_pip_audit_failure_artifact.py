from __future__ import annotations

import json
from pathlib import Path

from scripts.pip_audit_failure_artifact import build_artifact


def test_builds_pip_audit_failure_artifact_with_fix_command(tmp_path: Path) -> None:
    raw_report = tmp_path / "pip-audit-report.raw.json"
    output = tmp_path / "pip-audit-failure.json"
    raw_report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "torch",
                        "version": "2.12.0",
                        "vulns": [
                            {
                                "id": "CVE-2025-3000",
                                "fix_versions": ["2.12.1"],
                                "aliases": ["GHSA-example"],
                                "description": "example vulnerability",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    artifact = build_artifact(raw_report, output, timeout="30")
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert artifact["vulnerability_count"] == 1
    assert persisted["affected_packages"] == ["torch"]
    vulnerability = persisted["vulnerabilities"][0]
    assert vulnerability["cve"] == "CVE-2025-3000"
    assert vulnerability["package"] == "torch"
    assert vulnerability["installed_version"] == "2.12.0"
    assert vulnerability["fix_versions"] == ["2.12.1"]
    assert "uv lock --upgrade-package torch" in vulnerability["suggested_command"]
    assert "uv sync --all-extras" in vulnerability["suggested_command"]
    assert "pip-audit --skip-editable --timeout 30" in vulnerability["suggested_command"]


def test_builds_parse_error_artifact_when_raw_report_missing(tmp_path: Path) -> None:
    output = tmp_path / "pip-audit-failure.json"

    build_artifact(tmp_path / "missing.json", output, timeout="10")
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted["vulnerability_count"] == 0
    assert "parse_error" in persisted
    assert persisted["suggested_commands"][-1].endswith("--timeout 10")
