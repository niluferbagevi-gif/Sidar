"""Autonomy trigger helpers shared by the web API layer."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from agent.core.contracts import FederationTaskEnvelope, FederationTaskResult
from agent.swarm import SwarmTask


def autonomy_service_actor(config: Any, trigger_source: str) -> tuple[str, str]:
    """Return the explicit service actor used by userless autonomy triggers."""
    configured_user = str(
        getattr(config, "AUTONOMY_SERVICE_USER_ID", "")
        or getattr(config, "SYSTEM_USER_ID", "")
        or "system:autonomy"
    ).strip()
    service_user_id = configured_user or "system:autonomy"
    source_label = str(trigger_source or "external").strip() or "external"
    return service_user_id, f"autonomy:{source_label}"


def trim_autonomy_text(value: Any, limit: int = 1200) -> str:
    """Normalize and truncate webhook/autonomy text fields for prompts and logs."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[truncated]"


def build_event_driven_federation_spec(
    source: str, event_name: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Turn a supported webhook payload (Jira/GitHub/system monitor) into a swarm task spec."""
    from agent.core.contracts import derive_correlation_id

    source_key = str(source or "").strip().lower()
    event_key = str(event_name or "").strip().lower()
    data = dict(payload or {})

    if source_key in {"jira", "atlassian", "jira_cloud"}:
        issue = dict(data.get("issue") or data)
        action = (
            str(data.get("action") or data.get("webhookEvent") or event_key or "").strip().lower()
        )
        issue_key = str(issue.get("key") or issue.get("id") or data.get("issue_key") or "").strip()
        summary = str(
            issue.get("title") or issue.get("summary") or data.get("summary") or ""
        ).strip()
        if issue_key and (
            "created" in action
            or event_key in {"issue_created", "issue_opened", "jira_issue_created"}
        ):
            project_key = str(
                (issue.get("fields") or {}).get("project", {}).get("key")
                or data.get("project")
                or ""
            ).strip()
            return {
                "workflow_type": "jira_issue",
                "task_id": f"jira-{issue_key.lower()}",
                "source_system": "jira",
                "source_agent": "issue_webhook",
                "goal": (
                    f"Jira issue {issue_key} için event-driven swarm remediation/uygulama planı çıkar: {summary or 'başlıksız issue'}. "
                    "Coder uygulanabilir teknik yaklaşımı oluştursun, Reviewer risk/QA/handoff değerlendirsin."
                ),
                "context": {
                    "workflow_type": "jira_issue",
                    "issue_key": issue_key,
                    "issue_summary": summary,
                    "project_key": project_key,
                    "issue_status": str(
                        (issue.get("fields") or {}).get("status", {}).get("name")
                        or data.get("status")
                        or ""
                    ).strip(),
                    "issue_type": str(
                        (issue.get("fields") or {}).get("issuetype", {}).get("name")
                        or data.get("issue_type")
                        or ""
                    ).strip(),
                },
                "inputs": [
                    f"issue_key={issue_key}",
                    f"summary={summary}",
                    f"description={trim_autonomy_text((issue.get('fields') or {}).get('description') or data.get('description') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), issue_key, summary
                ),
            }

    if source_key == "github":
        pr = dict(data.get("pull_request") or {})
        action = str(data.get("action") or event_key or "").strip().lower()
        pr_number = str(pr.get("number") or data.get("number") or "").strip()
        pr_title = str(pr.get("title") or data.get("title") or "").strip()
        if pr_number and action in {"opened", "reopened", "ready_for_review", "synchronize"}:
            repo = str(
                (data.get("repository") or {}).get("full_name") or data.get("repo") or ""
            ).strip()
            return {
                "workflow_type": "github_pull_request",
                "task_id": f"github-pr-{pr_number}",
                "source_system": "github",
                "source_agent": "pull_request_webhook",
                "goal": (
                    f"GitHub PR #{pr_number} ({pr_title or 'başlıksız PR'}) için event-driven swarm incelemesi yap. "
                    "Coder değişiklik/patch/test stratejisini çıkarsın, Reviewer merge riski ve QA kapısını değerlendirsin."
                ),
                "context": {
                    "workflow_type": "github_pull_request",
                    "repo": repo,
                    "pr_number": pr_number,
                    "pr_title": pr_title,
                    "base_branch": str(
                        (pr.get("base") or {}).get("ref") or data.get("base_branch") or ""
                    ).strip(),
                    "head_branch": str(
                        (pr.get("head") or {}).get("ref") or data.get("branch") or ""
                    ).strip(),
                    "author": str(
                        (pr.get("user") or {}).get("login")
                        or data.get("sender", {}).get("login")
                        or ""
                    ).strip(),
                },
                "inputs": [
                    f"pr_number={pr_number}",
                    f"title={pr_title}",
                    f"body={trim_autonomy_text(pr.get('body') or data.get('body') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), pr.get("node_id", ""), pr_number
                ),
            }

    if source_key in {"system_monitor", "monitor", "observability", "system"}:
        severity = (
            str(data.get("severity") or data.get("level") or data.get("status") or "")
            .strip()
            .lower()
        )
        alert_name = str(
            data.get("alert_name") or data.get("service") or data.get("title") or event_key
        ).strip()
        if severity in {"error", "critical", "fatal"} or event_key in {
            "system_error",
            "monitor_alert",
            "incident",
            "error_detected",
        }:
            return {
                "workflow_type": "system_error",
                "task_id": f"system-{secrets.token_hex(4)}",
                "source_system": "system_monitor",
                "source_agent": "alert_webhook",
                "goal": (
                    f"Sistem monitör hatasını değerlendir: {alert_name}. "
                    "Coder muhtemel kök neden ve hotfix adımlarını çıkarsın, Reviewer risk/rollback/QA planını doğrulasın."
                ),
                "context": {
                    "workflow_type": "system_error",
                    "alert_name": alert_name,
                    "severity": severity or "error",
                    "service": str(data.get("service") or "").strip(),
                    "environment": str(data.get("environment") or data.get("env") or "").strip(),
                },
                "inputs": [
                    f"message={trim_autonomy_text(data.get('message') or data.get('summary') or data.get('error') or '', 1000)}",
                    f"stacktrace={trim_autonomy_text(data.get('stacktrace') or data.get('details') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), data.get("alert_id", ""), alert_name
                ),
            }

    return None


def build_swarm_goal_for_role(base_goal: str, role: str, spec: dict[str, Any]) -> str:
    """Render the per-role (coder/reviewer) swarm prompt for an event-driven federation task."""
    context_blob = json.dumps(spec.get("context") or {}, ensure_ascii=False, sort_keys=True)
    inputs_blob = json.dumps(spec.get("inputs") or [], ensure_ascii=False)
    if role == "coder":
        return (
            f"{base_goal}\n\n"
            "[EVENT_DRIVEN_SWARM:CODER]\n"
            "Bu dış olay için inisiyatif al. Muhtemel kod hedeflerini, uygulanabilir adımları, test/komut planını ve gerekiyorsa açılması gereken follow-up'ları üret.\n"
            f"context={context_blob}\ninputs={inputs_blob}"
        )
    return (
        f"{base_goal}\n\n"
        "[EVENT_DRIVEN_SWARM:REVIEWER]\n"
        "Coder çıktısını kalite kapısı olarak incele. Riskler, QA, rollback, insan onayı ve follow-up aksiyonlarını netleştir.\n"
        f"context={context_blob}\ninputs={inputs_blob}"
    )


async def run_event_driven_federation_workflow(
    *,
    source: str,
    event_name: str,
    payload: dict[str, Any],
    cfg: Any,
    spec_builder: Callable[[str, str, dict[str, Any]], dict[str, Any] | None],
    goal_builder: Callable[[str, str, dict[str, Any]], str],
    trim_text: Callable[..., str],
    correlation_id_fn: Callable[..., str],
    orchestrator_cls: Callable[[Any], Any],
) -> dict[str, Any] | None:
    """Build a spec from a webhook event and run it through the swarm orchestrator.

    ``spec_builder``, ``goal_builder``, ``trim_text``, ``correlation_id_fn`` and
    ``orchestrator_cls`` are threaded through explicitly (rather than imported
    directly) so callers — namely web_server.py's thin wrapper — can resolve
    their own current module-global values (including test monkeypatches) at
    call time instead of binding them once at import time.
    """
    spec = spec_builder(source, event_name, payload)
    if spec is None:
        return None

    orchestrator = orchestrator_cls(cfg)
    correlation_id = str(
        spec.get("correlation_id") or correlation_id_fn(spec.get("task_id", ""), event_name)
    ).strip()
    task_context = {
        **{str(k): str(v) for k, v in dict(spec.get("context") or {}).items()},
        "event_name": str(event_name or ""),
        "event_source": str(source or ""),
        "correlation_id": correlation_id,
        "event_payload_excerpt": trim_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), 1200
        ),
    }
    tasks = [
        SwarmTask(
            task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
            goal=goal_builder(str(spec.get("goal") or ""), "coder", spec),
            intent="code",
            context=dict(task_context),
            preferred_agent="coder",
        ),
        SwarmTask(
            task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
            goal=goal_builder(str(spec.get("goal") or ""), "reviewer", spec),
            intent="review",
            context=dict(task_context),
            preferred_agent="reviewer",
        ),
    ]
    pipeline = await orchestrator.run_pipeline(tasks, session_id=correlation_id)
    envelope = FederationTaskEnvelope(
        task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
        source_system=str(spec.get("source_system") or source or "external"),
        source_agent=str(spec.get("source_agent") or "event_webhook"),
        target_system="sidar",
        target_agent="supervisor",
        goal=str(spec.get("goal") or ""),
        intent="mixed",
        context={
            **task_context,
            "workflow_type": str(spec.get("workflow_type") or "external_event"),
        },
        inputs=[str(item) for item in list(spec.get("inputs") or [])],
        meta={"initiative": "event_driven_swarm", "event_name": str(event_name or "")},
        correlation_id=correlation_id,
    )
    coder_result = pipeline[0] if pipeline else None
    reviewer_result = pipeline[-1] if pipeline else None
    reviewer_summary = trim_text(
        getattr(reviewer_result, "summary", "") or getattr(coder_result, "summary", "") or "", 2400
    )
    fed_result = FederationTaskResult(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent="supervisor",
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status=(
            getattr(reviewer_result, "status", "")
            or getattr(coder_result, "status", "")
            or "failed"
        ),
        summary=reviewer_summary or "Event-driven swarm sonucu üretilemedi.",
        protocol=envelope.protocol,
        evidence=[
            trim_text(getattr(item, "summary", "") or "", 800)
            for item in pipeline
            if getattr(item, "summary", "")
        ],
        next_actions=[
            f"coder_status={getattr(coder_result, 'status', 'n/a')}",
            f"reviewer_status={getattr(reviewer_result, 'status', 'n/a')}",
            f"workflow_type={spec.get('workflow_type', 'external_event')}",
        ],
        meta={
            "workflow_type": str(spec.get("workflow_type") or "external_event"),
            "initiative": "event_driven_swarm",
            "correlation_id": correlation_id,
            "event_name": str(event_name or ""),
        },
        correlation_id=correlation_id,
    )
    federation_prompt = (
        envelope.to_prompt()
        + "\n\n[SWARM_PIPELINE_RESULT]\n"
        + f"workflow_type={spec.get('workflow_type', 'external_event')}\n"
        + f"coder_summary={trim_text(getattr(coder_result, 'summary', '') or '', 1200)}\n"
        + f"reviewer_summary={reviewer_summary or '-'}"
    )
    return {
        "workflow_type": str(spec.get("workflow_type") or "external_event"),
        "correlation_id": correlation_id,
        "federation_task": asdict(envelope),
        "federation_result": asdict(fed_result),
        "pipeline": [asdict(item) for item in pipeline],
        "federation_prompt": federation_prompt,
    }


def embed_event_driven_federation_payload(
    base_payload: dict[str, Any], workflow: dict[str, Any]
) -> dict[str, Any]:
    """Project an event-driven federation workflow result into an autonomy trigger payload."""
    return {
        "kind": "federation_task",
        "federation_task": dict(workflow.get("federation_task") or {}),
        "federation_prompt": str(workflow.get("federation_prompt") or ""),
        "event_payload": dict(base_payload or {}),
        "event_driven_federation": dict(workflow or {}),
        "task_id": str((workflow.get("federation_task") or {}).get("task_id", "") or ""),
        "source_system": str(
            (workflow.get("federation_task") or {}).get("source_system", "") or ""
        ),
        "source_agent": str((workflow.get("federation_task") or {}).get("source_agent", "") or ""),
        "target_agent": str((workflow.get("federation_task") or {}).get("target_agent", "") or ""),
        "correlation_id": str(workflow.get("correlation_id") or ""),
    }
