"""Security and authentication helpers for Sidar's FastAPI surface.

The helpers in this module are intentionally framework-light so existing route
builders can depend on them while ``web_server.py`` keeps backward-compatible
wrapper names during the router modularization effort.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request

SIDAR_WS_CHAT_PROTOCOL = "sidar.chat.v1"
_WS_PROTOCOL_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{3,4096}$")


def parse_ws_subprotocol_values(raw_header: str) -> list[str]:
    """Return comma-separated WebSocket subprotocol values without empty items."""

    return [item.strip() for item in str(raw_header or "").split(",") if item.strip()]


def extract_ws_header_token(raw_header: str) -> tuple[str, str | None]:
    """Extract a websocket auth token without echoing raw tokens as subprotocols."""

    protocols = parse_ws_subprotocol_values(raw_header)
    if not protocols:
        return "", None
    accept_subprotocol = SIDAR_WS_CHAT_PROTOCOL if SIDAR_WS_CHAT_PROTOCOL in protocols else None
    for candidate in protocols:
        if candidate == SIDAR_WS_CHAT_PROTOCOL:
            continue
        if _WS_PROTOCOL_TOKEN_RE.fullmatch(candidate):
            return candidate, accept_subprotocol
    return "", accept_subprotocol


def build_user_from_jwt_payload(payload: dict[str, Any]) -> Any:
    """Build the lightweight request user object from validated JWT claims."""

    user_id = str(payload.get("sub", "") or "").strip()
    username = str(payload.get("username", "") or "").strip()
    role = str(payload.get("role", "user") or "user").strip() or "user"
    tenant_id = str(payload.get("tenant_id", "default") or "default").strip() or "default"
    if not user_id or not username:
        return None
    return SimpleNamespace(id=user_id, username=username, role=role, tenant_id=tenant_id)


def get_jwt_secret(config: Any, logger_obj: Any) -> str:
    """Read the JWT secret from config and log a critical development fallback warning."""

    key = str(getattr(config, "JWT_SECRET_KEY", "") or "")
    if not key:
        logger_obj.critical(
            "JWT_SECRET_KEY yapılandırılmamış! Geliştirme ortamında geçici bir "
            "anahtar kullanılıyor. Üretim ortamında .env dosyasına güçlü bir "
            "JWT_SECRET_KEY değeri eklemelisiniz."
        )
        key = "sidar-dev-secret"
    return key


async def resolve_user_from_token(agent: Any, token: str, *, config: Any, logger_obj: Any) -> Any:
    """Resolve a stateless JWT user, falling back to the legacy DB token lookup."""

    secret_key = get_jwt_secret(config, logger_obj)
    algorithm = str(getattr(config, "JWT_ALGORITHM", "HS256") or "HS256")
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return build_user_from_jwt_payload(payload)
    except jwt.PyJWTError:
        pass
    # Fallback: DB token lookup (opak / oturum tabanlı token desteği)
    if agent and hasattr(agent, "memory") and hasattr(agent.memory, "db"):
        db_user = await agent.memory.db.get_user_by_token(token)
        if db_user:
            return db_user
    return None


async def issue_auth_token(_agent: Any, user: Any, *, config: Any, logger_obj: Any) -> str:
    """Issue a stateless JWT for an authenticated Sidar user."""

    secret_key = get_jwt_secret(config, logger_obj)
    algorithm = str(getattr(config, "JWT_ALGORITHM", "HS256") or "HS256")
    ttl_days = max(1, int(getattr(config, "JWT_TTL_DAYS", 7) or 7))
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "username": str(user.username),
        "role": str(getattr(user, "role", "user") or "user"),
        "tenant_id": str(getattr(user, "tenant_id", "default") or "default"),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return str(jwt.encode(payload, secret_key, algorithm=algorithm))


def get_request_user(request: Request) -> Any:
    """Return the authenticated request user or raise a 401 response."""

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Yetkisiz erişim")
    return user


def is_admin_user(user: Any) -> bool:
    """Return whether the request user has Sidar admin privileges."""

    role = str(getattr(user, "role", "") or "").strip().lower()
    username = str(getattr(user, "username", "") or "").strip()
    return role == "admin" or username == "default_admin"


def require_admin_user(user: Any = Depends(get_request_user)) -> Any:
    """FastAPI dependency enforcing admin access."""

    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekiyor")
    return user


def require_metrics_access(request: Request, user: Any, *, config: Any) -> Any:
    """Allow metrics access for admin users or requests carrying METRICS_TOKEN."""

    metrics_token = str(getattr(config, "METRICS_TOKEN", "") or "").strip()
    if metrics_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].strip() == metrics_token:
            return user
    if is_admin_user(user):
        return user
    raise HTTPException(
        status_code=403, detail="Metrics erişimi için admin yetkisi veya METRICS_TOKEN gerekiyor"
    )
