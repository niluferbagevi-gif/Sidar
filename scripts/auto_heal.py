#!/usr/bin/env python3
"""Local auto-heal CLI bridge for run_tests.sh."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agent.auto_handle import run_local_remediation_loop
from agent.sidar_agent import SidarAgent
from config import Config
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

    result = asyncio.run(
        _run_heal_with_fallback(
            log_file=str(log_path),
            log_text=log_text,
            stage=args.stage,
            command=args.command,
            attempt=args.attempt,
            max_attempts=args.max_attempts,
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


async def _run_heal_with_fallback(
    *,
    log_file: str,
    log_text: str,
    stage: str,
    command: str,
    attempt: int,
    max_attempts: int,
    output_path: str | None,
) -> dict:
    """Önce SidarAgent + `.heal` akışını dener, gerekirse remediation loop fallback'ına geçer."""
    cfg = Config()
    setattr(cfg, "ENABLE_AUTONOMOUS_SELF_HEAL", True)
    try:
        agent = SidarAgent(cfg=cfg)
        chunks = []
        async for chunk in agent.respond(f".heal {log_file}"):
            chunks.append(str(chunk))
        output = "".join(chunks).strip()
        if "✅ Heal tamamlandı" in output:
            result = {"status": "ok", "execution": {"status": "applied"}, "summary": output}
            if output_path:
                Path(output_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
    except Exception as exc:
        output = f"agent_heal_fallback: {exc}"

    context = build_local_failure_context(
        log_text=log_text,
        stage=stage,
        command=command,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    diagnosis = (
        "Bu logları oku, hataları analiz et ve dosyaları düzelt. "
        + str(context.get("root_cause_hint") or context.get("failure_summary") or "local failure")
    )
    remediation_payload = build_ci_remediation_payload(context, diagnosis)
    fallback_result = await run_local_remediation_loop(
        context=context,
        diagnosis=diagnosis,
        remediation_payload=remediation_payload,
        output_path=output_path,
    )
    if output:
        fallback_result["agent_heal_note"] = output
    return fallback_result


if __name__ == "__main__":
    raise SystemExit(main())
