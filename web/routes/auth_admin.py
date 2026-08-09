from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from web.routes import LegacyExportRouter
from web.security import is_reserved_username


def _parse_payload(model: type[Any], payload: Any) -> Any:
    if not isinstance(payload, dict) and hasattr(payload, "__dict__"):
        payload = dict(vars(payload))
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)
    if isinstance(payload, dict):
        return model(**payload)
    return payload


def _normalize_register_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    alias_pairs = (
        ("userName", "username"),
        ("user_name", "username"),
        ("passWord", "password"),
        ("tenantId", "tenant_id"),
        ("tenant", "tenant_id"),
    )
    for alias_key, canonical_key in alias_pairs:
        if canonical_key not in normalized and alias_key in normalized:
            normalized[canonical_key] = normalized[alias_key]
    return normalized


def build_auth_admin_router(
    *,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    get_request_user: Callable[..., Any],
    require_admin_user: Callable[..., Any],
    issue_auth_token: Callable[[Any, Any], Awaitable[str]],
    serialize_prompt: Callable[[Any], dict[str, Any]],
    serialize_policy: Callable[[Any], dict[str, Any]],
    serialize_audit_log: Callable[[Any], dict[str, Any]],
    get_admin_stats: Callable[[Any], Awaitable[dict[str, Any]] | dict[str, Any]] | None = None,
    register_request_model: type[Any],
    login_request_model: type[Any],
    prompt_upsert_request_model: type[Any],
    prompt_activate_request_model: type[Any],
    policy_upsert_request_model: type[Any],
) -> LegacyExportRouter:
    """Build router for auth, admin prompt and access policy endpoints."""
    router = LegacyExportRouter()

    @router.post("/auth/register")
    async def register_user(payload: Annotated[dict[str, Any], Body()]) -> Any:
        data = _parse_payload(register_request_model, _normalize_register_payload(payload))
        username = data.username.strip()
        password = data.password
        tenant_id = data.tenant_id.strip() or "default"
        if len(username) < 3 or len(password) < 6:
            raise HTTPException(status_code=400, detail="Geçersiz kullanıcı adı veya şifre")
        if is_reserved_username(username):
            raise HTTPException(status_code=400, detail="Bu kullanıcı adı rezerve edilmiştir")

        agent = await resolve_agent_instance()
        try:
            register_result = agent.memory.db.register_user(
                username=username, password=password, tenant_id=tenant_id
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"Kullanıcı oluşturulamadı: {exc}") from exc
        try:
            maybe = await_if_needed(register_result)
            user = await maybe if inspect.isawaitable(maybe) else maybe
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail="Kullanıcı kaydı işlenirken beklenmeyen bir hata oluştu"
            ) from exc

        token = await issue_auth_token(agent, user)
        return JSONResponse(
            {
                "user": {"id": user.id, "username": user.username, "role": user.role},
                "access_token": token,
            }
        )

    @router.post("/auth/login")
    async def login_user(payload: Annotated[dict[str, Any], Body()]) -> Any:
        data = _parse_payload(login_request_model, payload)
        username = data.username.strip()
        password = data.password
        agent = await resolve_agent_instance()
        try:
            maybe = await_if_needed(
                agent.memory.db.authenticate_user(username=username, password=password)
            )
            user = await maybe if inspect.isawaitable(maybe) else maybe
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail="Veritabanı hatası nedeniyle giriş yapılamadı"
            ) from exc
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

        token = await issue_auth_token(agent, user)
        return JSONResponse(
            {
                "user": {"id": user.id, "username": user.username, "role": user.role},
                "access_token": token,
            }
        )

    @router.get("/auth/me")
    async def auth_me(request: Request, user: Any = Depends(get_request_user)) -> Any:
        return JSONResponse({"id": user.id, "username": user.username, "role": user.role})

    @router.get("/admin/stats")
    async def admin_stats(_user: Any = Depends(require_admin_user)) -> Any:
        agent = await resolve_agent_instance()
        if get_admin_stats is not None:
            maybe = get_admin_stats(agent)
            stats = await maybe if inspect.isawaitable(maybe) else maybe
        else:
            stats = await agent.memory.db.get_admin_stats()
        return JSONResponse(stats)

    @router.get("/admin/prompts")
    async def admin_list_prompts(
        role_name: str = "", _user: Any = Depends(require_admin_user)
    ) -> Any:
        agent = await resolve_agent_instance()
        prompts = await agent.memory.db.list_prompts(role_name=role_name.strip() or None)
        return JSONResponse({"items": [serialize_prompt(p) for p in prompts]})

    @router.get("/admin/prompts/active")
    async def admin_active_prompt(
        role_name: str = "system", _user: Any = Depends(require_admin_user)
    ) -> Any:
        agent = await resolve_agent_instance()
        active = await agent.memory.db.get_active_prompt(role_name)
        if not active:
            raise HTTPException(status_code=404, detail="Aktif prompt bulunamadı")
        return JSONResponse(serialize_prompt(active))

    @router.post("/admin/prompts")
    async def admin_upsert_prompt(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = _parse_payload(prompt_upsert_request_model, payload)
        role_name = (data.role_name or "").strip().lower()
        prompt_text = (data.prompt_text or "").strip()
        if not role_name or not prompt_text:
            raise HTTPException(status_code=400, detail="role_name ve prompt_text zorunludur")

        agent = await await_if_needed(resolve_agent_instance())
        record = await agent.memory.db.upsert_prompt(
            role_name=role_name, prompt_text=prompt_text, activate=bool(data.activate)
        )
        if role_name == "system":
            agent.system_prompt = record.prompt_text
        return JSONResponse(serialize_prompt(record))

    @router.post("/admin/prompts/activate")
    async def admin_activate_prompt(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        agent = await await_if_needed(resolve_agent_instance())
        data = _parse_payload(prompt_activate_request_model, payload)
        active = await agent.memory.db.activate_prompt(data.prompt_id)
        if not active:
            raise HTTPException(status_code=404, detail="Prompt kaydı bulunamadı")
        if active.role_name == "system":
            agent.system_prompt = active.prompt_text
        return JSONResponse(serialize_prompt(active))

    @router.get("/admin/policies/{user_id}")
    async def admin_list_policies(
        user_id: str, tenant_id: str = "", _user: Any = Depends(require_admin_user)
    ) -> JSONResponse:
        agent = await resolve_agent_instance()
        records = await agent.memory.db.list_access_policies(
            user_id=user_id, tenant_id=tenant_id.strip() or None
        )
        return JSONResponse({"items": [serialize_policy(r) for r in records]})

    @router.get("/admin/audit-logs")
    async def admin_list_audit_logs(
        user_id: str = "",
        tenant_id: str = "",
        limit: int = 100,
        _user: Any = Depends(require_admin_user),
    ) -> JSONResponse:
        agent = await resolve_agent_instance()
        records = await agent.memory.db.list_audit_logs(
            user_id=user_id.strip() or None,
            tenant_id=tenant_id.strip() or None,
            limit=limit,
        )
        return JSONResponse({"items": [serialize_audit_log(r) for r in records]})

    @router.post("/admin/policies")
    async def admin_upsert_policy(
        payload: Annotated[dict[str, Any], Body()],
        _user: Any = Depends(require_admin_user),
    ) -> Any:
        data = _parse_payload(policy_upsert_request_model, payload)
        agent = await resolve_agent_instance()
        await agent.memory.db.upsert_access_policy(
            user_id=data.user_id.strip(),
            tenant_id=data.tenant_id.strip() or "default",
            resource_type=data.resource_type.strip().lower(),
            resource_id=data.resource_id.strip() or "*",
            action=data.action.strip().lower(),
            effect=data.effect.strip().lower(),
        )
        records = await agent.memory.db.list_access_policies(
            user_id=data.user_id.strip(), tenant_id=data.tenant_id.strip() or "default"
        )
        return JSONResponse({"success": True, "items": [serialize_policy(r) for r in records]})

    router.legacy_exports = {
        "register_user": register_user,
        "login_user": login_user,
        "auth_me": auth_me,
        "admin_stats": admin_stats,
        "admin_list_prompts": admin_list_prompts,
        "admin_active_prompt": admin_active_prompt,
        "admin_upsert_prompt": admin_upsert_prompt,
        "admin_activate_prompt": admin_activate_prompt,
        "admin_list_policies": admin_list_policies,
        "admin_list_audit_logs": admin_list_audit_logs,
        "admin_upsert_policy": admin_upsert_policy,
    }
    return router
