"""Frontend bootstrap helpers for the Sidar FastAPI application."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles


def make_static_files_with_staticfiles(directory: Path, static_files_cls: type[Any]) -> Any:
    """Create a ``StaticFiles`` instance even when the dist dir is missing."""
    try:
        return static_files_cls(directory=directory, check_dir=False)
    except TypeError:
        return static_files_cls(directory=directory)


def make_static_files(directory: Path) -> Any:
    """Create a FastAPI ``StaticFiles`` instance even when the dist dir is missing."""
    return make_static_files_with_staticfiles(directory, StaticFiles)


def mount_frontend_static_routes(target_app: FastAPI, web_dir: Path) -> None:
    """Mount React build static asset routes on the target FastAPI app."""
    target_app.mount("/static", make_static_files(web_dir), name="static")
    assets_dir = web_dir / "assets"
    if assets_dir.exists():
        target_app.mount("/assets", make_static_files(assets_dir), name="assets")


async def await_if_needed(value: Any) -> Any:
    """Await a value only when it is awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


def build_spa_fallback_handler(
    *,
    index: Callable[[], Any | Awaitable[Any]],
    await_value: Callable[[Any], Awaitable[Any]] = await_if_needed,
) -> Callable[[str], Awaitable[Any]]:
    """Build the React SPA history fallback handler.

    API, WebSocket, webhook and static asset-looking paths intentionally return
    404 so missing backend/static endpoints are not masked by the SPA shell.
    """

    async def spa_fallback(full_path: str) -> Any:
        normalized = (full_path or "").strip()
        if not normalized:
            return await await_value(index())
        first_segment = normalized.split("/", 1)[0].lower()
        if first_segment in {"api", "vendor", "static", "assets", "ws", "webhook"}:
            return Response(status_code=404)
        if "." in Path(normalized).name:
            return Response(status_code=404)
        response = await await_value(index())
        if getattr(response, "status_code", None) == 500:
            return HTMLResponse(
                "<h1>SİDAR arayüzü için SPA fallback etkin.</h1>",
                status_code=200,
            )
        return response

    return spa_fallback
