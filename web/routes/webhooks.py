from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Header, Request
from fastapi.responses import JSONResponse

from web.routes import LegacyExportRouter



def build_webhooks_router(
    *,
    cfg: Any,
    logger: Any,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    verify_hmac_signature: Callable[..., None],
    resolve_ci_failure_context: Callable[[str, dict[str, Any]], dict[str, Any] | None],
    run_event_driven_federation_workflow: Callable[..., Awaitable[Any] | Any],
    embed_event_driven_federation_payload: Callable[[dict[str, Any], Any], Any],
    dispatch_autonomy_trigger: Callable[..., Awaitable[Any] | Any],
) -> LegacyExportRouter:
    """Build external webhook routes."""

    router = LegacyExportRouter()

    @router.post(
        "/api/webhook",
        summary="GitHub Webhook Alıcısı",
        description="GitHub repository'sinden gelen Push, PR ve Issue olaylarını dinler ve doğrular.",
        responses={
            200: {"description": "Webhook başarıyla işlendi"},
            401: {"description": "Geçersiz imza"},
        },
    )
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default=""),
        x_hub_signature_256: str = Header(default=""),
    ) -> Any:
        """GitHub'dan gelen webhook tetiklemelerini karşılar."""
        payload_body = await request.body()
        # Determine environment; skip signature verification in test environments
        env_name = str(
            getattr(cfg, "SIDAR_ENV", "") or os.getenv("SIDAR_ENV", "")
        ).strip().lower()
        secret = getattr(cfg, "GITHUB_WEBHOOK_SECRET", "").encode("utf-8")
        if env_name in {"test", "testing"}:
            secret = b""

        if not secret:
            logger.warning(
                "GITHUB_WEBHOOK_SECRET yapılandırılmamış — webhook imza doğrulaması atlanıyor. "
                "Üretim ortamında mutlaka ayarlayın."
            )
        if secret:
            verify_hmac_signature(
                payload_body,
                secret.decode("utf-8"),
                x_hub_signature_256,
                label="GitHub webhook",
            )

        try:
            data = json.loads(payload_body.decode("utf-8"))
        except json.JSONDecodeError:
            return JSONResponse(
                {"success": False, "error": "Geçersiz JSON payload'u"}, status_code=400
            )

        if not isinstance(data, dict):
            data = {"payload": data}

        agent = await resolve_agent_instance()
        msg = ""

        if x_github_event == "push":
            pusher = data.get("pusher", {}).get("name", "Biri")
            ref = data.get("ref", "")
            branch = ref.split("/")[-1] if "/" in ref else ref
            msg = (
                f"[GITHUB BİLDİRİMİ] '{pusher}' adlı kullanıcı '{branch}' "
                "dalına yeni kod yükledi (push)."
            )
        elif x_github_event == "pull_request":
            action = data.get("action")
            pr_title = data.get("pull_request", {}).get("title", "")
            pr_num = data.get("pull_request", {}).get("number", "")
            msg = (
                f"[GITHUB BİLDİRİMİ] Pull Request #{pr_num} "
                f"durumu güncellendi ({action}): {pr_title}"
            )
        elif x_github_event == "issues":
            action = data.get("action")
            issue_title = data.get("issue", {}).get("title", "")
            issue_num = data.get("issue", {}).get("number", "")
            msg = (
                f"[GITHUB BİLDİRİMİ] Issue #{issue_num} "
                f"durumu güncellendi ({action}): {issue_title}"
            )

        ci_context = resolve_ci_failure_context(x_github_event, data)
        if ci_context:
            msg = (
                "[GITHUB CI] Başarısız pipeline algılandı: "
                f"{ci_context.get('workflow_name', x_github_event)} "
                f"(run_id={ci_context.get('run_id', '-')}, "
                f"conclusion={ci_context.get('conclusion', '-')})"
            )

        if msg:
            logger.info("Webhook işlendi: %s", msg)
            await await_if_needed(agent.memory.add("user", msg))
            await await_if_needed(
                agent.memory.add(
                    "assistant",
                    "GitHub bildirimini kayıtlarıma aldım. İstenirse 'github_commits' "
                    "veya PR/Issue araçlarımla detayları inceleyebilirim.",
                )
            )
            if bool(getattr(cfg, "ENABLE_EVENT_WEBHOOKS", True)):
                with contextlib.suppress(Exception):
                    payload_dict = data if isinstance(data, dict) else {"payload": data}
                    federation_workflow = (
                        None
                        if ci_context
                        else await await_if_needed(
                            run_event_driven_federation_workflow(
                                source="github",
                                event_name=x_github_event,
                                payload=payload_dict,
                            )
                        )
                    )
                    dispatch_payload = ci_context if ci_context else payload_dict
                    dispatch_meta = {
                        "source": "github",
                        "provider": "github",
                        "ci_failure": "true" if ci_context else "false",
                    }
                    if federation_workflow:
                        dispatch_payload = embed_event_driven_federation_payload(
                            payload_dict, federation_workflow
                        )
                        dispatch_meta.update(
                            {
                                "event_driven_federation": "true",
                                "workflow_type": str(
                                    federation_workflow.get("workflow_type") or "external_event"
                                ),
                                "correlation_id": str(
                                    federation_workflow.get("correlation_id") or ""
                                ),
                            }
                        )
                    await await_if_needed(
                        dispatch_autonomy_trigger(
                            trigger_source="webhook:github:ci_failure"
                            if ci_context
                            else "webhook:github",
                            event_name="ci_failure_remediation" if ci_context else x_github_event,
                            payload=dispatch_payload,
                            meta=dispatch_meta,
                        )
                    )

        return JSONResponse({"success": True, "event": x_github_event, "message": "İşlendi"})

    router.legacy_exports = {"github_webhook": github_webhook}
    return router
