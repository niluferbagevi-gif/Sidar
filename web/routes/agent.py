from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from web.routes import LegacyExportRouter


def _parse_payload(model: type[Any], payload: Any) -> Any:
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)
    if isinstance(payload, dict):
        return model(**payload)
    return payload


def build_agent_router(
    *,
    require_admin_user: Callable[..., Any],
    register_plugin_agent: Callable[..., Any],
    persist_and_import_plugin_file: Callable[[str, bytes, str], Any],
    max_file_content_bytes: int | Callable[[], int],
    read_plugin_marketplace_state: Callable[[], dict[str, Any]],
    serialize_marketplace_plugin: Callable[..., dict[str, Any]],
    plugin_marketplace_catalog: dict[str, Any] | Callable[[], dict[str, Any]],
    install_marketplace_plugin: Callable[[str], dict[str, Any]],
    uninstall_marketplace_plugin: Callable[[str], dict[str, Any]],
    agent_plugin_register_request_model: type[Any],
    plugin_marketplace_install_request_model: type[Any],
) -> LegacyExportRouter:
    """Build router for /api/agents and plugin marketplace endpoints.

    ``require_admin_user`` limits plugin registration to trusted operators. The
    runtime additionally rejects all in-process plugin execution in production;
    AST/builtins restrictions remain defense-in-depth for explicit non-production
    compatibility mode, not a process or container sandbox.
    """
    router = LegacyExportRouter()
    _resolve_mfcb = (
        max_file_content_bytes
        if callable(max_file_content_bytes)
        else (lambda: max_file_content_bytes)
    )

    @router.post("/api/agents/register")
    async def register_agent_plugin(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = _parse_payload(agent_plugin_register_request_model, payload)
        result = register_plugin_agent(
            role_name=data.role_name,
            source_code=data.source_code,
            class_name=data.class_name,
            capabilities=data.capabilities,
            description=data.description,
            version=data.version,
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
        if len(data) > int(_resolve_mfcb()):
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
        catalog = (
            plugin_marketplace_catalog()
            if callable(plugin_marketplace_catalog)
            else plugin_marketplace_catalog
        )
        items = []
        for plugin_id in sorted(catalog):
            item = dict(
                serialize_marketplace_plugin(plugin_id, installed_state=state.get(plugin_id, {}))
            )
            item.setdefault("id", plugin_id)
            items.append(item)
        return JSONResponse({"items": items})

    @router.post("/api/plugin-marketplace/install")
    async def install_plugin_marketplace_item(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = _parse_payload(plugin_marketplace_install_request_model, payload)
        return JSONResponse(install_marketplace_plugin(data.plugin_id))

    @router.post("/api/plugin-marketplace/reload")
    async def reload_plugin_marketplace_item(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = _parse_payload(plugin_marketplace_install_request_model, payload)
        return JSONResponse(install_marketplace_plugin(data.plugin_id))

    @router.delete("/api/plugin-marketplace/install/{plugin_id}")
    async def uninstall_plugin_marketplace_item(
        plugin_id: str, _user: Any = Depends(require_admin_user)
    ) -> Any:
        return JSONResponse(uninstall_marketplace_plugin(plugin_id))

    router.legacy_exports = {
        "register_agent_plugin": register_agent_plugin,
        "register_agent_plugin_file": register_agent_plugin_file,
        "plugin_marketplace_catalog": plugin_marketplace_catalog_endpoint,
        "install_plugin_marketplace_item": install_plugin_marketplace_item,
        "reload_plugin_marketplace_item": reload_plugin_marketplace_item,
        "uninstall_plugin_marketplace_item": uninstall_plugin_marketplace_item,
    }
    return router
