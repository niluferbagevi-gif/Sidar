"""
Yerel statik analiz log'larını Sidar self-healing döngüsüne bağlayan CLI köprüsü.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sidar local self-heal CLI")
    parser.add_argument("--log", required=True, help="Analiz log dosyası (örn: artifacts/mypy_errors.log)")
    parser.add_argument("--source", default="mypy", help="Hata kaynağı etiketi (varsayılan: mypy)")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Dosya bazlı kuyruğun batch boyutu (varsayılan: 1).",
    )
    parser.add_argument(
        "--model",
        help=(
            "Self-heal için coding model override değeri. "
            "Verilmezse mypy işlerinde 3B model algılanırsa otomatik 7B'ye yükseltilir."
        ),
    )
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


def _select_auto_heal_model(current_model: str, source: str, requested_model: str | None) -> str:
    requested = str(requested_model or "").strip()
    if requested:
        return requested
    normalized_source = str(source or "").strip().lower()
    model_name = str(current_model or "").strip()
    if normalized_source == "mypy" and ":3b" in model_name.lower():
        return model_name.lower().replace(":3b", ":7b")
    return model_name


def _build_scope_queue(remediation_loop: dict[str, Any], *, batch_size: int) -> list[list[str]]:
    raw_paths = [str(path).strip() for path in remediation_loop.get("scope_paths", []) if str(path).strip()]
    if not raw_paths:
        return []

    normalized_batch_size = max(1, int(batch_size or 1))
    return [
        raw_paths[index : index + normalized_batch_size]
        for index in range(0, len(raw_paths), normalized_batch_size)
    ]


async def _run_self_heal_attempt(
    *,
    agent: Any,
    context: dict[str, Any],
    diagnosis: str,
    remediation: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    execution = await agent._attempt_autonomous_self_heal(  # noqa: SLF001
        ci_context=context,
        diagnosis=diagnosis,
        remediation=remediation,
    )
    if str(execution.get("status") or "") != "awaiting_hitl":
        return execution

    approved = _parse_approval_value(args.hitl_approve)
    if approved is None and args.hitl_approve is not None:
        print(
            "⚠ --hitl-approve değeri anlaşılamadı. "
            "Kabul edilenler: yes/no, y/n, evet/hayır, e/h, true/false, 1/0."
        )
    approved = approved if approved is not None else _prompt_hitl_approval()
    return await agent._attempt_autonomous_self_heal(  # noqa: SLF001
        ci_context=context,
        diagnosis=diagnosis,
        remediation=remediation,
        human_approval=approved,
    )


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
    cfg.CODING_MODEL = _select_auto_heal_model(cfg.CODING_MODEL, args.source, args.model)
    agent = SidarAgent(config=cfg)
    await agent.initialize()

    remediation_base = build_ci_remediation_payload(context, diagnosis)
    scope_queue = _build_scope_queue(
        remediation_base.get("remediation_loop", {}),
        batch_size=args.batch_size,
    )
    executions: list[dict[str, Any]] = []
    queue = scope_queue or [list(remediation_base.get("remediation_loop", {}).get("scope_paths", []))]

    for index, scope_paths in enumerate(queue, start=1):
        chunk_context = dict(context)
        chunk_context["suspected_targets"] = list(scope_paths)
        chunk_remediation = build_ci_remediation_payload(chunk_context, diagnosis)
        chunk_remediation_loop = dict(chunk_remediation.get("remediation_loop") or {})
        chunk_remediation_loop["scope_paths"] = list(scope_paths)
        chunk_remediation_loop["autonomous_batches"] = []
        chunk_remediation["remediation_loop"] = chunk_remediation_loop
        execution = await _run_self_heal_attempt(
            agent=agent,
            context=chunk_context,
            diagnosis=diagnosis,
            remediation=chunk_remediation,
            args=args,
        )
        execution["batch_index"] = index
        execution["batch_total"] = len(queue)
        execution["scope_paths"] = list(scope_paths)
        executions.append(execution)
        if str(execution.get("status") or "") != "applied":
            break

    final_status = "applied" if executions and all(
        str(item.get("status") or "") == "applied" for item in executions
    ) else "partial_or_failed"
    print(
        json.dumps(
            {
                "status": final_status,
                "model": cfg.CODING_MODEL,
                "queue_size": len(queue),
                "executions": executions,
                "context": context,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if final_status == "applied" else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
