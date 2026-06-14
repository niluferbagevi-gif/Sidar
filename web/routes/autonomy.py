"""Autonomy webhook, wake, and activity HTTP routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class AutonomyWakeRequest(BaseModel):
    event_name: str = Field("manual_wake", description="Manuel/proaktif tetik olay adı")
    prompt: str = Field(..., description="Ajanın değerlendireceği proaktif prompt")
    source: str = Field("manual", description="Tetik kaynağı etiketi")
    payload: dict[str, Any] = Field(default_factory=dict, description="Ek olay payload'u")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek meta verisi")


_deps_factory: Callable[[], Any] | None = None
router = APIRouter()


def configure_autonomy_dependencies(deps_factory: Callable[[], Any]) -> None:
    global _deps_factory
    _deps_factory = deps_factory


def _deps() -> Any:
    if _deps_factory is None:  # pragma: no cover - configuration guard
        raise RuntimeError("Autonomy route dependencies are not configured.")
    return _deps_factory()


def build_autonomy_router(deps_factory: Callable[[], Any]) -> APIRouter:
    configure_autonomy_dependencies(deps_factory)
    return router


@router.post(
    "/api/autonomy/webhook/{source}",
    summary="Otonom Webhook Tetikleyicisi",
    description="Harici sistem olaylarını Sidar'a otonom trigger olarak iletir.",
)
async def autonomy_webhook(
    source: str,
    request: Request,
    x_sidar_signature: str = Header(default=""),
) -> JSONResponse:
    """Genel amaçlı webhook olaylarını ajanın proaktif değerlendirmesine iletir."""
    deps = _deps()
    if not bool(getattr(deps.cfg, "ENABLE_EVENT_WEBHOOKS", True)):
        raise HTTPException(status_code=503, detail="Event webhook özelliği devre dışı.")

    payload_body = await request.body()
    deps.verify_hmac_signature(
        payload_body,
        str(getattr(deps.cfg, "AUTONOMY_WEBHOOK_SECRET", "") or ""),
        x_sidar_signature,
        label="Autonomy webhook",
    )

    try:
        data = json.loads(payload_body.decode("utf-8")) if payload_body else {}
    except json.JSONDecodeError:
        return JSONResponse({"success": False, "error": "Geçersiz JSON payload'u"}, status_code=400)

    payload_dict = data if isinstance(data, dict) else {"payload": data}
    resolved_event_name = str(payload_dict.get("event_name", source) or source)
    ci_context = deps.resolve_ci_failure_context(resolved_event_name, payload_dict)
    federation_workflow = (
        None
        if ci_context
        else await deps.await_if_needed(
            deps.run_event_driven_federation_workflow(
                source=source,
                event_name=resolved_event_name,
                payload=payload_dict,
            )
        )
    )
    dispatch_payload = ci_context if ci_context else payload_dict
    dispatch_meta = {
        "source": source,
        "provider": source,
        "ci_failure": "true" if ci_context else "false",
    }
    if federation_workflow:
        dispatch_payload = deps.embed_event_driven_federation_payload(payload_dict, federation_workflow)
        dispatch_meta.update(
            {
                "event_driven_federation": "true",
                "workflow_type": str(federation_workflow.get("workflow_type") or "external_event"),
                "correlation_id": str(federation_workflow.get("correlation_id") or ""),
            }
        )
    result = await deps.await_if_needed(
        deps.dispatch_autonomy_trigger(
            trigger_source=f"webhook:{source}:ci_failure" if ci_context else f"webhook:{source}",
            event_name="ci_failure_remediation" if ci_context else resolved_event_name,
            payload=dispatch_payload,
            meta=dispatch_meta,
        )
    )
    return JSONResponse(
        {"success": True, "result": result, "event_driven_federation": federation_workflow}
    )


@router.post(
    "/api/autonomy/wake",
    summary="Manuel Otonomi Uyanışı",
    description="SIDAR'ı kullanıcı veya sistem tarafından proaktif görev için uyandırır.",
)
async def autonomy_wake(req: AutonomyWakeRequest) -> Any:
    """Webhook dışı manuel/proaktif tetik giriş noktası."""
    deps = _deps()
    payload = dict(req.payload or {})
    payload["prompt"] = req.prompt.strip()
    result = await deps.await_if_needed(
        deps.dispatch_autonomy_trigger(
            trigger_source=f"manual:{req.source.strip() or 'manual'}",
            event_name=req.event_name.strip() or "manual_wake",
            payload=payload,
            meta=dict(req.meta or {}),
        )
    )
    return JSONResponse({"success": True, "result": result})


@router.get(
    "/api/autonomy/activity",
    summary="Otonomi Aktivite Akışı",
    description="Webhook/cron/manual kaynaklı son proaktif tetik geçmişini döndürür.",
)
async def autonomy_activity(limit: int = 20) -> Any:
    """Son proaktif tetik kayıtlarını UI ve operasyon panelleri için sunar."""
    deps = _deps()
    agent = await deps.resolve_agent_instance()
    return JSONResponse({"success": True, "activity": agent.get_autonomy_activity(limit=limit)})
