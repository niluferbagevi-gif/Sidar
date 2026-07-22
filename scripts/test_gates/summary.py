#!/usr/bin/env python3
"""Write Sidar's machine-readable quality-gate summary JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


def _safe_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return max(parsed, 0)


def _flag_enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "required"}


def _testcase_nodeid(testcase: Any) -> str:
    name = cast(str, testcase.attrib.get("name", "")).strip()
    file_path = cast(str, testcase.attrib.get("file", "")).strip()
    if file_path and name:
        return f"{file_path}::{name}"

    classname = cast(str, testcase.attrib.get("classname", "")).strip()
    if classname and name:
        candidate = classname.replace(".", "/")
        if candidate.startswith("tests/") and not candidate.endswith(".py"):
            candidate = f"{candidate}.py"
        return f"{candidate}::{name}"
    return name


def _failed_backend_tests(report_dir: str) -> list[str]:
    failed_tests: list[str] = []
    seen: set[str] = set()
    for report_path in sorted(Path(report_dir).glob("backend-*.xml")):
        try:
            root = ET.parse(report_path).getroot()
        except (ET.ParseError, DefusedXmlException):
            continue
        for testcase in root.iter("testcase"):
            if not any(child.tag.rsplit("}", 1)[-1] in {"failure", "error"} for child in testcase):
                continue
            nodeid = _testcase_nodeid(testcase)
            if nodeid and nodeid not in seen:
                seen.add(nodeid)
                failed_tests.append(nodeid)
    return failed_tests


def build_summary(args: list[str]) -> dict[str, object]:
    """Build the test-summary payload from run_tests.sh positional values."""
    (
        _output_path,
        smoke,
        integration,
        e2e,
        frontend_lint,
        frontend_typecheck,
        frontend_coverage,
        frontend_bundle_budget,
        frontend_e2e,
        benchmark,
        production_ready,
        junit_dir,
        backend_failed_tests_enabled,
        installer_bootstrap_mode,
        raw_fallback_modules_downloaded,
        remote_module_download_attempts,
        http_429_retries,
        remote_module_cache_hits,
        remote_module_base_url,
        production_readiness_summary,
        production_readiness_status,
        production_readiness_reason,
        validation_class,
        release_blocking,
        release_gate_exit_code,
        installer_mode,
        benchmark_compare_status,
        benchmark_baseline_name,
        benchmark_baseline_file,
        benchmark_compare_selector,
        benchmark_compare_required,
        benchmark_enforce_compare,
        benchmark_enable_compare,
        benchmark_compare_fail,
        benchmark_json_output,
        frontend_e2e_scope,
        frontend_e2e_script,
    ) = args

    return {
        "smoke": smoke,
        "integration": integration,
        "e2e": e2e,
        "frontend_lint": frontend_lint,
        "frontend_typecheck": frontend_typecheck,
        "frontend_coverage": frontend_coverage,
        "frontend_bundle_budget": frontend_bundle_budget,
        "frontend_e2e": frontend_e2e,
        "benchmark": benchmark,
        "production_readiness": production_readiness_summary,
        "benchmark_compare": benchmark_compare_status,
        "frontend_e2e_scope": frontend_e2e_scope,
        "installer_mode": installer_mode,
        "benchmark_baseline": {
            "name": benchmark_baseline_name or "baseline",
            "compare_required": _flag_enabled(benchmark_compare_required),
            "compare_enforced": _flag_enabled(benchmark_enforce_compare),
            "compare_enabled": _flag_enabled(benchmark_enable_compare),
            "compare_fail": benchmark_compare_fail or None,
            "file": benchmark_baseline_file or None,
            "selector": benchmark_compare_selector or None,
            "json_output": benchmark_json_output,
            "local_seed_command": (
                "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required bash run_tests.sh --stage all"
            ),
            "ci_seed_workflow": "GitHub Actions → CI → Run workflow → seed_benchmark_baseline=true",
            "ci_fail_closed": True,
        },
        "production_ready": production_ready == "true",
        "production_readiness_detail": {
            "status": production_readiness_status,
            "reason": production_readiness_reason,
            "required_command": "make production-readiness",
            "equivalent_direct_command": (
                "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
                "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
            ),
            "validation_class": validation_class,
            "release_blocking": release_blocking == "true",
            "release_gate_exit_code": _safe_int(release_gate_exit_code),
        },
        "frontend_e2e_script": frontend_e2e_script,
        "backend_failed_tests": (
            _failed_backend_tests(junit_dir) if backend_failed_tests_enabled == "true" else []
        ),
        "installer": {
            "bootstrap_mode": installer_bootstrap_mode or "unknown",
            "raw_fallback_modules_downloaded": _safe_int(raw_fallback_modules_downloaded),
            "remote_module_download_attempts": _safe_int(remote_module_download_attempts),
            "http_429_retries": _safe_int(http_429_retries),
            "remote_module_cache_hits": _safe_int(remote_module_cache_hits),
            "remote_module_base_url": remote_module_base_url,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Write a summary JSON file and return a process status code."""
    args = list(sys.argv[1:] if argv is None else argv)
    expected_arg_count = 37
    if len(args) != expected_arg_count:
        print(
            f"expected {expected_arg_count} arguments, got {len(args)}",
            file=sys.stderr,
        )
        return 2
    output_path = args[0]
    summary = build_summary(args)
    Path(output_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
