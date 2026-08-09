from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from web.routes.auth_admin import (
    _normalize_register_payload,
    _parse_payload,
    build_auth_admin_router,
)


@dataclass
class _RegisterRequest:
    username: str
    password: str
    tenant_id: str = "default"


@dataclass
class _LoginRequest:
    username: str
    password: str


@dataclass
class _PromptRequest:
    role_name: str
    prompt_text: str
    activate: bool = False


@dataclass
class _PromptActivateRequest:
    prompt_id: str


@dataclass
class _PolicyRequest:
    user_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str
    effect: str


def _build_auth_exports(db: Any) -> dict[str, Any]:
    agent = SimpleNamespace(memory=SimpleNamespace(db=db))

    async def _resolve_agent_instance() -> Any:
        return agent

    async def _issue_auth_token(*_args: Any) -> str:
        return "token"

    router = build_auth_admin_router(
        resolve_agent_instance=_resolve_agent_instance,
        await_if_needed=lambda value: value,
        get_request_user=lambda: None,
        require_admin_user=lambda: None,
        issue_auth_token=_issue_auth_token,
        serialize_prompt=lambda _prompt: {},
        serialize_policy=lambda _policy: {},
        serialize_audit_log=lambda _audit_log: {},
        register_request_model=_RegisterRequest,
        login_request_model=_LoginRequest,
        prompt_upsert_request_model=_PromptRequest,
        prompt_activate_request_model=_PromptActivateRequest,
        policy_upsert_request_model=_PolicyRequest,
    )
    return router.legacy_exports


def _json_body(response: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(response.body))


def test_parse_payload_returns_raw_value_without_model_validate_or_mapping() -> None:
    marker = object()

    assert _parse_payload(_RegisterRequest, marker) is marker


def test_normalize_register_payload_supports_camel_case_aliases() -> None:
    payload = _normalize_register_payload(
        {"userName": "alice", "passWord": "secret1", "tenantId": "tenant-a"}
    )

    assert payload == {
        "userName": "alice",
        "passWord": "secret1",
        "tenantId": "tenant-a",
        "username": "alice",
        "password": "secret1",
        "tenant_id": "tenant-a",
    }


@pytest.mark.asyncio
async def test_register_user_maps_database_exception_to_conflict() -> None:
    def _register_user(**_kwargs: Any) -> Any:
        raise RuntimeError("duplicate username")

    register_user = _build_auth_exports(SimpleNamespace(register_user=_register_user))[
        "register_user"
    ]

    with pytest.raises(HTTPException, match="Kullanıcı oluşturulamadı: duplicate username") as exc:
        await register_user({"username": "alice", "password": "secret1"})

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_register_user_rejects_reserved_default_admin_without_db_call() -> None:
    def _register_user(**_kwargs: Any) -> Any:
        raise AssertionError("reserved usernames must be rejected before database registration")

    register_user = _build_auth_exports(SimpleNamespace(register_user=_register_user))[
        "register_user"
    ]

    with pytest.raises(HTTPException, match="rezerve") as exc:
        await register_user({"username": "  DEFAULT_ADMIN  ", "password": "secret1"})

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_stats_falls_back_to_database_provider() -> None:
    class _Database:
        async def get_admin_stats(self) -> dict[str, int]:
            return {"users": 3}

    admin_stats = _build_auth_exports(_Database())["admin_stats"]

    response = await admin_stats()

    assert _json_body(response) == {"users": 3}
