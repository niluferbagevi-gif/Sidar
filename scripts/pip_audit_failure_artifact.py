"""Summarize failing pip-audit JSON output into a stable CI artifact."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RERUN_COMMAND = "uv run --with pip-audit pip-audit --skip-editable --timeout {timeout}"


def _load_report(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, f"raw pip-audit report not found: {path}"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, f"raw pip-audit report is not valid JSON: {exc}"

    if not isinstance(data, dict):
        return {}, "raw pip-audit report root is not a JSON object"
    return data, None


def _dependency_vulnerabilities(report: dict[str, Any], timeout: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    dependencies = report.get("dependencies", [])
    if not isinstance(dependencies, list):
        return findings

    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        package_name = str(dependency.get("name", ""))
        installed_version = str(dependency.get("version", ""))
        vulns = dependency.get("vulns", [])
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            vulnerability_id = str(vuln.get("id", ""))
            fix_versions = vuln.get("fix_versions", [])
            if not isinstance(fix_versions, list):
                fix_versions = []
            findings.append(
                {
                    "cve": vulnerability_id,
                    "vulnerability_id": vulnerability_id,
                    "package": package_name,
                    "installed_version": installed_version,
                    "fix_versions": [str(version) for version in fix_versions],
                    "aliases": [str(alias) for alias in vuln.get("aliases", []) if isinstance(alias, str)]
                    if isinstance(vuln.get("aliases", []), list)
                    else [],
                    "description": str(vuln.get("description", "")),
                    "suggested_command": (
                        f"uv lock --upgrade-package {package_name} && uv sync --all-extras && "
                        f"{DEFAULT_RERUN_COMMAND.format(timeout=timeout)}"
                    )
                    if package_name
                    else DEFAULT_RERUN_COMMAND.format(timeout=timeout),
                }
            )
    return findings


def build_artifact(raw_report_path: Path, output_path: Path, *, timeout: str) -> dict[str, Any]:
    report, parse_error = _load_report(raw_report_path)
    findings = _dependency_vulnerabilities(report, timeout)
    affected_packages = sorted({finding["package"] for finding in findings if finding.get("package")})

    artifact: dict[str, Any] = {
        "success": False,
        "tool": "pip-audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_report_path": str(raw_report_path),
        "vulnerability_count": len(findings),
        "affected_packages": affected_packages,
        "vulnerabilities": findings,
        "suggested_commands": [
            "uv lock --upgrade-package <package>",
            "uv sync --all-extras",
            DEFAULT_RERUN_COMMAND.format(timeout=timeout),
        ],
    }
    if parse_error:
        artifact["parse_error"] = parse_error

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", default="30")
    args = parser.parse_args()

    build_artifact(args.raw_report, args.output, timeout=str(args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
