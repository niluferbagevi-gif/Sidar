"""Autonomous self-heal orchestration service for :class:`SidarAgent`."""

from __future__ import annotations

import asyncio
from typing import Any, cast


async def attempt_autonomous_self_heal(
    agent: Any,
    *,
    ci_context: dict[str, Any],
    diagnosis: str,
    remediation: dict[str, Any],
    human_approval: bool | None = None,
) -> dict[str, Any]:
    """Run the bounded mechanical/LLM patch workflow through an agent facade."""
    remediation_loop = dict(remediation.get("remediation_loop") or {})
    execution: dict[str, Any]
    if not bool(getattr(agent.cfg, "ENABLE_AUTONOMOUS_SELF_HEAL", False)):
        execution = {"status": "disabled", "summary": "Autonomous self-heal kapalı."}
        remediation["self_heal_execution"] = execution
        return execution
    if str(remediation_loop.get("status", "")).strip() != "planned":
        execution = {"status": "skipped", "summary": "Remediation loop plan durumunda değil."}
        remediation["self_heal_execution"] = execution
        return execution
    if bool(remediation_loop.get("needs_human_approval")):
        default_hitl_decision = (
            str(getattr(agent.cfg, "SELF_HEAL_DEFAULT_DECISION", "prompt")).strip().lower()
        )
        if human_approval is None and default_hitl_decision in {
            "approve",
            "approved",
            "yes",
            "true",
            "1",
        }:
            human_approval = True
        elif human_approval is None and default_hitl_decision in {
            "reject",
            "rejected",
            "no",
            "false",
            "0",
        }:
            human_approval = False
        elif human_approval is None and default_hitl_decision in {
            "prompt",
            "ask",
            "interactive",
        }:
            human_approval = None
        if human_approval is False:
            remediation_loop["status"] = "rejected"
            agent._update_remediation_step(
                remediation_loop,
                "handoff",
                status="rejected",
                detail="HITL onayı reddedildi; self-heal uygulanmadı.",
            )
            execution = cast(
                dict[str, Any],
                {
                    "status": "rejected",
                    "summary": "İnsan onayı verilmediği için self-heal iptal edildi.",
                    "hitl_reasons": list(remediation_loop.get("hitl_reasons") or []),
                },
            )
            remediation["remediation_loop"] = remediation_loop
            remediation["self_heal_execution"] = execution
            return execution
        if human_approval is True:
            remediation_loop["needs_human_approval"] = False
            agent._update_remediation_step(
                remediation_loop,
                "handoff",
                status="running",
                detail="HITL onayı alındı; otonom self-heal devam ediyor.",
            )
        else:
            agent._update_remediation_step(
                remediation_loop,
                "handoff",
                status="awaiting_hitl",
                detail="Riskli remediation otomatik uygulanmadı; HITL onayı bekleniyor.",
            )
            execution = cast(
                dict[str, Any],
                {
                    "status": "awaiting_hitl",
                    "summary": "Risk seviyesi nedeniyle self-heal HITL onayına bırakıldı.",
                    "hitl_reasons": list(remediation_loop.get("hitl_reasons") or []),
                },
            )
            remediation["remediation_loop"] = remediation_loop
            remediation["self_heal_execution"] = execution
            return execution
    if not hasattr(agent, "code") or not hasattr(agent, "llm"):
        execution = {
            "status": "blocked",
            "summary": "Self-heal için code/llm bağımlılıkları hazır değil.",
        }
        remediation["self_heal_execution"] = execution
        return execution

    revision_identity = str(
        ci_context.get("sha") or ci_context.get("run_id") or ci_context.get("branch") or "unknown"
    ).strip()
    attempt_key = (
        "|".join(
            (
                str(ci_context.get("repo", "") or "").strip(),
                str(ci_context.get("workflow_name", "") or "").strip(),
                revision_identity,
            )
        )
        or "default"
    )
    default_max_attempts = 1 if remediation_loop.get("needs_human_approval") else 2
    max_auto_attempts = max(
        1,
        int(remediation_loop.get("max_auto_attempts") or default_max_attempts),
    )
    if not hasattr(agent, "_self_heal_attempts"):
        agent._self_heal_attempts = {}
    attempts_lock = getattr(agent, "_self_heal_attempts_lock", None)
    if attempts_lock is None:
        attempts_lock = asyncio.Lock()
        agent._self_heal_attempts_lock = attempts_lock
    async with attempts_lock:
        attempts_used = agent._self_heal_attempts.get(attempt_key, 0)
        if attempts_used >= max_auto_attempts:
            remediation_loop["status"] = "circuit_open"
            execution = {
                "status": "circuit_open",
                "summary": (
                    "Self-heal deneme limiti aşıldı; yeni otomatik LLM/patch çağrıları "
                    "insan müdahalesine kadar engellendi."
                ),
                "attempt_key": attempt_key,
                "attempts_used": attempts_used,
                "max_auto_attempts": max_auto_attempts,
            }
            remediation["remediation_loop"] = remediation_loop
            remediation["self_heal_execution"] = execution
            return execution
        agent._self_heal_attempts[attempt_key] = attempts_used + 1

    mechanical_execution: dict[str, Any] = await agent._attempt_mechanical_autofix(
        remediation_loop=remediation_loop
    )
    if mechanical_execution.get("status") == "applied":
        agent._self_heal_attempts.pop(attempt_key, None)
        remediation_loop["status"] = "applied"
        agent._update_remediation_step(
            remediation_loop,
            "patch",
            status="completed",
            detail=str(mechanical_execution.get("summary") or ""),
        )
        agent._update_remediation_step(
            remediation_loop,
            "validate",
            status="completed",
            detail="Mekanik autofix sonrası sandbox doğrulamaları geçti.",
        )
        agent._update_remediation_step(
            remediation_loop,
            "handoff",
            status="completed",
            detail="Mekanik autofix (ruff --fix) LLM plan üretimine gerek kalmadan uygulandı.",
        )
        remediation["remediation_loop"] = remediation_loop
        remediation["self_heal_execution"] = mechanical_execution
        return mechanical_execution

    plan = await agent._build_self_heal_plan(
        ci_context=ci_context,
        diagnosis=diagnosis,
        remediation_loop=remediation_loop,
    )
    remediation["self_heal_plan"] = plan
    if not list(plan.get("operations") or []):
        execution = {"status": "blocked", "summary": "LLM patch planı üretilemedi."}
        if int(plan.get("plan_attempt") or 0) >= int(plan.get("plan_max_retries") or 0) > 0:
            remediation_loop["needs_human_intervention"] = True
            agent._update_remediation_step(
                remediation_loop,
                "handoff",
                status="pending",
                detail=("Maksimum self-heal plan retry limiti aşıldı; insan müdahalesi gerekiyor."),
            )
        agent._update_remediation_step(
            remediation_loop,
            "patch",
            status="blocked",
            detail="LLM güvenli patch planı üretemedi.",
        )
        remediation["remediation_loop"] = remediation_loop
        remediation["self_heal_execution"] = execution
        return execution

    agent._update_remediation_step(
        remediation_loop,
        "patch",
        status="running",
        detail="Self-heal patch operasyonları uygulanıyor.",
    )
    execution = await agent._execute_self_heal_plan(remediation_loop=remediation_loop, plan=plan)
    remediation["self_heal_execution"] = execution

    if execution["status"] == "applied":
        agent._self_heal_attempts.pop(attempt_key, None)
        remediation_loop["status"] = "applied"
        agent._update_remediation_step(
            remediation_loop,
            "patch",
            status="completed",
            detail=f"{len(execution.get('operations_applied', []))} patch uygulandı.",
        )
        agent._update_remediation_step(
            remediation_loop,
            "validate",
            status="completed",
            detail="Sandbox doğrulamaları başarıyla geçti.",
        )
        agent._update_remediation_step(
            remediation_loop,
            "handoff",
            status="completed",
            detail="Değişiklikler başarıyla uygulandı; sonraki adım PR/proposal güncellemesi.",
        )
    else:
        remediation_loop["status"] = execution["status"]
        agent._update_remediation_step(
            remediation_loop,
            "patch",
            status="failed",
            detail=execution["summary"],
        )
        agent._update_remediation_step(
            remediation_loop,
            "validate",
            status="failed",
            detail="Self-heal doğrulaması başarısız olduğu için rollback yapıldı.",
        )
    remediation["remediation_loop"] = remediation_loop
    return execution
