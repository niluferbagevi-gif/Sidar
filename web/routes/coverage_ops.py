"""Coverage QA HTTP routes split from the broader operations router."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .operations_models import CoverageAnalyzeRequest, CoverageBatchRequest, CoverageGenerateRequest

_deps_factory: Callable[[], Any] | None = None
router = APIRouter()
logger = logging.getLogger(__name__)


def configure_coverage_dependencies(deps_factory: Callable[[], Any]) -> None:
    """Configure shared dependency access for Coverage QA route handlers."""
    global _deps_factory
    _deps_factory = deps_factory


def _deps() -> Any:
    if _deps_factory is None:  # pragma: no cover - configuration guard
        raise RuntimeError("Coverage route dependencies are not configured.")
    return _deps_factory()


async def _get_request_user_proxy(request: Request) -> Any:
    return await _deps().get_request_user(request)


async def _resolve_operations_db(deps: Any) -> Any:
    agent = await deps.resolve_agent_instance()
    return agent.memory.db


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


def decode_agent_tool_result(raw_result: Any) -> dict[str, Any]:
    """Decode a string/dict tool result into a JSON-serializable mapping."""
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


def serialize_coverage_task(record: Any) -> dict[str, Any]:
    """Serialize a coverage task ORM/model record for API responses."""
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
    except (RuntimeError, OSError, AttributeError) as exc:
        return _database_unavailable_response(operation="database_operation", exc=exc)
    except Exception as exc:
        logger.exception("Unexpected operations route failure during database_operation")
        return _database_unavailable_response(operation="database_operation", exc=exc)
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
