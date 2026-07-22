"""Access-policy middleware helpers for Sidar's web API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response


async def access_policy_middleware_impl(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    resolve_policy_from_request: Callable[[Request], tuple[str, str, str]],
    get_client_ip: Callable[[Request], str],
    is_admin_user: Callable[[Any], bool],
    schedule_access_audit_log: Callable[..., None],
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    get_user_tenant: Callable[[Any], str],
    logger_obj: Any,
) -> Response:
    """Apply fine-grained ACL checks with injectable web-server dependencies."""
    if request.method == "OPTIONS":
        return await call_next(request)
    user = getattr(request.state, "user", None)
    if not user:
        return await call_next(request)
    resource_type, action, resource_id = resolve_policy_from_request(request)
    if not resource_type:
        return await call_next(request)
    client_ip = get_client_ip(request)
    if is_admin_user(user):
        schedule_access_audit_log(
            user=user,
            resource_type=resource_type,
            action=action,
            resource_id=resource_id,
            ip_address=client_ip,
            allowed=True,
        )
        return await call_next(request)

    allowed = False
    try:
        agent = await resolve_agent_instance()
        checker = getattr(agent.memory.db, "check_access_policy", None)
        if checker is None:
            allowed = True
        else:
            allowed = await checker(
                user_id=str(getattr(user, "id", "") or ""),
                tenant_id=get_user_tenant(user),
                resource_type=resource_type,
                action=action,
                resource_id=resource_id,
            )
    except Exception as exc:
        logger_obj.warning("ACL kontrolü başarısız (%s), erişim reddedildi.", exc)
        allowed = False

    schedule_access_audit_log(
        user=user,
        resource_type=resource_type,
        action=action,
        resource_id=resource_id,
        ip_address=client_ip,
        allowed=allowed,
    )
    if not allowed:
        return JSONResponse(
            status_code=403,
            content={"error": "Yetki yok", "resource": resource_type, "action": action},
        )
    return await call_next(request)
