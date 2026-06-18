from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.routes import LegacyExportRouter
from web.security import SIDAR_WS_HITL_PROTOCOL
from web.security import extract_ws_header_token as default_extract_ws_header_token


class HITLRespondRequest(BaseModel):
    approved: bool
    decided_by: str = "operator"
    rejection_reason: str = ""


def build_hitl_router(
    *,
    get_request_user: Callable[..., Any],
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    resolve_user_from_token: Callable[[Any, str], Awaitable[Any] | Any],
    ws_close_policy_violation: Callable[[WebSocket, str], Awaitable[None]],
    hitl_ws_clients: set[WebSocket],
    get_hitl_store: Callable[[], Any],
    get_hitl_gate: Callable[[], Any],
    extract_ws_header_token: Callable[
        [str, str], tuple[str, str | None]
    ] = default_extract_ws_header_token,
    ws_hitl_protocol: str = SIDAR_WS_HITL_PROTOCOL,
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    async def _resolve_pending_items() -> list[Any]:
        pending_result = get_hitl_store().pending()
        if inspect.isawaitable(pending_result):
            pending_items = await pending_result
        else:
            pending_items = pending_result
        return list(pending_items or [])

    @router.get("/api/hitl/pending")
    async def hitl_pending(user: Any = Depends(get_request_user)) -> Any:
        pending = await _resolve_pending_items()
        return JSONResponse({"pending": [r.to_dict() for r in pending], "count": len(pending)})

    @router.post("/api/hitl/request")
    async def hitl_create_request(
        payload: dict[str, Any], user: Any = Depends(get_request_user)
    ) -> Any:
        gate = get_hitl_gate()
        action = str(payload.get("action", "manual")).strip()
        description = str(payload.get("description", "Manuel onay isteği")).strip()
        hitl_payload = dict(payload.get("payload") or {})
        requested_by = str(payload.get("requested_by", getattr(user, "username", "api"))).strip()

        import time
        import uuid

        from core.hitl import HITLRequest, notify

        now = time.time()
        req = HITLRequest(
            request_id=str(uuid.uuid4()),
            action=action,
            description=description,
            payload=hitl_payload,
            requested_by=requested_by,
            created_at=now,
            expires_at=now + gate.timeout,
        )
        store = get_hitl_store()
        await await_if_needed(store.add(req))
        await notify(req)
        return JSONResponse({"request_id": req.request_id, "expires_at": req.expires_at})

    @router.post("/api/hitl/respond/{request_id}")
    async def hitl_respond(
        request_id: str, payload: HITLRespondRequest, user: Any = Depends(get_request_user)
    ) -> Any:
        gate = get_hitl_gate()
        decided_by = payload.decided_by or getattr(user, "username", "operator")
        req = await gate.respond(
            request_id,
            approved=payload.approved,
            decided_by=decided_by,
            rejection_reason=payload.rejection_reason,
        )
        if req is None:
            raise HTTPException(status_code=404, detail="HITL isteği bulunamadı")
        return JSONResponse({"request_id": req.request_id, "decision": req.decision.value})

    @router.websocket("/ws/hitl")
    async def websocket_hitl(websocket: WebSocket) -> Any:
        proto_header = websocket.headers.get("sec-websocket-protocol", "").strip()
        auth_header = websocket.headers.get("authorization", "").strip()
        bearer_token = ""  # Empty sentinel; populated from Authorization header.  # nosec B105
        if auth_header.lower().startswith("bearer "):
            bearer_token = auth_header[7:].strip()
        header_token, accept_subprotocol = extract_ws_header_token(proto_header, ws_hitl_protocol)
        if not header_token:
            header_token = bearer_token
        if accept_subprotocol:
            await websocket.accept(subprotocol=accept_subprotocol)
        else:
            await websocket.accept()

        agent = await resolve_agent_instance()
        if header_token:
            ws_user = await await_if_needed(resolve_user_from_token(agent, header_token))
            if not ws_user:
                await ws_close_policy_violation(websocket, "Invalid or expired token")
                return
        hitl_ws_clients.add(websocket)
        try:
            pending = await _resolve_pending_items()
            await websocket.send_json(
                {"type": "hitl_snapshot", "pending": [item.to_dict() for item in pending]}
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hitl_ws_clients.discard(websocket)

    router.legacy_exports = {
        "hitl_pending": hitl_pending,
        "hitl_create_request": hitl_create_request,
        "hitl_respond": hitl_respond,
        "_HITLRespondRequest": HITLRespondRequest,
        "websocket_hitl": websocket_hitl,
    }
    return router
