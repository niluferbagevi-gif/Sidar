"""External swarm federation HTTP routes."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class FederationTaskRequest(BaseModel):
    task_id: str = Field(..., description="Dış platform tarafından verilen görev kimliği")
    source_system: str = Field(..., description="Gönderen swarm platformu (örn. crewai, autogen)")
    source_agent: str = Field(..., description="Gönderen ajan veya workflow adı")
    target_agent: str = Field("supervisor", description="Sidar içinde hedef ajan/rol")
    goal: str = Field(..., description="Sidar'ın çalıştıracağı hedef görev")
    protocol: str = Field("federation.v1", description="Federation sözleşme sürümü")
    intent: str = Field("mixed", description="Görev intent tipi")
    context: dict[str, str] = Field(default_factory=dict, description="Yapısal bağlam")
    inputs: list[str] = Field(default_factory=list, description="Ek girdiler")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek protokol meta verisi")
    correlation_id: str = Field("", description="Dış sistemlerle iz sürme için korelasyon kimliği")


class FederationFeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="Dış sistem action feedback kaydı kimliği")
    source_system: str = Field(..., description="Feedback gönderen dış sistem")
    source_agent: str = Field(..., description="Feedback gönderen ajan/workflow")
    action_name: str = Field(..., description="Geri besleme verilen aksiyon adı")
    status: str = Field(..., description="Aksiyonun dış sistemdeki durumu")
    summary: str = Field(..., description="İnsan/ajan tarafından üretilen kısa özet")
    related_task_id: str = Field("", description="İlişkili federation task id")
    related_trigger_id: str = Field("", description="İlişkili autonomy trigger id")
    details: dict[str, Any] = Field(default_factory=dict, description="Detay payload")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek protokol meta verisi")
    correlation_id: str = Field("", description="Dış sistemlerle paylaşılan korelasyon kimliği")


_deps_factory: Callable[[], Any] | None = None
router = APIRouter()


def _federation_env_name(cfg: Any) -> str:
    return str(getattr(cfg, "SIDAR_ENV", "") or os.getenv("SIDAR_ENV", "") or "").strip().lower()


def _resolve_federation_secret(cfg: Any) -> str:
    secret = str(getattr(cfg, "SWARM_FEDERATION_SHARED_SECRET", "") or "")
    if not secret and _federation_env_name(cfg) == "production":
        raise HTTPException(
            status_code=401,
            detail="SWARM_FEDERATION_SHARED_SECRET yapılandırılmadığı için federation imzası doğrulanamadı.",
        )
    return secret


def configure_federation_dependencies(deps_factory: Callable[[], Any]) -> None:
    global _deps_factory
    _deps_factory = deps_factory


def _deps() -> Any:
    if _deps_factory is None:  # pragma: no cover - configuration guard
        raise RuntimeError("Federation route dependencies are not configured.")
    return _deps_factory()


def build_federation_router(deps_factory: Callable[[], Any]) -> APIRouter:
    configure_federation_dependencies(deps_factory)
    return router


@router.post(
    "/api/swarm/federation",
    summary="Dış Swarm Federation Görevi",
    description="CrewAI/AutoGen gibi dış platformlardan gelen görevleri Sidar içinde çalıştırır.",
)
async def swarm_federation_execute(
    req: FederationTaskRequest,
    x_sidar_signature: str = Header(default=""),
) -> Any:
    """Federasyon görevlerini Sidar içinde çalıştırıp yapısal sonuç döndürür."""
    deps = _deps()
    if not bool(getattr(deps.cfg, "ENABLE_SWARM_FEDERATION", True)):
        raise HTTPException(status_code=503, detail="Swarm federation özelliği devre dışı.")

    raw_body = json.dumps(req.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")
    deps.verify_hmac_signature(
        raw_body,
        _resolve_federation_secret(deps.cfg),
        x_sidar_signature,
        label="Federation",
    )

    envelope = deps.federation_task_envelope_cls(
        task_id=req.task_id,
        source_system=req.source_system,
        source_agent=req.source_agent,
        target_system="sidar",
        target_agent=req.target_agent,
        goal=req.goal,
        protocol=deps.normalize_federation_protocol(req.protocol),
        intent=req.intent,
        context=dict(req.context or {}),
        inputs=list(req.inputs or []),
        meta=dict(req.meta or {}),
        correlation_id=req.correlation_id,
    )
    federation_payload = {
        "kind": "federation_task",
        "federation_task": asdict(envelope),
        "federation_prompt": envelope.to_prompt(),
        "task_id": envelope.task_id,
        "source_system": envelope.source_system,
        "source_agent": envelope.source_agent,
        "target_agent": envelope.target_agent,
        "correlation_id": envelope.correlation_id,
    }
    trigger_result = await deps.dispatch_autonomy_trigger(
        trigger_source=f"federation:{envelope.source_system}",
        event_name="federation_task",
        payload=federation_payload,
        meta={
            "protocol": envelope.protocol,
            "protocol_legacy_alias": deps.legacy_federation_protocol_v1,
            "correlation_id": envelope.correlation_id,
        },
    )
    summary = str(trigger_result.get("summary", "") or "").strip()
    result = deps.federation_task_result_cls(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent=envelope.target_agent,
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status="success" if summary else "failed",
        summary=summary or "Sidar görev için çıktı üretemedi.",
        protocol=envelope.protocol,
        correlation_id=envelope.correlation_id,
        meta={
            "protocol": envelope.protocol,
            "protocol_legacy_alias": deps.legacy_federation_protocol_v1,
            "correlation_id": envelope.correlation_id,
            "autonomy_trigger_id": str(trigger_result.get("trigger_id", "") or ""),
            "action_feedback_endpoint": "/api/swarm/federation/feedback",
        },
    )
    return JSONResponse({"success": True, "result": asdict(result)})


@router.post(
    "/api/swarm/federation/feedback",
    summary="Dış Swarm Action Feedback",
    description="Dış swarm sistemlerinden gelen action feedback sinyallerini autonomy korelasyon akışına bağlar.",
)
async def swarm_federation_feedback(
    req: FederationFeedbackRequest,
    x_sidar_signature: str = Header(default=""),
) -> Any:
    deps = _deps()
    if not bool(getattr(deps.cfg, "ENABLE_SWARM_FEDERATION", True)):
        raise HTTPException(status_code=503, detail="Swarm federation özelliği devre dışı.")

    raw_body = json.dumps(req.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")
    deps.verify_hmac_signature(
        raw_body,
        _resolve_federation_secret(deps.cfg),
        x_sidar_signature,
        label="Federation feedback",
    )

    feedback = deps.action_feedback_cls(
        feedback_id=req.feedback_id,
        source_system=req.source_system,
        source_agent=req.source_agent,
        action_name=req.action_name,
        status=req.status,
        summary=req.summary,
        related_task_id=req.related_task_id,
        related_trigger_id=req.related_trigger_id,
        details=dict(req.details or {}),
        meta=dict(req.meta or {}),
        correlation_id=deps.derive_correlation_id(
            req.correlation_id, req.related_task_id, req.related_trigger_id, req.feedback_id
        ),
    )
    trigger = feedback.to_external_trigger()
    result = await deps.dispatch_autonomy_trigger(
        trigger_source=trigger.source,
        event_name=trigger.event_name,
        payload=dict(trigger.payload or {}),
        meta=dict(trigger.meta or {}),
    )
    return JSONResponse(
        {
            "success": True,
            "result": result,
            "feedback": {
                "feedback_id": feedback.feedback_id,
                "correlation_id": feedback.correlation_id,
                "related_task_id": feedback.related_task_id,
                "related_trigger_id": feedback.related_trigger_id,
            },
        }
    )
