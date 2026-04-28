"""
Yerel statik analiz log'larını Sidar self-healing döngüsüne bağlayan CLI köprüsü.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sidar local self-heal CLI")
    parser.add_argument("--log", required=True, help="Analiz log dosyası (örn: artifacts/mypy_errors.log)")
    parser.add_argument("--source", default="mypy", help="Hata kaynağı etiketi (varsayılan: mypy)")
    parser.add_argument(
        "--hitl-approve",
        help=(
            "Riskli self-heal planı için insan onayı. "
            "Kabul edilen değerler: yes/no, y/n, evet/hayır, e/h, true/false, 1/0. "
            "Verilmezse etkileşimli sorulur."
        ),
    )
    return parser.parse_args()


def _parse_approval_value(value: str | None) -> bool | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "y", "evet", "e"}:
        return True
    if normalized in {"0", "false", "no", "n", "hayır", "hayir", "h"}:
        return False
    return None


def _prompt_hitl_approval() -> bool:
    while True:
        answer = input("⚠ Riskli self-heal planı bulundu. Uygulansın mı? (evet/hayır): ").strip().lower()
        parsed = _parse_approval_value(answer)
        if parsed is not None:
            return parsed
        print("Lütfen 'evet/e' veya 'hayır/h' (ya da yes/no) girin.")


async def _run(args: argparse.Namespace) -> int:
    from agent.sidar_agent import SidarAgent
    from config import Config
    from core.ci_remediation import build_ci_remediation_payload, build_local_failure_context

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"❌ Log dosyası bulunamadı: {log_path}")
        return 1

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    context = build_local_failure_context(log_text, source=args.source, log_path=str(log_path))
    diagnosis = str(context.get("root_cause_hint") or context.get("failure_summary") or "").strip()

    cfg = Config()
    cfg.ENABLE_AUTONOMOUS_SELF_HEAL = True
    agent = SidarAgent(config=cfg)
    await agent.initialize()

    remediation = build_ci_remediation_payload(context, diagnosis)
    execution = await agent._attempt_autonomous_self_heal(  # noqa: SLF001
        ci_context=context,
        diagnosis=diagnosis,
        remediation=remediation,
    )
    if str(execution.get("status") or "") == "awaiting_hitl":
        approved = _parse_approval_value(args.hitl_approve)
        if approved is None and args.hitl_approve is not None:
            print(
                "⚠ --hitl-approve değeri anlaşılamadı. "
                "Kabul edilenler: yes/no, y/n, evet/hayır, e/h, true/false, 1/0."
            )
        approved = approved if approved is not None else _prompt_hitl_approval()
        execution = await agent._attempt_autonomous_self_heal(  # noqa: SLF001
            ci_context=context,
            diagnosis=diagnosis,
            remediation=remediation,
            human_approval=approved,
        )
    print(json.dumps({"execution": execution, "context": context}, ensure_ascii=False, indent=2))
    return 0 if str(execution.get("status") or "") == "applied" else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
