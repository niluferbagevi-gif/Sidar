"""Bearer-token authentication middleware for the Sidar FastAPI app.

Extracted from ``web_server.py``. Every collaborator is injected by
``web_server.basic_auth_middleware`` at call time, so tests that monkeypatch
``web_server._resolve_user_from_token``, ``web_server.set_current_metrics_user_id``
and friends keep observing their patches.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

NextHandler = Callable[[Request], Awaitable[Response]]


async def basic_auth_middleware_impl(
    request: Request,
    call_next: NextHandler,
    *,
    config: Any,
    authenticate_metrics_service: Callable[..., Any],
    resolve_user_from_token: Callable[[Any, str], Awaitable[Any]],
    resolve_agent_instance: Callable[[], Any],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    set_metrics_user_id: Callable[[Any], Any],
    reset_metrics_user_id: Callable[[Any], Any],
) -> Response:
    """Bearer token ile stateless JWT kullanıcı doğrulaması uygular."""
    open_paths = {
        "/",
        "/health",
        "/healthz",
        "/readyz",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/login",
        "/auth/register",
    }
    webhook_signature_paths = {"/api/webhook"}
    webhook_signature_prefixes = ("/api/autonomy/webhook/",)
    is_signature_verified_webhook = request.method == "POST" and (
        request.url.path in webhook_signature_paths
        or request.url.path.startswith(webhook_signature_prefixes)
    )
    if (
        request.method == "OPTIONS"
        or request.url.path in open_paths
        or is_signature_verified_webhook
        or request.url.path.startswith("/static/")
        or request.url.path.startswith("/vendor/")
        or request.url.path.startswith("/assets/")
        or request.url.path == "/favicon.ico"
        or request.url.path == "/favicon.svg"
    ):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Yetkisiz erişim"}, status_code=401)

    access_token = auth_header[7:].strip()
    if not access_token:
        return JSONResponse({"error": "Geçersiz token"}, status_code=401)

    metrics_user = authenticate_metrics_service(request, config=config)
    if metrics_user is not None:
        request.state.user = metrics_user
        metrics_context = set_metrics_user_id(metrics_user.id)
        try:
            return await call_next(request)
        finally:
            reset_metrics_user_id(metrics_context)

    user = await resolve_user_from_token(None, access_token)
    if not user:
        return JSONResponse({"error": "Oturum geçersiz veya süresi dolmuş"}, status_code=401)

    agent = await await_if_needed(resolve_agent_instance())
    request.state.user = user
    set_active_user = getattr(agent.memory, "set_active_user", None)
    if callable(set_active_user):
        await set_active_user(user.id, user.username)
    metrics_token = set_metrics_user_id(user.id)
    try:
        return await call_next(request)
    finally:
        reset_metrics_user_id(metrics_token)
