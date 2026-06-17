"""Summarize failing pip-audit JSON output into a stable CI artifact."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RERUN_COMMAND = "uv run --with pip-audit pip-audit --skip-editable --timeout {timeout}"

# Substrings (case-insensitive) that mark a pip-audit failure as a transient
# network/tunnel/PyPI-reachability issue rather than a real vulnerability
# finding. The list stays narrow on purpose: a generic word like "error" would
# misclassify a legitimate security failure.
NETWORK_ERROR_PATTERNS: tuple[str, ...] = (
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "ReadTimeoutError",
    "ConnectTimeoutError",
    "Max retries exceeded",
    "HTTPSConnectionPool",
    "HTTPConnectionPool",
    "Could not fetch",
    "Could not reach",
    "Name or service not known",
    "Temporary failure in name resolution",
    "Network is unreachable",
    "getaddrinfo failed",
    "Errno -3",
    "Errno 101",
    "SSLError",
    "TLSV1_ALERT",
    "tunnel",
    "proxy",
)


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
                    "aliases": [
                        str(alias) for alias in vuln.get("aliases", []) if isinstance(alias, str)
                    ]
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


def classify_failure(
    findings: list[dict[str, Any]],
    stderr_text: str,
) -> str:
    """Decide whether the pip-audit failure was a vulnerability or a network blip.

    Returns one of ``"vulnerability"``, ``"network"``, ``"unknown"``. A real
    vulnerability finding always wins — even if the stderr also mentions a
    network blip — because the report was actually produced.
    """

    if findings:
        return "vulnerability"
    if stderr_text:
        lowered = stderr_text.lower()
        for pattern in NETWORK_ERROR_PATTERNS:
            if pattern.lower() in lowered:
                return "network"
    return "unknown"


def _read_stderr_log(path: Path | None) -> str:
    if path is None:
        return ""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def build_artifact(
    raw_report_path: Path,
    output_path: Path,
    *,
    timeout: str,
    stderr_log_path: Path | None = None,
) -> dict[str, Any]:
    report, parse_error = _load_report(raw_report_path)
    findings = _dependency_vulnerabilities(report, timeout)
    affected_packages = sorted(
        {finding["package"] for finding in findings if finding.get("package")}
    )
    stderr_text = _read_stderr_log(stderr_log_path)
    failure_category = classify_failure(findings, stderr_text)

    # Trim the stderr snippet we persist; the raw log stays on disk for forensics.
    stderr_snippet = stderr_text.strip().splitlines()[-20:] if stderr_text else []

    artifact: dict[str, Any] = {
        "success": False,
        "tool": "pip-audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_report_path": str(raw_report_path),
        "failure_category": failure_category,
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
    if stderr_log_path is not None:
        artifact["stderr_log_path"] = str(stderr_log_path)
    if stderr_snippet:
        artifact["stderr_tail"] = stderr_snippet

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", default="30")
    parser.add_argument(
        "--stderr-log",
        type=Path,
        default=None,
        help="Optional path to the captured pip-audit stderr log, used to "
        "classify network/tunnel failures vs. real vulnerability findings.",
    )
    args = parser.parse_args()

    build_artifact(
        args.raw_report,
        args.output,
        timeout=str(args.timeout),
        stderr_log_path=args.stderr_log,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
