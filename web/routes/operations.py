"""Operations, Poyraz bridge, and Coverage QA HTTP routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class OperationChecklistCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    items: list[str] = Field(default_factory=list)
    status: str = Field(default="pending", min_length=1, max_length=32)


class ContentAssetCreateRequest(BaseModel):
    asset_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1)
    channel: str = Field(default="", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    channel: str = Field(default="", max_length=64)
    objective: str = Field(default="", max_length=400)
    status: str = Field(default="draft", min_length=1, max_length=32)
    budget: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_assets: list[ContentAssetCreateRequest] = Field(default_factory=list)
    initial_checklists: list[OperationChecklistCreateRequest] = Field(default_factory=list)


class PoyrazToolRunRequest(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    room_id: str = Field(default="ops:control", max_length=120)


class LandingPageDraftRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=160)
    offer: str = Field(..., min_length=1, max_length=600)
    audience: str = Field(..., min_length=1, max_length=400)
    call_to_action: str = Field(..., min_length=1, max_length=160)
    tone: str = Field(default="professional", max_length=64)
    sections: list[str] = Field(default_factory=list)
    campaign_id: int | None = Field(default=None)
    store_asset: bool = Field(default=False)
    asset_title: str = Field(default="Landing Page Taslağı", max_length=160)
    channel: str = Field(default="web", max_length=64)
    room_id: str = Field(default="ops:control", max_length=120)


class CampaignCopyGenerateRequest(BaseModel):
    campaign_name: str = Field(..., min_length=1, max_length=160)
    objective: str = Field(..., min_length=1, max_length=400)
    audience: str = Field(..., min_length=1, max_length=400)
    channels: list[str] = Field(default_factory=list)
    offer: str = Field(default="", max_length=600)
    tone: str = Field(default="professional", max_length=64)
    call_to_action: str = Field(default="", max_length=160)
    campaign_id: int | None = Field(default=None)
    store_asset: bool = Field(default=False)
    asset_title: str = Field(default="Kampanya Kopyası", max_length=160)
    room_id: str = Field(default="ops:control", max_length=120)


class ServiceOperationsPlanRequest(BaseModel):
    campaign_id: int | None = Field(default=None)
    campaign_name: str = Field(default="", max_length=160)
    service_name: str = Field(default="", max_length=160)
    audience: str = Field(default="", max_length=400)
    menu_plan: dict[str, list[str]] = Field(default_factory=dict)
    vendor_assignments: dict[str, str] = Field(default_factory=dict)
    timeline: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    persist_checklist: bool = Field(default=True)
    checklist_title: str = Field(default="Operasyon Planı", max_length=160)
    room_id: str = Field(default="ops:control", max_length=120)


class CoverageAnalyzeRequest(BaseModel):
    coverage_xml: str = Field(default="coverage.xml", max_length=512)
    coveragerc: str = Field(default=".coveragerc", max_length=512)
    coverage_output: str = Field(default="")
    limit: int = Field(default=25, ge=1, le=200)
    room_id: str = Field(default="qa:coverage", max_length=120)


class CoverageGenerateRequest(BaseModel):
    coverage_finding: dict[str, Any] = Field(default_factory=dict)
    coveragerc: dict[str, Any] = Field(default_factory=dict)
    target_path: str = Field(default="", max_length=512)
    pytest_output: str = Field(default="")
    analysis: dict[str, Any] = Field(default_factory=dict)
    room_id: str = Field(default="qa:coverage", max_length=120)


class CoverageBatchRequest(BaseModel):
    coverage_xml: str = Field(default="coverage.xml", max_length=512)
    coveragerc: str = Field(default=".coveragerc", max_length=512)
    limit: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=1, ge=1, le=10)
    append: bool = Field(default=True)
    room_id: str = Field(default="qa:coverage", max_length=120)


_deps_factory: Callable[[], Any] | None = None
router = APIRouter()


def configure_operations_dependencies(deps_factory: Callable[[], Any]) -> None:
    global _deps_factory
    _deps_factory = deps_factory


def _deps() -> Any:
    if _deps_factory is None:  # pragma: no cover - configuration guard
        raise RuntimeError("Operations route dependencies are not configured.")
    return _deps_factory()


async def _get_request_user_proxy(request: Request) -> Any:
    return await _deps().get_request_user(request)


def build_operations_router(deps_factory: Callable[[], Any]) -> APIRouter:
    configure_operations_dependencies(deps_factory)
    return router


def serialize_campaign(record: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "name": str(getattr(record, "name", "") or ""),
        "channel": str(getattr(record, "channel", "") or ""),
        "objective": str(getattr(record, "objective", "") or ""),
        "status": str(getattr(record, "status", "draft") or "draft"),
        "owner_user_id": str(getattr(record, "owner_user_id", "") or ""),
        "budget": float(getattr(record, "budget", 0.0) or 0.0),
        "metadata_json": str(getattr(record, "metadata_json", "{}") or "{}"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def serialize_content_asset(record: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "campaign_id": int(getattr(record, "campaign_id", 0) or 0),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "asset_type": str(getattr(record, "asset_type", "") or ""),
        "title": str(getattr(record, "title", "") or ""),
        "content": str(getattr(record, "content", "") or ""),
        "channel": str(getattr(record, "channel", "") or ""),
        "metadata_json": str(getattr(record, "metadata_json", "{}") or "{}"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def serialize_operation_checklist(record: Any) -> dict[str, Any]:
    campaign_id = getattr(record, "campaign_id", None)
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "campaign_id": None if campaign_id is None else int(campaign_id),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "title": str(getattr(record, "title", "") or ""),
        "items_json": str(getattr(record, "items_json", "[]") or "[]"),
        "status": str(getattr(record, "status", "pending") or "pending"),
        "owner_user_id": str(getattr(record, "owner_user_id", "") or ""),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def decode_agent_tool_result(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    text_result = str(raw_result or "")
    try:
        parsed = json.loads(text_result)
    except json.JSONDecodeError:
        return {"success": bool(text_result.strip()), "output": text_result}
    if isinstance(parsed, dict):
        return parsed
    return {"success": True, "output": parsed}


def _database_unavailable_response() -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "error": "database_unavailable",
            "message": "Veritabanı geçici olarak kullanılamıyor.",
        },
        status_code=503,
    )


async def _resolve_operations_db(deps: Any) -> Any:
    agent = await deps.resolve_agent_instance()
    return agent.memory.db


def serialize_coverage_task(record: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "requester_role": str(getattr(record, "requester_role", "") or ""),
        "command": str(getattr(record, "command", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "target_path": str(getattr(record, "target_path", "") or ""),
        "suggested_test_path": str(getattr(record, "suggested_test_path", "") or ""),
        "review_payload_json": str(getattr(record, "review_payload_json", "{}") or "{}"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


@router.get(
    "/api/operations/campaigns", summary="Operasyon Kampanyalarını Listele", tags=["Operations"]
)
async def api_operations_list_campaigns(
    status: str = "",
    limit: int = 50,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        campaigns = await db.list_marketing_campaigns(
            tenant_id=deps.get_user_tenant(_user), status=status, limit=limit
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse(
        {"success": True, "campaigns": [serialize_campaign(item) for item in campaigns]}
    )


@router.post(
    "/api/operations/campaigns", summary="Operasyon Kampanyası Oluştur", tags=["Operations"]
)
async def api_operations_create_campaign(
    req: CampaignCreateRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        tenant_id = deps.get_user_tenant(_user)
        campaign = await db.upsert_marketing_campaign(
            tenant_id=tenant_id,
            name=req.name,
            channel=req.channel,
            objective=req.objective,
            status=req.status,
            owner_user_id=str(getattr(_user, "id", "") or ""),
            budget=float(req.budget or 0.0),
            metadata=dict(req.metadata or {}),
        )
        assets = [
            await db.add_content_asset(
                campaign_id=int(campaign.id),
                tenant_id=tenant_id,
                asset_type=item.asset_type,
                title=item.title,
                content=item.content,
                channel=item.channel,
                metadata=dict(item.metadata or {}),
            )
            for item in req.initial_assets
        ]
        checklists = [
            await db.add_operation_checklist(
                campaign_id=int(campaign.id),
                tenant_id=tenant_id,
                title=item.title,
                items=list(item.items or []),
                status=item.status,
                owner_user_id=str(getattr(_user, "id", "") or ""),
            )
            for item in req.initial_checklists
        ]
    except Exception:
        return _database_unavailable_response()
    return JSONResponse(
        {
            "success": True,
            "campaign": serialize_campaign(campaign),
            "assets": [serialize_content_asset(item) for item in assets],
            "checklists": [serialize_operation_checklist(item) for item in checklists],
        }
    )


@router.get(
    "/api/operations/campaigns/{campaign_id}/assets",
    summary="Kampanya İçerik Varlıklarını Listele",
    tags=["Operations"],
)
async def api_operations_list_assets(
    campaign_id: int,
    limit: int = 100,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        assets = await db.list_content_assets(
            tenant_id=deps.get_user_tenant(_user), campaign_id=campaign_id, limit=limit
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse(
        {"success": True, "assets": [serialize_content_asset(item) for item in assets]}
    )


@router.post(
    "/api/operations/campaigns/{campaign_id}/assets",
    summary="Kampanyaya İçerik Varlığı Ekle",
    tags=["Operations"],
)
async def api_operations_add_asset(
    campaign_id: int,
    req: ContentAssetCreateRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        asset = await db.add_content_asset(
            campaign_id=campaign_id,
            tenant_id=deps.get_user_tenant(_user),
            asset_type=req.asset_type,
            title=req.title,
            content=req.content,
            channel=req.channel,
            metadata=dict(req.metadata or {}),
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse({"success": True, "asset": serialize_content_asset(asset)})


@router.get(
    "/api/operations/campaigns/{campaign_id}/checklists",
    summary="Kampanya Operasyon Checklistlerini Listele",
    tags=["Operations"],
)
async def api_operations_list_checklists(
    campaign_id: int,
    limit: int = 100,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        checklists = await db.list_operation_checklists(
            tenant_id=deps.get_user_tenant(_user), campaign_id=campaign_id, limit=limit
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse(
        {
            "success": True,
            "checklists": [serialize_operation_checklist(item) for item in checklists],
        }
    )


@router.post(
    "/api/operations/campaigns/{campaign_id}/checklists",
    summary="Kampanyaya Operasyon Checklisti Ekle",
    tags=["Operations"],
)
async def api_operations_add_checklist(
    campaign_id: int,
    req: OperationChecklistCreateRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        checklist = await db.add_operation_checklist(
            campaign_id=campaign_id,
            tenant_id=deps.get_user_tenant(_user),
            title=req.title,
            items=list(req.items or []),
            status=req.status,
            owner_user_id=str(getattr(_user, "id", "") or ""),
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse({"success": True, "checklist": serialize_operation_checklist(checklist)})


async def _run_poyraz_tool(req: Any, _user: Any, tool_name: str, payload: dict[str, Any]) -> Any:
    deps = _deps()
    await deps.emit_control_room_event(
        req.room_id,
        kind="tool_call",
        source="poyraz",
        content=f"Poyraz aracı başlatıldı: {tool_name}",
        payload={"tool": tool_name},
    )
    poyraz = await deps.await_if_needed(deps.get_poyraz_agent_instance())
    raw_result = await poyraz.run_task(f"{tool_name}|{json.dumps(payload, ensure_ascii=False)}")
    result = decode_agent_tool_result(raw_result)
    await deps.emit_control_room_event(
        req.room_id,
        kind="status",
        source="poyraz",
        content=f"Poyraz aracı tamamlandı: {tool_name}",
        payload={"tool": tool_name, "success": bool(result.get("success", True))},
    )
    return raw_result, result


@router.post(
    "/api/operations/poyraz/run", summary="Poyraz operasyon aracını çalıştır", tags=["Operations"]
)
async def api_operations_poyraz_run(
    req: PoyrazToolRunRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    allowed_tools = {
        "build_landing_page",
        "generate_campaign_copy",
        "create_marketing_campaign",
        "store_content_asset",
        "create_operation_checklist",
        "plan_service_operations",
        "ingest_video_insights",
    }
    tool_name = req.tool_name.strip()
    if tool_name not in allowed_tools:
        raise HTTPException(
            status_code=400, detail="Bu Poyraz aracı REST operasyon köprüsünde desteklenmiyor."
        )
    payload = {**dict(req.payload or {}), "tenant_id": deps.get_user_tenant(_user)}
    if "owner_user_id" not in payload:
        payload["owner_user_id"] = str(getattr(_user, "id", "") or "")
    _raw_result, result = await _run_poyraz_tool(req, _user, tool_name, payload)
    return JSONResponse(
        {"success": bool(result.get("success", True)), "tool": tool_name, "result": result}
    )


async def _run_named_poyraz_request(
    req: Any, _user: Any, tool_name: str, started: str, completed: str
) -> JSONResponse:
    deps = _deps()
    payload = req.model_dump()
    payload.pop("room_id", None)
    payload["tenant_id"] = deps.get_user_tenant(_user)
    if tool_name == "plan_service_operations":
        payload["owner_user_id"] = str(getattr(_user, "id", "") or "")
    await deps.emit_control_room_event(
        req.room_id, kind="tool_call", source="poyraz", content=started
    )
    poyraz = await deps.await_if_needed(deps.get_poyraz_agent_instance())
    raw_result = await poyraz.run_task(f"{tool_name}|{json.dumps(payload, ensure_ascii=False)}")
    result = decode_agent_tool_result(raw_result)
    await deps.emit_control_room_event(
        req.room_id,
        kind="status",
        source="poyraz",
        content=completed,
        payload={"success": bool(result.get("success", True))}
        if tool_name == "plan_service_operations"
        else None,
    )
    if tool_name == "plan_service_operations":
        return JSONResponse({"success": bool(result.get("success", True)), "result": result})
    return JSONResponse(
        {"success": True, "output": result.get("output", raw_result), "result": result}
    )


@router.post(
    "/api/operations/landing-page", summary="Poyraz landing page taslağı üret", tags=["Operations"]
)
async def api_operations_generate_landing_page(
    req: LandingPageDraftRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    return await _run_named_poyraz_request(
        req,
        _user,
        "build_landing_page",
        "Landing page üretimi başlatıldı.",
        "Landing page üretimi tamamlandı.",
    )


@router.post(
    "/api/operations/campaign-copy", summary="Poyraz kampanya kopyası üret", tags=["Operations"]
)
async def api_operations_generate_campaign_copy(
    req: CampaignCopyGenerateRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    return await _run_named_poyraz_request(
        req,
        _user,
        "generate_campaign_copy",
        "Kampanya kopyası üretimi başlatıldı.",
        "Kampanya kopyası üretimi tamamlandı.",
    )


@router.post(
    "/api/operations/service-plan",
    summary="Poyraz servis operasyon planı üret",
    tags=["Operations"],
)
async def api_operations_plan_service(
    req: ServiceOperationsPlanRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    return await _run_named_poyraz_request(
        req,
        _user,
        "plan_service_operations",
        "Servis operasyon planı başlatıldı.",
        "Servis operasyon planı tamamlandı.",
    )


@router.get(
    "/api/qa/coverage/tasks", summary="Coverage görev geçmişini listele", tags=["QA", "Coverage"]
)
async def api_qa_coverage_tasks(
    status: str = "",
    limit: int = 50,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    try:
        db = await _resolve_operations_db(deps)
        tasks = await db.list_coverage_tasks(
            tenant_id=deps.get_user_tenant(_user), status=status or None, limit=limit
        )
    except Exception:
        return _database_unavailable_response()
    return JSONResponse(
        {"success": True, "tasks": [serialize_coverage_task(item) for item in tasks]}
    )


@router.post(
    "/api/qa/coverage/analyze", summary="Coverage raporunu analiz et", tags=["QA", "Coverage"]
)
async def api_qa_coverage_analyze(
    req: CoverageAnalyzeRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    coverage_agent = await deps.await_if_needed(deps.get_coverage_agent_instance())
    payload = req.model_dump()
    payload.pop("room_id", None)
    await deps.emit_control_room_event(
        req.room_id, kind="tool_call", source="coverage", content="Coverage analizi başlatıldı."
    )
    raw_result = await coverage_agent._tool_analyze_coverage_report(
        json.dumps(payload, ensure_ascii=False)
    )
    result = decode_agent_tool_result(raw_result)
    await deps.emit_control_room_event(
        req.room_id, kind="status", source="coverage", content="Coverage analizi tamamlandı."
    )
    return JSONResponse(
        {"success": True, "analysis": result, "tenant_id": deps.get_user_tenant(_user)}
    )


@router.post(
    "/api/qa/coverage/generate",
    summary="Coverage bulgusu için test adayı üret",
    tags=["QA", "Coverage"],
)
async def api_qa_coverage_generate(
    req: CoverageGenerateRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    coverage_agent = await deps.await_if_needed(deps.get_coverage_agent_instance())
    payload = req.model_dump()
    payload.pop("room_id", None)
    await deps.emit_control_room_event(
        req.room_id,
        kind="tool_call",
        source="coverage",
        content="Coverage test adayı üretimi başlatıldı.",
    )
    raw_candidate = await coverage_agent._tool_generate_missing_tests(
        json.dumps(payload, ensure_ascii=False)
    )
    rejection_reason = coverage_agent._candidate_rejection_reason(
        str(raw_candidate or ""), finding=dict(req.coverage_finding or {})
    )
    await deps.emit_control_room_event(
        req.room_id,
        kind="status",
        source="coverage",
        content="Coverage test adayı kalite kontrolünden geçti."
        if not rejection_reason
        else "Coverage test adayı kalite kapısında reddedildi.",
        payload={"quality_rejection_reason": rejection_reason},
    )
    return JSONResponse(
        {
            "success": not bool(rejection_reason),
            "candidate": str(raw_candidate or ""),
            "quality_rejection_reason": rejection_reason,
            "tenant_id": deps.get_user_tenant(_user),
        }
    )


@router.post(
    "/api/qa/coverage/batch",
    summary="CoverageAgent otonom batch iyileştirme çalıştır",
    tags=["QA", "Coverage"],
)
async def api_qa_coverage_batch(
    req: CoverageBatchRequest,
    _user: Any = Depends(_get_request_user_proxy),
) -> JSONResponse:
    deps = _deps()
    coverage_agent = await deps.await_if_needed(deps.get_coverage_agent_instance())
    await deps.emit_control_room_event(
        req.room_id,
        kind="tool_call",
        source="coverage",
        content="Coverage batch iyileştirme başlatıldı.",
    )
    result = await coverage_agent.run_autonomous_coverage_batch(
        coverage_xml=req.coverage_xml,
        coveragerc=req.coveragerc,
        limit=req.limit,
        batch_size=req.batch_size,
        append=req.append,
    )
    await deps.emit_control_room_event(
        req.room_id,
        kind="status",
        source="coverage",
        content="Coverage batch iyileştirme tamamlandı.",
        payload={"success": bool(result.get("success", False)), "status": result.get("status", "")},
    )
    return JSONResponse(
        {
            "success": bool(result.get("success", False)),
            "result": result,
            "tenant_id": deps.get_user_tenant(_user),
        }
    )
