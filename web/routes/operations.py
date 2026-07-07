"""Operations, Poyraz bridge, and Coverage QA HTTP routes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import coverage_ops
from .operations_models import (
    CampaignCopyGenerateRequest,
    CampaignCreateRequest,
    ContentAssetCreateRequest,
    LandingPageDraftRequest,
    OperationChecklistCreateRequest,
    PoyrazToolRunRequest,
    ServiceOperationsPlanRequest,
)

ALLOWED_POYRAZ_REST_TOOLS = frozenset(
    {
        "build_landing_page",
        "generate_campaign_copy",
        "create_marketing_campaign",
        "store_content_asset",
        "create_operation_checklist",
        "plan_service_operations",
        "ingest_video_insights",
    }
)


_deps_factory: Callable[[], Any] | None = None
router = APIRouter()
logger = logging.getLogger(__name__)


# Legacy exports kept for direct web_server/tests imports while endpoint implementations
# live in the smaller coverage_ops route module.
api_qa_coverage_tasks = coverage_ops.api_qa_coverage_tasks
api_qa_coverage_analyze = coverage_ops.api_qa_coverage_analyze
api_qa_coverage_generate = coverage_ops.api_qa_coverage_generate
api_qa_coverage_batch = coverage_ops.api_qa_coverage_batch
decode_agent_tool_result = coverage_ops.decode_agent_tool_result
serialize_coverage_task = coverage_ops.serialize_coverage_task


def configure_operations_dependencies(deps_factory: Callable[[], Any]) -> None:
    global _deps_factory
    _deps_factory = deps_factory
    coverage_ops.configure_coverage_dependencies(deps_factory)


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


def _database_unavailable_response(*, operation: str, exc: Exception) -> JSONResponse:
    logger.warning("Operations database unavailable during %s: %s", operation, exc)
    return JSONResponse(
        {
            "success": False,
            "error": "database_unavailable",
            "message": "Veritabanı geçici olarak kullanılamıyor.",
        },
        status_code=503,
    )


def _poyraz_unavailable_response(*, operation: str, exc: Exception) -> JSONResponse:
    logger.warning("Poyraz operation unavailable during %s: %s", operation, exc)
    return JSONResponse(
        {
            "success": False,
            "error": "poyraz_unavailable",
            "message": "Poyraz operasyon aracı geçici olarak kullanılamıyor.",
        },
        status_code=503,
    )


async def _resolve_operations_db(deps: Any) -> Any:
    agent = await deps.resolve_agent_instance()
    return agent.memory.db


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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
    tool_name = req.tool_name.strip()
    if tool_name not in ALLOWED_POYRAZ_REST_TOOLS:
        raise HTTPException(
            status_code=400, detail="Bu Poyraz aracı REST operasyon köprüsünde desteklenmiyor."
        )
    payload = {**dict(req.payload or {}), "tenant_id": deps.get_user_tenant(_user)}
    if "owner_user_id" not in payload:
        payload["owner_user_id"] = str(getattr(_user, "id", "") or "")
    try:
        _raw_result, result = await _run_poyraz_tool(req, _user, tool_name, payload)
    except (RuntimeError, OSError, AttributeError) as exc:
        return _poyraz_unavailable_response(operation="poyraz_tool_bridge", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during poyraz_tool_bridge")
        return _poyraz_unavailable_response(operation="poyraz_tool_bridge", exc=exc)
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
    try:
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _poyraz_unavailable_response(operation=tool_name, exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during %s", tool_name)
        return _poyraz_unavailable_response(operation=tool_name, exc=exc)
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


router.routes.extend(coverage_ops.router.routes)
