"""
Yerel statik analiz log'larını Sidar self-healing döngüsüne bağlayan CLI köprüsü.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
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
    parser.add_argument(
        "--batch-retries",
        type=int,
        default=2,
        help=(
            "Her batch için plan üretimi/uygulama başarısız olursa yapılacak ek deneme sayısı "
            "(varsayılan: 2)."
        ),
    )
    parser.add_argument(
        "--scope-log-lines",
        type=int,
        default=30,
        help="Her batch prompt'una eklenecek hedefe özgü hata satırı limiti (varsayılan: 30).",
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


def _extract_scope_error_lines(
    log_text: str,
    *,
    scope_paths: list[str],
    limit: int,
) -> list[str]:
    if not log_text.strip():
        return []
    normalized_paths = [
        str(path).strip().lstrip("./").replace("\\", "/")
        for path in scope_paths
        if str(path).strip()
    ]
    if not normalized_paths:
        return []
    seen: set[str] = set()
    selected: list[str] = []
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        if not line or line in seen:
            continue
        normalized_line = line.replace("\\", "/")
        if not any(path in normalized_line for path in normalized_paths):
            continue
        if not re.search(r"\berror\b|mypy|type|incompatible|no-untyped-def", normalized_line, re.IGNORECASE):
            continue
        seen.add(line)
        selected.append(line)
        if len(selected) >= max(1, int(limit or 1)):
            break
    return selected


def _build_attempt_diagnosis(
    *,
    base_diagnosis: str,
    scope_paths: list[str],
    scope_error_lines: list[str],
    attempt: int,
    total_attempts: int,
) -> str:
    diagnosis_lines = [line.strip() for line in str(base_diagnosis or "").splitlines() if line.strip()]
    scope_display = ", ".join(scope_paths) or "-"
    if not diagnosis_lines:
        diagnosis_lines = [f"Hedef kapsam için tip hataları düzeltilecek: {scope_display}"]
    guidance = (
        f"Batch retry {attempt}/{total_attempts}: Yalnızca şu dosyalarda minimal patch üret: {scope_display}. "
        "JSON şemasına birebir uy, sadece patch action kullan, target metni dosyada birebir geçen satırlardan seç."
    )
    diagnosis_lines.append(guidance)
    if scope_error_lines:
        diagnosis_lines.append("Hedef hata satırları:")
        diagnosis_lines.extend(f"- {line}" for line in scope_error_lines[:40])
    return "\n".join(diagnosis_lines)


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
        scope_error_lines = _extract_scope_error_lines(
            log_text,
            scope_paths=scope_paths,
            limit=args.scope_log_lines,
        )
        if scope_error_lines:
            chunk_context["log_excerpt"] = "\n".join(scope_error_lines)
            chunk_context["failure_summary"] = (
                f"{context.get('failure_summary', '')}\n"
                f"scope_errors={len(scope_error_lines)} target_files={len(scope_paths)}"
            ).strip()
        chunk_remediation = build_ci_remediation_payload(chunk_context, diagnosis)
        chunk_remediation_loop = dict(chunk_remediation.get("remediation_loop") or {})
        chunk_remediation_loop["scope_paths"] = list(scope_paths)
        chunk_remediation_loop["autonomous_batches"] = []
        chunk_remediation["remediation_loop"] = chunk_remediation_loop
        attempt_logs: list[dict[str, Any]] = []
        attempt_count = max(1, int(args.batch_retries or 0) + 1)
        execution: dict[str, Any] = {"status": "blocked", "summary": "Self-heal denemesi çalıştırılmadı."}
        for attempt in range(1, attempt_count + 1):
            attempt_diagnosis = _build_attempt_diagnosis(
                base_diagnosis=diagnosis,
                scope_paths=scope_paths,
                scope_error_lines=scope_error_lines,
                attempt=attempt,
                total_attempts=attempt_count,
            )
            execution = await _run_self_heal_attempt(
                agent=agent,
                context=chunk_context,
                diagnosis=attempt_diagnosis,
                remediation=chunk_remediation,
                args=args,
            )
            attempt_status = str(execution.get("status") or "")
            attempt_logs.append(
                {
                    "attempt": attempt,
                    "status": attempt_status or "unknown",
                    "summary": str(execution.get("summary") or "").strip(),
                }
            )
            if attempt_status == "applied":
                break
            retryable = attempt_status in {"blocked", "failed", "partial"}
            if not retryable or attempt >= attempt_count:
                break
        execution["batch_index"] = index
        execution["batch_total"] = len(queue)
        execution["scope_paths"] = list(scope_paths)
        execution["attempts"] = attempt_logs
        executions.append(execution)

    status_values = [str(item.get("status") or "") for item in executions]
    any_applied = any(status == "applied" for status in status_values)
    all_applied = bool(status_values) and all(status == "applied" for status in status_values)
    final_status = "applied" if all_applied else ("partial" if any_applied else "failed")
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
    return 0 if final_status in {"applied", "partial"} else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
