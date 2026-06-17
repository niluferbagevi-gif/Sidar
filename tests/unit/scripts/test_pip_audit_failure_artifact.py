from __future__ import annotations

import json
from pathlib import Path

from scripts.pip_audit_failure_artifact import build_artifact, classify_failure


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


def test_classify_failure_flags_vulnerability_when_findings_present(tmp_path: Path) -> None:
    raw_report = tmp_path / "pip-audit-report.raw.json"
    output = tmp_path / "pip-audit-failure.json"
    raw_report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "torch",
                        "version": "2.12.0",
                        "vulns": [{"id": "CVE-2025-3000"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stderr_log = tmp_path / "pip-audit-stderr.log"
    # Even when the stderr looks network-flavored, real vulns must win.
    stderr_log.write_text("HTTPSConnectionPool: Max retries exceeded", encoding="utf-8")

    artifact = build_artifact(raw_report, output, timeout="30", stderr_log_path=stderr_log)

    assert artifact["failure_category"] == "vulnerability"
    assert artifact["vulnerability_count"] == 1


def test_classify_failure_flags_network_when_stderr_matches_tunnel(tmp_path: Path) -> None:
    raw_report = tmp_path / "pip-audit-report.raw.json"
    output = tmp_path / "pip-audit-failure.json"
    # No report on disk — pip-audit exited before producing one.
    stderr_log = tmp_path / "pip-audit-stderr.log"
    stderr_log.write_text(
        "ERROR Could not fetch URL https://pypi.org/simple/pyarrow/: tunnel closed\n"
        "HTTPSConnectionPool(host='pypi.org', port=443)\n",
        encoding="utf-8",
    )

    artifact = build_artifact(raw_report, output, timeout="30", stderr_log_path=stderr_log)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert artifact["failure_category"] == "network"
    assert persisted["failure_category"] == "network"
    assert persisted["vulnerability_count"] == 0
    assert "stderr_tail" in persisted


def test_classify_failure_falls_back_to_unknown(tmp_path: Path) -> None:
    raw_report = tmp_path / "pip-audit-report.raw.json"
    output = tmp_path / "pip-audit-failure.json"
    raw_report.write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    stderr_log = tmp_path / "pip-audit-stderr.log"
    stderr_log.write_text("Some unexpected stderr without a known signature.\n", encoding="utf-8")

    artifact = build_artifact(raw_report, output, timeout="30", stderr_log_path=stderr_log)

    assert artifact["failure_category"] == "unknown"
    assert artifact["vulnerability_count"] == 0


def test_classify_failure_handles_missing_stderr_log(tmp_path: Path) -> None:
    raw_report = tmp_path / "missing-report.json"
    output = tmp_path / "pip-audit-failure.json"

    # Neither raw report nor stderr log exists. We should still emit a stable
    # artifact and degrade to "unknown" rather than crashing.
    artifact = build_artifact(
        raw_report, output, timeout="30", stderr_log_path=tmp_path / "absent.log"
    )

    assert artifact["failure_category"] == "unknown"
    assert "parse_error" in artifact


def test_classify_failure_pure_function_ignores_unrelated_stderr() -> None:
    assert classify_failure([], "") == "unknown"
    assert classify_failure([], "completely unrelated note") == "unknown"
    assert classify_failure([], "Max retries exceeded with url ...") == "network"
    assert classify_failure([{"package": "x"}], "Max retries exceeded") == "vulnerability"
