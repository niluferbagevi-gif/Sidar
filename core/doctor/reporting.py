"""Pure doctor report formatting and persistence helpers."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.doctor.models import DoctorCheckContract, validate_doctor_check_contract


def build_doctor_report(
    checks: Iterable[DoctorCheckContract],
    *,
    generated_at_unix: int | None = None,
    schema_version: int = 1,
) -> dict[str, Any]:
    """Build a JSON-serializable aggregate doctor report from check results."""

    validated_checks = [validate_doctor_check_contract(check) for check in checks]
    statuses = [check.status for check in validated_checks]
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {
        "schema_version": schema_version,
        "generated_at_unix": int(time.time()) if generated_at_unix is None else generated_at_unix,
        "overall_status": overall,
        "run_gpu_stress": any(
            check.name == "gpu" and bool(check.details.get("run_gpu_stress"))
            for check in validated_checks
        ),
        "checks": [check.as_dict() for check in validated_checks],
    }


def write_doctor_report(report: dict[str, Any], output_path: str | Path) -> None:
    """Persist a formatted doctor report as stable, pretty JSON."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
