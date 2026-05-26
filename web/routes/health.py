from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter

from web.routes import LegacyExportRouter


def build_health_router(
    health_response: Callable[[bool], Awaitable[Any]],
) -> APIRouter:
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

    router.legacy_exports = {
        "health_check": health_check,
        "readiness_check": readiness_check,
    }
    return router
