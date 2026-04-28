#!/usr/bin/env python3
"""Local auto-heal CLI bridge for run_tests.sh."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agent.auto_handle import run_local_remediation_loop
from core.ci_remediation import build_ci_remediation_payload, build_local_failure_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local autonomous self-heal from a log file.")
    parser.add_argument("--log-file", required=True, help="Path to mypy/pytest error log file.")
    parser.add_argument("--stage", default="local_heal", help="Logical stage label.")
    parser.add_argument("--command", default="", help="Failed command text.")
    parser.add_argument("--attempt", type=int, default=1, help="Current retry attempt.")
    parser.add_argument("--max-attempts", type=int, default=1, help="Max retry attempts.")
    parser.add_argument("--output", default="", help="Optional JSON output file for heal result.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_path = Path(args.log_file)
    if not log_path.exists():
        print(f"❌ Log dosyası bulunamadı: {log_path}", file=sys.stderr)
        return 1

    log_text = log_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not log_text:
        print(f"❌ Log dosyası boş: {log_path}", file=sys.stderr)
        return 1

    context = build_local_failure_context(
        log_text=log_text,
        stage=args.stage,
        command=args.command,
        attempt=args.attempt,
        max_attempts=args.max_attempts,
    )
    diagnosis = (
        "Bu logları oku, hataları analiz et ve dosyaları düzelt. "
        + str(context.get("root_cause_hint") or context.get("failure_summary") or "local failure")
    )
    remediation_payload = build_ci_remediation_payload(context, diagnosis)
    result = asyncio.run(
        run_local_remediation_loop(
            context=context,
            diagnosis=diagnosis,
            remediation_payload=remediation_payload,
            output_path=(args.output or None),
        )
    )
    print(json.dumps(result, ensure_ascii=False))

    if str(result.get("status", "")).lower() != "ok":
        return 1
    execution = dict(result.get("execution") or {})
    execution_status = str(execution.get("status") or "").strip().lower()
    if execution_status in {"failed", "reverted", "blocked"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
