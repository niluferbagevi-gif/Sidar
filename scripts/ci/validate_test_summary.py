#!/usr/bin/env python3
"""Validate Sidar run_tests.sh summary JSON for development or release gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL_FIELDS = {
    "production_ready",
    "production_readiness",
    "production_readiness_detail",
}
REQUIRED_DETAIL_FIELDS = {
    "status",
    "reason",
    "required_command",
    "validation_class",
    "release_blocking",
    "release_gate_exit_code",
}


def _load_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"test summary bulunamadı: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"test summary JSON geçersiz: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("test summary kök JSON nesnesi dict/object olmalıdır")
    return payload


def _validate_shape(summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing_top = sorted(REQUIRED_TOP_LEVEL_FIELDS.difference(summary))
    if missing_top:
        errors.append("eksik top-level alanlar: " + ", ".join(missing_top))

    detail = summary.get("production_readiness_detail")
    if not isinstance(detail, dict):
        errors.append("production_readiness_detail nesnesi eksik veya object değil")
        return errors

    missing_detail = sorted(REQUIRED_DETAIL_FIELDS.difference(detail))
    if missing_detail:
        errors.append("eksik production_readiness_detail alanları: " + ", ".join(missing_detail))

    if "production_ready" in summary and not isinstance(summary["production_ready"], bool):
        errors.append("production_ready boolean olmalıdır")
    if "release_blocking" in detail and not isinstance(detail["release_blocking"], bool):
        errors.append("production_readiness_detail.release_blocking boolean olmalıdır")
    if "release_gate_exit_code" in detail and not isinstance(detail["release_gate_exit_code"], int):
        errors.append("production_readiness_detail.release_gate_exit_code integer olmalıdır")

    return errors


def _validate_release(summary: dict[str, Any]) -> list[str]:
    errors = _validate_shape(summary)
    if errors:
        return errors

    detail = summary["production_readiness_detail"]
    if summary.get("production_ready") is not True:
        errors.append("release mode production_ready=true bekler")
    if detail.get("status") != "passed":
        errors.append("release mode production_readiness_detail.status=passed bekler")
    if detail.get("validation_class") != "production_readiness":
        errors.append("release mode validation_class=production_readiness bekler")
    if detail.get("release_blocking") is not False:
        errors.append("release mode release_blocking=false bekler")
    if detail.get("release_gate_exit_code") != 0:
        errors.append("release mode release_gate_exit_code=0 bekler")

    if errors:
        required_command = str(detail.get("required_command") or "make production-readiness")
        direct_command = str(
            detail.get("equivalent_direct_command")
            or "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
            "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
        )
        errors.append(f"release/merge öncesi zorunlu komut: {required_command}")
        errors.append(f"eşdeğer doğrudan komut: {direct_command}")
    return errors


def validate_summary(summary: dict[str, Any], mode: str) -> list[str]:
    """Return validation errors for a test summary payload."""
    if mode == "release":
        return _validate_release(summary)
    return _validate_shape(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/test-summary.json"),
        help="Path to artifacts/test-summary.json produced by run_tests.sh.",
    )
    parser.add_argument(
        "--mode",
        choices=("development", "release"),
        default="development",
        help="Validation strictness. release fails unless production_ready=true.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = _load_summary(args.summary)
    errors = validate_summary(summary, args.mode)
    if errors:
        print("❌ test-summary doğrulaması başarısız:", file=sys.stderr)
        for error in errors:
            print(f"   - {error}", file=sys.stderr)
        return 1

    detail = summary["production_readiness_detail"]
    print(
        "✅ test-summary doğrulandı: "
        f"mode={args.mode}, production_ready={summary['production_ready']}, "
        f"validation_class={detail['validation_class']}, "
        f"release_blocking={detail['release_blocking']}, "
        f"release_gate_exit_code={detail['release_gate_exit_code']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
