from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from web import security


class _Config:
    JWT_SECRET_KEY = "unit-secret-key-32-bytes-minimum"
    JWT_ALGORITHM = "HS256"
    JWT_TTL_DAYS = 2
    METRICS_TOKEN = "metrics-token"


class _Logger:
    def __init__(self) -> None:
        self.critical_messages: list[str] = []

    def critical(self, message: str) -> None:
        self.critical_messages.append(message)


def test_extract_ws_header_token_preserves_sidar_protocol_without_echoing_token() -> None:
    token, protocol = security.extract_ws_header_token("sidar.chat.v1, opaque.jwt-token_123")

    assert token == "opaque.jwt-token_123"
    assert protocol == security.SIDAR_WS_CHAT_PROTOCOL
    assert protocol != token


def test_extract_ws_header_token_supports_raw_token_without_subprotocol_echo() -> None:
    token, protocol = security.extract_ws_header_token("raw-token-1")

    assert token == "raw-token-1"
    assert protocol is None


def test_extract_ws_header_token_supports_voice_and_hitl_fixed_protocols() -> None:
    voice_token, voice_protocol = security.extract_ws_header_token(
        "sidar.voice.v1, voice-token", security.SIDAR_WS_VOICE_PROTOCOL
    )
    hitl_token, hitl_protocol = security.extract_ws_header_token(
        "sidar.hitl.v1, hitl-token", security.SIDAR_WS_HITL_PROTOCOL
    )

    assert voice_token == "voice-token"
    assert voice_protocol == security.SIDAR_WS_VOICE_PROTOCOL
    assert hitl_token == "hitl-token"
    assert hitl_protocol == security.SIDAR_WS_HITL_PROTOCOL


def test_extract_ws_header_token_ignores_invalid_token_but_accepts_fixed_protocol() -> None:
    token, protocol = security.extract_ws_header_token("sidar.chat.v1, bad token with spaces")

    assert token == ""
    assert protocol == security.SIDAR_WS_CHAT_PROTOCOL


def test_extract_ws_header_token_keeps_legacy_token_without_subprotocol_echo() -> None:
    token, protocol = security.extract_ws_header_token("legacy-token")

    assert token == "legacy-token"
    assert protocol is None


def test_get_jwt_secret_fails_closed_instead_of_dev_fallback() -> None:
    logger = _Logger()

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        security.get_jwt_secret(SimpleNamespace(JWT_SECRET_KEY=""), logger)
    assert logger.critical_messages


@pytest.mark.asyncio
async def test_resolve_user_from_token_uses_jwt_then_opaque_db_fallback() -> None:
    logger = _Logger()
    token = jwt.encode(
        {"sub": "42", "username": "ada", "role": "admin", "tenant_id": "team"},
        _Config.JWT_SECRET_KEY,
        algorithm=_Config.JWT_ALGORITHM,
    )

    user = await security.resolve_user_from_token(None, token, config=_Config, logger_obj=logger)

    assert user.id == "42"
    assert user.username == "ada"
    assert user.role == "admin"
    assert user.tenant_id == "team"

    class _DB:
        async def get_user_by_token(self, token_value: str):
            return SimpleNamespace(id="db", username="db-user") if token_value == "opaque" else None

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))
    fallback = await security.resolve_user_from_token(
        agent, "opaque", config=_Config, logger_obj=logger
    )

    assert fallback.id == "db"
    assert (
        await security.resolve_user_from_token(agent, "missing", config=_Config, logger_obj=logger)
        is None
    )


@pytest.mark.asyncio
async def test_issue_auth_token_embeds_expected_claims() -> None:
    user = SimpleNamespace(id="7", username="lin", role="editor", tenant_id="tenant")

    token = await security.issue_auth_token(None, user, config=_Config, logger_obj=_Logger())
    payload = jwt.decode(token, _Config.JWT_SECRET_KEY, algorithms=[_Config.JWT_ALGORITHM])

    assert payload["sub"] == "7"
    assert payload["username"] == "lin"
    assert payload["role"] == "editor"
    assert payload["tenant_id"] == "tenant"
    assert payload["exp"] > payload["iat"]


def test_request_admin_and_metrics_access_guards() -> None:
    request = SimpleNamespace(state=SimpleNamespace(), headers=Headers({}))

    with pytest.raises(HTTPException) as unauthorized:
        security.get_request_user(request)
    assert unauthorized.value.status_code == 401

    request.state.user = SimpleNamespace(role="admin", username="root")
    assert security.get_request_user(request) is request.state.user
    assert security.require_admin_user(request.state.user) is request.state.user

    regular = SimpleNamespace(role="user", username="ada")
    with pytest.raises(HTTPException) as forbidden_admin:
        security.require_admin_user(regular)
    assert forbidden_admin.value.status_code == 403

    metrics_request = SimpleNamespace(headers=Headers({"Authorization": "Bearer metrics-token"}))
    assert security.require_metrics_access(metrics_request, regular, config=_Config) is regular

    denied_request = SimpleNamespace(headers=Headers({}))
    with pytest.raises(HTTPException) as forbidden_metrics:
        security.require_metrics_access(denied_request, regular, config=_Config)
    assert forbidden_metrics.value.status_code == 403
