from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from web.routes import LegacyExportRouter


def build_health_router(
    health_response: Callable[[bool], Awaitable[Any]],
    status_response: Callable[[], Awaitable[Any]] | None = None,
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    @router.get(
        "/health",
        summary="Sağlık Kontrolü (Health Check)",
        description="Liveness/readiness kontrolü için sistem sağlık bilgisini döndürür.",
        responses={
            200: {"description": "Sistem sağlıklı"},
            503: {"description": "Sistemde kritik bir sorun var"},
        },
    )
    @router.get("/healthz", include_in_schema=False)
    async def health_check() -> Any:
        return await health_response(False)

    @router.get("/readyz", include_in_schema=False)
    async def readiness_check() -> Any:
        return await health_response(True)

    status_endpoint: Callable[[], Awaitable[Any]] | None = None
    if status_response is not None:
        @router.get("/status", include_in_schema=False)
        async def status() -> Any:
            return await status_response()

        status_endpoint = status

    router.legacy_exports = {
        "health_check": health_check,
        "readiness_check": readiness_check,
    }
    if status_endpoint is not None:
        router.legacy_exports["status"] = status_endpoint
    return router
