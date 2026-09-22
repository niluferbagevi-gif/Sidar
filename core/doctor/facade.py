"""Doctor orchestration facade: report aggregation, repair, and CLI entry point."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import core.doctor as _doctor
from core.doctor import DEFAULT_OUTPUT
from core.doctor.models import redact_sensitive_text as _redact_sensitive_text


def run_doctor_report(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    include_model_smoke: bool = True,
) -> dict[str, Any]:
    from core.doctor.checks.media import check_media_tools as media_tools_check
    from core.doctor.checks.redis import check_redis as redis_check

    checks = [
        _doctor.check_uv(),
        _doctor.check_prometheus_runtime(),
        _doctor.check_environment_profile(),
        _doctor.check_gpu_memory_config(),
        _doctor.check_docker_test_image(),
        _doctor.check_database_env(),
    ]
    database_connectivity = _doctor.check_database_connectivity()
    checks.extend(
        [
            database_connectivity,
            _doctor.check_pgvector_ready(database_connectivity=database_connectivity),
        ]
    )
    checks.extend(
        [
            _doctor.check_rag_index_ready(),
            _doctor.check_graphrag_entity_memory_ready(),
            _doctor.check_migrations(),
            _doctor.check_agent_catalog(),
            _doctor.check_supervisor_routing(),
            _doctor.check_websocket_routes(),
            redis_check(),
            _doctor.check_gpu(),
            media_tools_check(),
            _doctor.check_model(smoke=include_model_smoke),
        ]
    )
    report = _doctor.build_doctor_report(checks)
    _doctor.write_doctor_report(report, output_path)
    return report


def _apply_database_env_fix() -> dict[str, Any]:
    """Apply the allowlisted database environment repair and return its audit record.

    The repair is deliberately limited to ``database_env``.  Doctor never starts
    services, runs migrations, or seeds user data implicitly; those operations stay
    visible as follow-up recommendations in the resulting report.
    """
    check = _doctor.check_database_env()
    result: dict[str, Any] = {
        "check": check.name,
        "before_status": check.status,
        "attempted": False,
        "success": check.status == "pass",
    }
    if check.status == "pass":
        result["message"] = "database environment already healthy; no repair was needed"
        return result

    command = str(check.details.get("auto_fix", "") or "").strip()
    if not command:
        result["message"] = "database environment check did not publish an auto-fix"
        return result

    try:
        tokens = _doctor.validate_auto_fix_command(command)
    except ValueError as exc:
        result["message"] = f"database environment auto-fix was rejected: {exc}"
        return result

    result["attempted"] = True
    result["command"] = command
    return_code, output = _doctor._run_command(tokens, timeout=120)
    result["return_code"] = return_code
    result["output"] = _redact_sensitive_text(output)
    result["success"] = return_code == 0
    result["message"] = (
        "database environment auto-fix completed"
        if return_code == 0
        else "database environment auto-fix failed"
    )

    # --remove-explicit-urls edits dotenv files in a subprocess. Remove only values
    # that Doctor proved came from those editable files, so the report in this same
    # process observes the newly derived POSTGRES_* DSNs. Inherited shell values are
    # intentionally preserved because the repair command cannot safely own them.
    if return_code == 0:
        for env_key, source_key in (
            ("DATABASE_URL", "database_url_source"),
            ("SIDAR_CONTAINER_DATABASE_URL", "container_database_url_source"),
        ):
            if check.details.get(source_key):
                os.environ.pop(env_key, None)
    return result


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the standalone Doctor CLI while preserving its positional output path."""
    parser = argparse.ArgumentParser(description="Sidar installation/readiness Doctor")
    parser.add_argument("output", nargs="?", default=str(DEFAULT_OUTPUT), help="JSON report path")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Safely repair editable database environment drift before running checks",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_cli_args(argv)
    output = Path(args.output)
    repair = _doctor._apply_database_env_fix() if args.fix else None
    report = _doctor.run_doctor_report(output_path=output)
    if repair is not None:
        report["repairs"] = [repair]
        _doctor.write_doctor_report(report, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    repair_failed = repair is not None and repair.get("attempted") and not repair.get("success")
    return 0 if report["overall_status"] in {"pass", "warn"} and not repair_failed else 1


__all__ = ["main", "run_doctor_report"]
