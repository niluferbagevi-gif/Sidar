from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Header, Request
from fastapi.responses import JSONResponse

from web.routes import LegacyExportRouter


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """Normalize config/env boolean values used by webhook compatibility flags."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _github_webhook_signature_required(cfg: Any) -> bool:
    """Return whether GitHub webhook signatures must be validated.

    Signature validation remains enabled by default and is always enforced in
    production. Local/test compatibility can explicitly opt out with
    ``GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False``.
    """
    env_name = (
        str(getattr(cfg, "SIDAR_ENV", "") or os.getenv("SIDAR_ENV", "") or "").strip().lower()
    )
    if env_name == "production":
        return True
    return _coerce_bool(getattr(cfg, "GITHUB_WEBHOOK_REQUIRE_SIGNATURE", None), default=True)


def _validate_github_webhook_signature(
    *,
    payload_body: bytes,
    cfg: Any,
    signature_header: str,
    verify_hmac_signature: Callable[..., None],
    logger: Any,
) -> None:
    """Apply the GitHub webhook signature contract in one testable place."""
    secret_value = str(getattr(cfg, "GITHUB_WEBHOOK_SECRET", "") or "")
    if not secret_value:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET yapılandırılmamış — webhook imza doğrulaması atlanıyor. "
            "Üretim ortamında mutlaka ayarlayın."
        )
        return

    if not _github_webhook_signature_required(cfg):
        logger.warning(
            "GITHUB_WEBHOOK_REQUIRE_SIGNATURE=False — GitHub webhook imza doğrulaması "
            "yalnızca local/test uyumluluğu için atlanıyor."
        )
        return

    verify_hmac_signature(
        payload_body,
        secret_value,
        signature_header,
        label="GitHub webhook",
    )


def build_webhooks_router(
    *,
    cfg: Any,
    cfg_getter: Callable[[], Any] | None = None,
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

    def _active_cfg() -> Any:
        return cfg_getter() if cfg_getter is not None else cfg

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
        active_cfg = _active_cfg()
        _validate_github_webhook_signature(
            payload_body=payload_body,
            cfg=active_cfg,
            signature_header=x_hub_signature_256,
            verify_hmac_signature=verify_hmac_signature,
            logger=logger,
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
            with contextlib.suppress(Exception):
                await await_if_needed(agent.memory.add("user", msg))
                await await_if_needed(
                    agent.memory.add(
                        "assistant",
                        "GitHub bildirimini kayıtlarıma aldım. İstenirse 'github_commits' "
                        "veya PR/Issue araçlarımla detayları inceleyebilirim.",
                    )
                )
            if bool(getattr(active_cfg, "ENABLE_EVENT_WEBHOOKS", True)):
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
