"""External autonomy trigger correlation and processing services."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from agent.core.contracts import ExternalTrigger
from agent.federation.service import derive_correlation_id
from core.ci_remediation import (
    build_ci_failure_context,
    build_ci_remediation_payload,
)

logger = logging.getLogger(__name__)


def build_trigger_correlation(
    agent: Any, trigger: Any, payload_dict: dict[str, Any]
) -> dict[str, Any]:
    """Correlate a trigger with bounded recent autonomy history."""
    agent._ensure_autonomy_runtime_state()
    trigger_meta = agent._trigger_meta(trigger)
    correlation_id = derive_correlation_id(
        agent._trigger_attr(trigger, "correlation_id", ""),
        trigger_meta.get("correlation_id", ""),
        payload_dict.get("correlation_id", ""),
        payload_dict.get("related_task_id", ""),
        payload_dict.get("task_id", ""),
        agent._trigger_attr(trigger, "trigger_id", ""),
    )
    related_trigger_id = str(payload_dict.get("related_trigger_id") or "").strip()
    related_task_id = str(
        payload_dict.get("related_task_id") or payload_dict.get("task_id") or ""
    ).strip()

    matches: list[dict[str, Any]] = []
    for item in reversed(list(getattr(agent, "_autonomy_history", []) or [])):
        item_trigger_id = str(item.get("trigger_id", "") or "")
        item_payload = dict(item.get("payload") or {})
        item_corr = derive_correlation_id(
            item.get("correlation", {}).get("correlation_id", "")
            if isinstance(item.get("correlation"), dict)
            else "",
            item.get("meta", {}).get("correlation_id", "")
            if isinstance(item.get("meta"), dict)
            else "",
            item_payload.get("correlation_id", ""),
            item_payload.get("related_task_id", ""),
            item_payload.get("task_id", ""),
            item_trigger_id,
        )
        if correlation_id and item_corr == correlation_id:
            matches.append(item)
        elif related_trigger_id and item_trigger_id == related_trigger_id:
            matches.append(item)
        elif related_task_id and str(item_payload.get("task_id", "") or "") == related_task_id:
            matches.append(item)

    unique_matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in matches:
        item_id = str(item.get("trigger_id", "") or "")
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        unique_matches.append(item)

    related_trigger_ids = [str(item.get("trigger_id", "") or "") for item in unique_matches[:8]]
    related_sources = list(
        dict.fromkeys(
            str(item.get("source", "") or "")
            for item in unique_matches[:8]
            if str(item.get("source", "") or "")
        )
    )
    return {
        "correlation_id": correlation_id,
        "related_trigger_id": related_trigger_id,
        "related_task_id": related_task_id,
        "matched_records": len(unique_matches),
        "related_trigger_ids": related_trigger_ids,
        "related_sources": related_sources,
        "latest_related_status": str(unique_matches[0].get("status", "") or "")
        if unique_matches
        else "",
    }


async def handle_external_trigger(
    agent: Any,
    trigger: Any,
    *,
    ci_context_builder: Callable[[str, dict[str, Any]], dict[str, Any] | None] = (
        build_ci_failure_context
    ),
    remediation_builder: Callable[[dict[str, Any], str], dict[str, Any]] = (
        build_ci_remediation_payload
    ),
) -> dict[str, Any]:
    """Process webhook/cron/federation triggers and persist their outcome."""
    await agent.initialize()
    agent._ensure_autonomy_runtime_state()
    agent.mark_activity("external_trigger")

    if isinstance(trigger, dict):
        trigger = ExternalTrigger(
            trigger_id=str(trigger.get("trigger_id", f"trigger-{int(time.time())}")),
            source=str(trigger.get("source", "external")),
            event_name=str(trigger.get("event_name", "event")),
            payload=dict(trigger.get("payload", {}) or {}),
            meta=dict(trigger.get("meta", {}) or {}),
        )

    payload_dict = agent._trigger_payload(trigger)
    event_name = str(agent._trigger_attr(trigger, "event_name", "event"))
    ci_context = (
        payload_dict
        if payload_dict.get("kind") in {"workflow_run", "check_run", "check_suite"}
        and payload_dict.get("workflow_name")
        else ci_context_builder(event_name, payload_dict)
    )
    correlation = agent._build_trigger_correlation(trigger, payload_dict)
    prompt = agent._build_trigger_prompt(trigger, payload_dict, ci_context)
    started_at = time.time()
    status = "success"
    summary = ""
    remediation: dict[str, Any] | None = None
    try:
        revision_identity = str(
            (ci_context or {}).get("sha")
            or (ci_context or {}).get("run_id")
            or (ci_context or {}).get("branch")
            or "unknown"
        ).strip()
        preflight_attempt_key = "|".join(
            (
                str((ci_context or {}).get("repo", "") or "").strip(),
                str((ci_context or {}).get("workflow_name", "") or "").strip(),
                revision_identity,
            )
        )
        preflight_limit = 1 if (ci_context or {}).get("human_approval_required") else 2
        attempts_used = getattr(agent, "_self_heal_attempts", {}).get(preflight_attempt_key, 0)
        if (
            ci_context
            and bool(getattr(agent.cfg, "ENABLE_AUTONOMOUS_SELF_HEAL", False))
            and attempts_used >= preflight_limit
        ):
            status = "circuit_open"
            summary = (
                "Self-heal circuit breaker açık; aynı CI revision için yeni teşhis/patch "
                "LLM çağrısı yapılmadı."
            )
            remediation = remediation_builder(ci_context, summary)
            remediation["remediation_loop"]["status"] = "circuit_open"
            remediation["self_heal_execution"] = {
                "status": "circuit_open",
                "summary": summary,
                "attempt_key": preflight_attempt_key,
                "attempts_used": attempts_used,
                "max_auto_attempts": preflight_limit,
            }
        else:
            summary = await agent._try_multi_agent(prompt)
        if not isinstance(summary, str) or not summary.strip():
            status = "empty"
            summary = "⚠ Proaktif tetik işlendikten sonra boş çıktı üretildi."
        elif ci_context and remediation is None:
            remediation = remediation_builder(ci_context, summary)
            try:
                await agent._attempt_autonomous_self_heal(
                    ci_context=ci_context,
                    diagnosis=summary,
                    remediation=remediation,
                )
            except Exception as exc:
                logger.exception(
                    "Autonomous self-heal execution failed for trigger_id=%s",
                    trigger.trigger_id,
                )
                remediation["self_heal_execution"] = {
                    "status": "failed",
                    "summary": f"Autonomous self-heal hata verdi: {exc}",
                }
    except Exception as exc:
        logger.exception(
            "External autonomy trigger processing failed: source=%s event=%s",
            agent._trigger_attr(trigger, "source", "external"),
            event_name,
        )
        status = "failed"
        summary = f"⚠ Proaktif tetik işlenemedi: {exc}"

    record = {
        "trigger_id": str(agent._trigger_attr(trigger, "trigger_id", "")),
        "source": str(agent._trigger_attr(trigger, "source", "external")),
        "event_name": event_name,
        "status": status,
        "summary": summary,
        "payload": payload_dict,
        "meta": agent._trigger_meta(trigger),
        "correlation": correlation,
        "prompt": prompt,
        "created_at": started_at,
        "completed_at": time.time(),
    }
    if remediation:
        record["remediation"] = remediation

    await agent._append_autonomy_history(record)
    await agent._memory_add("user", f"[AUTONOMY_TRIGGER] {prompt}")
    await agent._memory_add("assistant", summary)
    return record
