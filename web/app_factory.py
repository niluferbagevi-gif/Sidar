"""FastAPI application factory and shared exception handlers for Sidar."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from sidar_version import PRODUCT_VERSION

logger = logging.getLogger("sidar.web")

_RUNTIME_STATE_DEFAULTS: dict[str, Any] = {
    "agent": None,
    "agent_lock": None,
    "redis_lock": None,
    "local_rate_lock": None,
    "rag_prewarm_task": None,
    "autonomy_cron_task": None,
    "autonomy_cron_stop": None,
    "nightly_memory_task": None,
    "nightly_memory_stop": None,
}


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def _expose_exception_details() -> bool:
    return os.getenv("SIDAR_ENV", "").strip().lower() != "production"


def _expose_api_docs() -> bool:
    """Return whether interactive API schemas may be published in this environment."""
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


def register_routers(application: FastAPI, routers: list[APIRouter]) -> dict[str, Any]:
    """Include route modules on the app and collect legacy endpoint exports.

    Route modules may expose a ``legacy_exports`` mapping for backwards-compatible
    direct imports/tests while app construction keeps router registration in one
    orchestration point.
    """
    legacy_exports: dict[str, Any] = {}
    for router in routers:
        application.include_router(router)
        exports = getattr(router, "legacy_exports", {}) or {}
        if isinstance(exports, dict):
            legacy_exports.update(exports)
    return legacy_exports


def initialize_runtime_state(application: FastAPI, **overrides: Any) -> SimpleNamespace:
    """Attach Sidar's mutable runtime state to ``app.state``.

    ``web_server.py`` still exposes legacy module globals for direct imports/tests, but
    new route factories and dependencies should prefer this app-bound state object so
    isolated FastAPI instances do not accidentally share singleton state.
    """
    state = getattr(application.state, "sidar_runtime", None)
    if state is None:
        state = SimpleNamespace()
        application.state.sidar_runtime = state
    for key, value in _RUNTIME_STATE_DEFAULTS.items():
        if not hasattr(state, key):
            setattr(state, key, value)
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def get_runtime_state(application: FastAPI) -> SimpleNamespace:
    """Return the app-bound Sidar runtime state, creating it if needed."""
    return initialize_runtime_state(application)


def create_app(
    *,
    lifespan: Callable[[FastAPI], Any] | None = None,
    register_handlers: bool = True,
    expose_exception_details: bool | None = None,
    expose_api_docs: bool | None = None,
    version: str = PRODUCT_VERSION,
) -> FastAPI:
    """Create the Sidar FastAPI application shell.

    Router construction remains dependency-driven in ``web_server.py``, while
    router registration is centralized through ``register_routers`` in this
    factory module.
    """
    include_api_docs = _expose_api_docs() if expose_api_docs is None else expose_api_docs
    application = FastAPI(
        title="Sidar Web UI & REST API",
        description=(
            "Sidar AI Ajanı için Web Arayüzü ve REST API uç noktaları. "
            "RAG, GitHub, Görev Yönetimi ve Sistem İzleme API'lerini içerir."
        ),
        version=str(version or PRODUCT_VERSION),
        docs_url="/docs" if include_api_docs else None,
        redoc_url="/redoc" if include_api_docs else None,
        openapi_url="/openapi.json" if include_api_docs else None,
        lifespan=lifespan or _noop_lifespan,
    )
    if register_handlers:
        register_exception_handlers(application, expose_exception_details=expose_exception_details)
    initialize_runtime_state(application)
    return application
