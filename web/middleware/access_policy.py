"""Access-policy middleware helpers for Sidar's web API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response


def get_user_tenant(user: Any) -> str:
    """Return a normalized tenant identifier for an authenticated principal."""
    return str(getattr(user, "tenant_id", "default") or "default").strip() or "default"


def serialize_policy(record: Any) -> dict[str, Any]:
    """Serialize an access-policy record for an API response."""
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "user_id": str(getattr(record, "user_id", "") or ""),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "resource_type": str(getattr(record, "resource_type", "") or ""),
        "resource_id": str(getattr(record, "resource_id", "*") or "*"),
        "action": str(getattr(record, "action", "") or ""),
        "effect": str(getattr(record, "effect", "allow") or "allow"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def serialize_audit_log(record: Any) -> dict[str, Any]:
    """Serialize an access audit-log record for an API response."""
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "user_id": str(getattr(record, "user_id", "") or ""),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "action": str(getattr(record, "action", "") or ""),
        "resource": str(getattr(record, "resource", "") or ""),
        "ip_address": str(getattr(record, "ip_address", "") or ""),
        "allowed": bool(getattr(record, "allowed", False)),
        "timestamp": str(getattr(record, "timestamp", "") or ""),
    }


def resolve_policy_from_request(request: Request) -> tuple[str, str, str]:
    """Map a protected HTTP path to its policy resource, action, and identifier."""
    path = request.url.path
    if path.startswith("/rag/"):
        action = "read" if request.method == "GET" else "write"
        resource_id = path.rsplit("/", 1)[-1] if request.method == "DELETE" else "*"
        return ("rag", action, resource_id)
    if path.startswith("/github-") or path == "/set-repo":
        action = "read" if request.method == "GET" else "write"
        return ("github", action, "*")
    if path.startswith("/api/agents/register"):
        return ("agents", "register", "*")
    if path.startswith("/api/swarm/"):
        return ("swarm", "execute", "*")
    if path.startswith("/api/operations/"):
        return ("operations", "write" if request.method != "GET" else "read", "*")
    if path.startswith("/api/qa/coverage/"):
        return ("coverage", "write" if request.method != "GET" else "read", "*")
    if path.startswith("/admin/"):
        return ("admin", "manage", "*")
    if path.startswith("/ws/"):
        return ("swarm", "execute", "*")
    return ("", "", "")


def build_audit_resource(resource_type: str, resource_id: str) -> str:
    """Build the canonical resource value persisted in an access audit log."""
    normalized_type = (resource_type or "").strip().lower()
    normalized_id = (resource_id or "*").strip() or "*"
    if not normalized_type:
        return ""
    return f"{normalized_type}:{normalized_id}"


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
