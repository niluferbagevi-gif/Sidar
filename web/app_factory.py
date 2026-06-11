"""FastAPI application factory and shared exception handlers for Sidar."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from sidar_version import PRODUCT_VERSION

logger = logging.getLogger("sidar.web")


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def _expose_exception_details() -> bool:
    return os.getenv("SIDAR_ENV", "").strip().lower() != "production"


def register_exception_handlers(
    application: FastAPI, *, expose_exception_details: bool | None = None
) -> None:
    """Register Sidar's JSON exception handlers on a FastAPI application."""

    if not hasattr(application, "exception_handler"):
        return
    include_detail = (
        _expose_exception_details()
        if expose_exception_details is None
        else expose_exception_details
    )

    @application.exception_handler(HTTPException)
    async def _http_exception_handler(_request: Request, exc: HTTPException) -> Any:
        detail = getattr(exc, "detail", "İstek işlenemedi.")
        if isinstance(detail, dict):
            content = {"success": False, **detail}
            content.setdefault("error", "İstek işlenemedi.")
        else:
            content = {"success": False, "error": str(detail or "İstek işlenemedi.")}
        return JSONResponse(content, status_code=getattr(exc, "status_code", 500))

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Any:
        logger.exception(
            "İşlenmeyen web hatası: path=%s error=%s",
            getattr(request.url, "path", "?"),
            exc,
        )
        content = {"success": False, "error": "İç sunucu hatası"}
        if include_detail:
            content["detail"] = str(exc)
        return JSONResponse(content, status_code=500)


def create_app(
    *,
    lifespan: Callable[[FastAPI], Any] | None = None,
    register_handlers: bool = True,
    expose_exception_details: bool | None = None,
    version: str = PRODUCT_VERSION,
) -> FastAPI:
    """Create the Sidar FastAPI application shell.

    Route registration is intentionally left to ``web_server.py`` for backwards
    compatibility while endpoint clusters continue moving into ``web.routes``.
    """

    application = FastAPI(
        title="Sidar Web UI & REST API",
        description=(
            "Sidar AI Ajanı için Web Arayüzü ve REST API uç noktaları. "
            "RAG, GitHub, Görev Yönetimi ve Sistem İzleme API'lerini içerir."
        ),
        version=str(version or PRODUCT_VERSION),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan or _noop_lifespan,
    )
    if register_handlers:
        register_exception_handlers(
            application, expose_exception_details=expose_exception_details
        )
    return application
