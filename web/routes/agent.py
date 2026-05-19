from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse


def build_agent_router(
    *,
    require_admin_user: Callable[..., Any],
    register_plugin_agent: Callable[..., Any],
    persist_and_import_plugin_file: Callable[[str, bytes, str], Any],
    max_file_content_bytes: int,
    read_plugin_marketplace_state: Callable[[], dict[str, Any]],
    serialize_marketplace_plugin: Callable[..., dict[str, Any]],
    plugin_marketplace_catalog: dict[str, Any],
    install_marketplace_plugin: Callable[[str], dict[str, Any]],
    uninstall_marketplace_plugin: Callable[[str], dict[str, Any]],
    agent_plugin_register_request_model: type[Any],
    plugin_marketplace_install_request_model: type[Any],
) -> APIRouter:
    """Build router for /api/agents and plugin marketplace endpoints."""
    router = APIRouter()

    @router.post("/api/agents/register")
    async def register_agent_plugin(
        payload: agent_plugin_register_request_model, _user: Any = Depends(require_admin_user)
    ) -> Any:
        result = register_plugin_agent(
            role_name=payload.role_name,
            source_code=payload.source_code,
            class_name=payload.class_name,
            capabilities=payload.capabilities,
            description=payload.description,
            version=payload.version,
        )
        return JSONResponse({"success": True, "agent": result})

    @router.post("/api/agents/register-file")
    async def register_agent_plugin_file(
        file: UploadFile = File(...),
        role_name: str = "",
        class_name: str = "",
        capabilities: str = "",
        description: str = "",
        version: str = "1.0.0",
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = await file.read()
        await file.close()
        if not data:
            raise HTTPException(status_code=400, detail="Yüklü dosya boş")
        if len(data) > max_file_content_bytes:
            raise HTTPException(status_code=413, detail="Dosya çok büyük")
        try:
            source_code = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Plugin dosyası UTF-8 olmalıdır") from exc

        parsed_capabilities = [c.strip() for c in capabilities.split(",") if c.strip()]
        target_role_name = role_name.strip() or Path(file.filename or "").stem
        module_label = f"sidar_uploaded_plugin_{secrets.token_hex(4)}"
        persist_and_import_plugin_file(file.filename or target_role_name, data, module_label)
        result = register_plugin_agent(
            role_name=target_role_name,
            source_code=source_code,
            class_name=class_name.strip() or None,
            capabilities=parsed_capabilities,
            description=description,
            version=version,
        )
        return JSONResponse({"success": True, "agent": result})

    @router.get("/api/plugin-marketplace/catalog")
    async def plugin_marketplace_catalog_endpoint(_user: Any = Depends(require_admin_user)) -> Any:
        state = read_plugin_marketplace_state()
        items = [
            serialize_marketplace_plugin(plugin_id, installed_state=state.get(plugin_id, {}))
            for plugin_id in sorted(plugin_marketplace_catalog)
        ]
        return JSONResponse({"items": items})

    @router.post("/api/plugin-marketplace/install")
    async def install_plugin_marketplace_item(
        payload: plugin_marketplace_install_request_model,
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        return JSONResponse(install_marketplace_plugin(payload.plugin_id))

    @router.post("/api/plugin-marketplace/reload")
    async def reload_plugin_marketplace_item(
        payload: plugin_marketplace_install_request_model,
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        return JSONResponse(install_marketplace_plugin(payload.plugin_id))

    @router.delete("/api/plugin-marketplace/install/{plugin_id}")
    async def uninstall_plugin_marketplace_item(
        plugin_id: str, _user: Any = Depends(require_admin_user)
    ) -> Any:
        return JSONResponse(uninstall_marketplace_plugin(plugin_id))

    return router
