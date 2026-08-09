"""Yerel statik analiz log'larını Sidar self-healing döngüsüne bağlayan CLI köprüsü."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

MYPY_SELF_HEAL_REFERENCE = """\
Mypy quick-fix referansı:
- [import-untyped]: 3rd-party paket için tip stubları yoksa önce stubs/paket kurulumu dene; geçici
olarak dar kapsamlı
  `# type: ignore[import-untyped]` kullan ve mümkünse satıra kısa gerekçe ekle.
- [misc]: Genel kural; gerçek kök nedeni logdan teyit et. Sadece deterministic false-positive
durumlarında
  dar kapsamlı `# type: ignore[misc]` uygula.
- [valid-type]: Geçersiz type ifadesi; import edilen sembolün gerçekten type olduğundan emin ol.
Gerekirse
  `typing.TypeAlias`, `from __future__ import annotations` veya doğru jenerik formu kullan.
Kurallar:
1) `type: ignore` her zaman spesifik kodla kullanılmalı (`ignore[...]`), çıplak ignore yasak.
2) Ignore sadece lokal satır/ifade kapsamına uygulanmalı; dosya geneline yayma.
3) Önce doğru type düzeltmesini dene, ignore son çare olmalı.
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sidar local self-heal CLI")
    parser.add_argument(
        "--log", required=True, help="Analiz log dosyası (örn: artifacts/mypy_errors.log)"
    )
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
            "Kabul edilen değerler: yes/no, y/n, evet/hayır, e/h, true/false, 1/0 veya prompt. "
            "Verilmezse ya da prompt verilirse etkileşimli sorulur."
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
    parser.add_argument(
        "--database-url",
        help=(
            "Self-heal çalışma belleği için DB URL override değeri. "
            "Verilmezse SELF_HEAL_DATABASE_URL okunur; o da yoksa log dizininde izole SQLite "
            "kullanılır."
        ),
    )
    parser.add_argument(
        "--output",
        help=(
            "Nihai self-heal JSON sonucunu yazılacak dosya. "
            "Verilirse stdout'a basılan sonuç aynı zamanda bu artefakta da kaydedilir."
        ),
    )
    return parser.parse_args()


def _emit_result(payload: dict[str, Any], args: argparse.Namespace) -> None:
    """Print the final self-heal result and optionally persist it for truncated logs."""
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    output_path_text = str(getattr(args, "output", "") or "").strip()
    if not output_path_text:
        return
    output_path = Path(output_path_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")


def _resolve_auto_heal_database_url(log_path: Path, requested_database_url: str | None) -> str:
    """Self-heal için altyapı bağımlılığı düşük, izole bellek veritabanı seçer."""
    requested = str(requested_database_url or "").strip()
    if requested:
        return requested

    env_database_url = os.getenv("SELF_HEAL_DATABASE_URL", "").strip()
    if env_database_url:
        return env_database_url

    db_path = log_path.expanduser().resolve().parent / "auto_heal_memory.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _configure_auto_heal_memory_backend(cfg: Any, database_url: str) -> str:
    """Prefer lightweight BM25 memory when self-heal runs on its isolated SQLite DB."""
    vector_backend = str(getattr(cfg, "RAG_VECTOR_BACKEND", "") or "").strip().lower()
    if vector_backend == "pgvector" and not str(database_url or "").startswith("postgresql"):
        cfg.RAG_VECTOR_BACKEND = "bm25"
        return "bm25"
    return str(getattr(cfg, "RAG_VECTOR_BACKEND", vector_backend) or vector_backend)


def _redact_database_url(database_url: str) -> str:
    """Log/JSON çıktısında parola sızdırmadan DB URL bilgisini gösterir."""
    text = str(database_url or "").strip()
    if not text or "://" not in text:
        return text
    scheme, rest = text.split("://", 1)
    if "@" not in rest:
        return text
    credentials, host_part = rest.split("@", 1)
    if ":" not in credentials:
        return text
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host_part}"


async def _initialize_agent_soft_dependency(agent: Any) -> str | None:
    """Ajan altyapısı hazır değilse self-heal'i soft dependency olarak devam ettirir."""
    try:
        await agent.initialize()
    except Exception as exc:
        warning = (
            "Ajan başlatma sırasında opsiyonel bellek/RAG altyapısı hazırlanamadı; "
            f"self-heal temel code/LLM yetenekleriyle devam edecek: {exc}"
        )
        return warning
    return None


def _parse_approval_value(value: str | None) -> bool | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"prompt", "ask", "interactive"}:
        return None
    if normalized in {"1", "true", "yes", "y", "evet", "e"}:
        return True
    if normalized in {"0", "false", "no", "n", "hayır", "hayir", "h"}:
        return False
    return None


def _wants_interactive_hitl_prompt(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"", "prompt", "ask", "interactive"}


def _has_interactive_tty() -> bool:
    """Return True only if both stdin and stdout are attached to a real terminal.

    input() blocks on stdin; in an unattended CI/cron run stdin is typically
    closed or redirected, which makes input() raise EOFError instead of
    returning a value, crashing the autonomous loop mid-remediation.
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _prompt_hitl_approval() -> bool:
    if not _has_interactive_tty():
        print(
            "⚠ Etkileşimli terminal bulunamadı; HITL onay prompt'u gösterilemiyor. "
            "Fail-closed davranış: risky self-heal planı reddedildi (hayır). "
            "Unattended/otonom çalıştırmalarda --hitl-approve yes/no ile açıkça belirtin."
        )
        return False
    while True:
        answer = (
            input("⚠ Riskli self-heal planı bulundu. Uygulansın mı? (evet/hayır): ").strip().lower()
        )
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
    raw_paths = [
        str(path).strip() for path in remediation_loop.get("scope_paths", []) if str(path).strip()
    ]
    if not raw_paths:
        return []

    normalized_batch_size = max(1, int(batch_size or 1))
    return [
        raw_paths[index : index + normalized_batch_size]
        for index in range(0, len(raw_paths), normalized_batch_size)
    ]


def _extract_mypy_targets_from_log(log_text: str, *, limit: int = 200) -> list[str]:
    """Fallback parser: derive candidate files from mypy's `path:line: error:` format."""
    if not log_text.strip():
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(?P<path>[A-Za-z0-9_./\-]+\.py):\d+(?::\d+)?:\s+error\b", line)
        if not match:
            continue
        candidate = match.group("path").lstrip("./").replace("\\", "/")
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        targets.append(candidate)
        if len(targets) >= max(1, int(limit or 1)):
            break
    return targets


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
        if not re.search(
            r"\berror\b|mypy|type|incompatible|no-untyped-def|assertion|attribute|failed|failure|traceback",
            normalized_line,
            re.IGNORECASE,
        ):
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
    diagnosis_lines = [
        line.strip() for line in str(base_diagnosis or "").splitlines() if line.strip()
    ]
    scope_display = ", ".join(scope_paths) or "-"
    if not diagnosis_lines:
        diagnosis_lines = [
            f"Hedef kapsam için yerel kalite kapısı hataları düzeltilecek: {scope_display}"
        ]
    guidance = (
        f"Batch retry {attempt}/{total_attempts}: Yalnızca şu dosyalarda minimal patch üret: "
        f"{scope_display}. "
        "JSON şemasına birebir uy, sadece patch action kullan, target metni dosyada birebir geçen "
        "satırlardan seç."
    )
    diagnosis_lines.append(guidance)
    if scope_error_lines:
        diagnosis_lines.append("Hedef hata satırları:")
        diagnosis_lines.extend(f"- {line}" for line in scope_error_lines[:40])
    diagnosis_lines.append(MYPY_SELF_HEAL_REFERENCE)
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
        return cast(dict[str, Any], execution)

    loop = dict((remediation or {}).get("remediation_loop") or {})
    hitl_reasons = [str(item) for item in list(loop.get("hitl_reasons") or []) if str(item)]
    reason_text = ", ".join(hitl_reasons) or "riskli remediation"
    print(f"⚠ Riskli self-heal planı HITL onayı bekliyor. Nedenler: {reason_text}")

    approved = _parse_approval_value(args.hitl_approve)
    if (
        approved is None
        and args.hitl_approve is not None
        and not _wants_interactive_hitl_prompt(args.hitl_approve)
    ):
        print(
            "⚠ --hitl-approve değeri anlaşılamadı. "
            "Kabul edilenler: yes/no, y/n, evet/hayır, e/h, true/false, 1/0 veya prompt."
        )
    approved = approved if approved is not None else _prompt_hitl_approval()
    return cast(
        dict[str, Any],
        await agent._attempt_autonomous_self_heal(  # noqa: SLF001
            ci_context=context,
            diagnosis=diagnosis,
            remediation=remediation,
            human_approval=approved,
        ),
    )


async def _run(args: argparse.Namespace) -> int:
    from agent.sidar_agent import SidarAgent
    from config import Config
    from core.ci_remediation import build_ci_remediation_payload, build_local_failure_context

    log_path = Path(args.log)
    if not await asyncio.to_thread(log_path.exists):
        _emit_result(
            {
                "status": "failed",
                "model": "",
                "queue_size": 0,
                "executions": [],
                "reason": f"Log dosyası bulunamadı: {log_path}",
            },
            args,
        )
        return 1

    log_text = await asyncio.to_thread(log_path.read_text, encoding="utf-8", errors="replace")
    context = build_local_failure_context(log_text, source=args.source, log_path=str(log_path))
    suspected_targets = list(context.get("suspected_targets") or [])
    if not suspected_targets:
        source_name = str(args.source or "local").strip() or "local"
        lower_text = log_text.lower()
        if "success: no issues found" in lower_text and source_name.lower() == "mypy":
            _emit_result(
                {
                    "status": "skipped",
                    "model": "",
                    "queue_size": 0,
                    "executions": [],
                    "context": context,
                    "reason": "mypy temiz çıktı verdi; uygulanacak patch yok.",
                },
                args,
            )
            return 0

        fallback_targets = (
            _extract_mypy_targets_from_log(log_text) if source_name.lower() == "mypy" else []
        )
        if fallback_targets:
            context["suspected_targets"] = fallback_targets
            suspected_targets = fallback_targets
            context["failure_summary"] = (
                f"{context.get('failure_summary', '')}\n"
                f"fallback_targets_from_mypy_log={len(fallback_targets)}"
            ).strip()

    diagnosis = str(context.get("root_cause_hint") or context.get("failure_summary") or "").strip()

    cfg = Config()
    cfg.ENABLE_AUTONOMOUS_SELF_HEAL = True
    cfg.CODING_MODEL = _select_auto_heal_model(cfg.CODING_MODEL, args.source, args.model)
    cfg.DATABASE_URL = _resolve_auto_heal_database_url(
        log_path, getattr(args, "database_url", None)
    )
    memory_backend = _configure_auto_heal_memory_backend(cfg, str(cfg.DATABASE_URL))
    agent = SidarAgent(config=cfg)
    initialization_warning = await _initialize_agent_soft_dependency(agent)

    remediation_base = build_ci_remediation_payload(context, diagnosis)
    scope_queue = _build_scope_queue(
        remediation_base.get("remediation_loop", {}),
        batch_size=args.batch_size,
    )
    executions: list[dict[str, Any]] = []
    queue = scope_queue or [
        list(remediation_base.get("remediation_loop", {}).get("scope_paths", []))
    ]

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
        execution: dict[str, Any] = {
            "status": "blocked",
            "summary": "Self-heal denemesi çalıştırılmadı.",
        }
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
    _emit_result(
        {
            "status": final_status,
            "model": cfg.CODING_MODEL,
            "database_url": _redact_database_url(str(getattr(cfg, "DATABASE_URL", ""))),
            "memory_backend": memory_backend,
            "initialization_warning": initialization_warning,
            "queue_size": len(queue),
            "executions": executions,
            "context": context,
        },
        args,
    )
    return 0 if final_status in {"applied", "partial"} else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
