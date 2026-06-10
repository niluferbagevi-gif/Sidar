from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse, HTMLResponse, Response

from web.routes import LegacyExportRouter


def build_frontend_router(
    *,
    web_dir: Callable[[], Path],
    grafana_url: Callable[[], str],
) -> LegacyExportRouter:
    """Build static frontend routes for the React SPA shell and vendor assets."""
    router = LegacyExportRouter()

    @router.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Any:
        """Tarayıcının favicon isteğini 404 hatası vermeden sessizce (204) geçiştirir."""
        return Response(status_code=204)

    @router.get("/vendor/{file_path:path}", include_in_schema=False)
    async def serve_vendor(file_path: str) -> Any:
        """React dist altındaki vendor kütüphanelerini servis eder."""
        vendor_dir = (web_dir() / "vendor").resolve()
        safe_path = (vendor_dir / file_path).resolve()
        if not str(safe_path).startswith(str(vendor_dir)):
            return Response(status_code=403)
        if not safe_path.exists():
            return Response(status_code=404)
        return FileResponse(safe_path)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> Any:
        """Ana sayfa — React SPA build çıktısı."""
        html_file = web_dir() / "index.html"
        if not html_file.exists():
            return HTMLResponse(
                "<h1>Hata: React dist bulunamadı. web_ui_react içinde npm run build çalıştırın.</h1>",
                status_code=500,
            )
        config_script = f'<script>window.__SIDAR_CONFIG__ = {{"grafanaUrl": {json.dumps(grafana_url())}}};</script>'
        html = html_file.read_text(encoding="utf-8")
        if "</head>" in html:
            html = html.replace("</head>", f"{config_script}</head>", 1)
        else:
            html = config_script + html
        return HTMLResponse(html)

    router.legacy_exports = {
        "favicon": favicon,
        "serve_vendor": serve_vendor,
        "index": index,
    }
    return router
