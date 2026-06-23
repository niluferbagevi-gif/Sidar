from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from web.bootstrap import build_spa_fallback_handler, mount_frontend_static_routes


@pytest.mark.asyncio
async def test_spa_fallback_serves_index_for_history_paths_and_empty_path():
    calls = []

    async def index():
        calls.append("index")
        return HTMLResponse("ok")

    fallback = build_spa_fallback_handler(index=index)

    empty = await fallback("  ")
    history = await fallback("dashboard/projects")

    assert empty.status_code == 200
    assert history.status_code == 200
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_spa_fallback_uses_default_await_helper_for_sync_index():
    def index():
        return HTMLResponse("sync ok")

    fallback = build_spa_fallback_handler(index=index)
    response = await fallback("dashboard")

    assert response.status_code == 200
    assert response.body == b"sync ok"


@pytest.mark.asyncio
async def test_spa_fallback_does_not_mask_backend_or_asset_paths():
    async def index():  # pragma: no cover - must not be called for rejected paths
        raise AssertionError("index should not be called")

    fallback = build_spa_fallback_handler(index=index)

    assert (await fallback("api/metrics")).status_code == 404
    assert (await fallback("assets/app.js")).status_code == 404
    assert (await fallback("nested/app.css")).status_code == 404


@pytest.mark.asyncio
async def test_spa_fallback_returns_emergency_shell_when_dist_index_missing():
    async def index():
        return HTMLResponse("missing dist", status_code=500)

    fallback = build_spa_fallback_handler(index=index)
    response = await fallback("dashboard")

    assert response.status_code == 200
    assert "SPA fallback" in response.body.decode("utf-8")


def test_mount_frontend_static_routes_mounts_assets_when_present(tmp_path):
    (tmp_path / "assets").mkdir()
    app = FastAPI()

    mount_frontend_static_routes(app, tmp_path)

    route_paths = {route.path for route in app.routes}
    assert "/static" in route_paths
    assert "/assets" in route_paths


def test_mount_frontend_static_routes_skips_missing_assets(tmp_path):
    app = FastAPI()

    mount_frontend_static_routes(app, tmp_path)

    route_paths = {route.path for route in app.routes}
    assert "/static" in route_paths
    assert "/assets" not in route_paths
