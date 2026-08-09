"""Focused tests for static frontend route fallback paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.responses import FileResponse, HTMLResponse, Response

from web.routes.static import build_frontend_router


@pytest.mark.asyncio
async def test_static_favicon_svg_missing_and_present_paths(tmp_path) -> None:
    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")
    favicon = router.legacy_exports["favicon"]
    favicon_svg = next(route.endpoint for route in router.routes if route.path == "/favicon.svg")

    favicon_response = await favicon()
    missing = await favicon_svg()
    assert favicon_response.status_code == 204
    assert isinstance(missing, Response)
    assert missing.status_code == 204

    icon = tmp_path / "favicon.svg"
    icon.write_text("<svg />", encoding="utf-8")
    present = await favicon_svg()
    assert isinstance(present, FileResponse)
    assert Path(present.path) == icon


@pytest.mark.asyncio
async def test_static_vendor_route_rejects_traversal_and_missing_assets(tmp_path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    asset = vendor_dir / "app.js"
    asset.write_text("console.log('ok')", encoding="utf-8")
    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")
    serve_vendor = router.legacy_exports["serve_vendor"]

    traversal = await serve_vendor("../secret.txt")
    missing = await serve_vendor("missing.js")
    present = await serve_vendor("app.js")

    assert traversal.status_code == 403
    assert missing.status_code == 404
    assert isinstance(present, FileResponse)
    assert Path(present.path) == asset.resolve()


@pytest.mark.asyncio
async def test_static_index_missing_dist_returns_actionable_500(tmp_path) -> None:
    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")
    index = router.legacy_exports["index"]

    response = await index()

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 500
    assert "React dist bulunamadı" in response.body.decode("utf-8")


@pytest.mark.asyncio
async def test_static_index_injects_config_before_head_close(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<html><head><title>Sidar</title></head><body>SPA</body></html>",
        encoding="utf-8",
    )
    router = build_frontend_router(web_dir=lambda: tmp_path, grafana_url=lambda: "http://grafana")
    index = router.legacy_exports["index"]

    response = await index()
    html = response.body.decode("utf-8")

    assert response.status_code == 200
    assert 'window.__SIDAR_CONFIG__ = {"grafanaUrl": "http://grafana"}' in html
    assert html.index("window.__SIDAR_CONFIG__") < html.index("</head>")
