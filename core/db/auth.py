"""Authentication domain boundary for the ``core.db`` package.

Houses the user/token record types and the PBKDF2 password helpers along
with their latency/SLO instrumentation. ``core.db`` re-exports these
names for backwards compatibility while internal callers gradually
migrate to the boundary import path.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_MIN_ITERATIONS = 600000
_PBKDF2_LEGACY_ITERATIONS = 120000
_PBKDF2_ITERATIONS_ENV = "SIDAR_PBKDF2_ITERATIONS"
_AUTH_HASH_SLO_MS_ENV = "SIDAR_AUTH_HASH_SLO_MS"


@dataclass
class UserRecord:
    id: str
    username: str
    role: str
    created_at: str
    tenant_id: str = "default"


@dataclass
class AuthTokenRecord:
    token: str
    user_id: str
    expires_at: str
    created_at: str


def _current_pbkdf2_iterations() -> int:
    """Return the configured PBKDF2 work factor without allowing insecure downgrades."""
    raw_value = os.getenv(_PBKDF2_ITERATIONS_ENV, "").strip()
    if not raw_value:
        return _PBKDF2_MIN_ITERATIONS
    try:
        configured = int(raw_value)
    except ValueError:
        logger.warning(
            "%s geçersiz (%r); PBKDF2 varsayılanı %s kullanılacak.",
            _PBKDF2_ITERATIONS_ENV,
            raw_value,
            _PBKDF2_MIN_ITERATIONS,
        )
        return _PBKDF2_MIN_ITERATIONS
    if configured < _PBKDF2_MIN_ITERATIONS:
        logger.warning(
            "%s=%s güvenli minimum %s altında; minimum değer kullanılacak.",
            _PBKDF2_ITERATIONS_ENV,
            configured,
            _PBKDF2_MIN_ITERATIONS,
        )
        return _PBKDF2_MIN_ITERATIONS
    return configured


def _auth_hash_slo_ms() -> int:
    raw_value = os.getenv(_AUTH_HASH_SLO_MS_ENV, "").strip()
    if not raw_value:
        return 120
    try:
        configured = int(raw_value)
    except ValueError:
        logger.warning(
            "%s geçersiz (%r); auth hash SLO varsayılanı 120 ms kullanılacak.",
            _AUTH_HASH_SLO_MS_ENV,
            raw_value,
        )
        return 120
    return max(configured, 1)


def _record_auth_hash_latency(operation: str, status: str, duration_s: float) -> None:
    from core.agent_metrics import get_agent_metrics_collector

    collector = get_agent_metrics_collector()
    collector.record_auth_hash_latency(
        operation,
        status,
        duration_s,
        slo_ms=_auth_hash_slo_ms(),
    )


def _pbkdf2_sha256(password: str, salt: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return digest.hex()


def _hash_password(password: str, salt: str | None = None) -> str:
    real_salt = salt or secrets.token_hex(16)
    # OWASP güncel rehberleriyle uyumlu iş faktörü (kurumsal dağıtım varsayılanı).
    iterations = _current_pbkdf2_iterations()
    started = time.perf_counter()
    status = "ok"
    try:
        digest_hex = _pbkdf2_sha256(password, real_salt, iterations)
        return f"{_PBKDF2_ALGORITHM}${iterations}${real_salt}${digest_hex}"
    except Exception:
        status = "error"
        raise
    finally:
        _record_auth_hash_latency("hash", status, time.perf_counter() - started)


def _verify_password(password: str, encoded: str) -> bool:
    started = time.perf_counter()
    status = "invalid"
    parts = encoded.split("$")
    try:
        if len(parts) == 4:
            algorithm, iterations_text, salt, expected_hex = parts
            if algorithm != _PBKDF2_ALGORITHM:
                return False
            try:
                iterations = int(iterations_text)
            except ValueError:
                return False
            actual_hex = _pbkdf2_sha256(password, salt, iterations)
            is_valid = secrets.compare_digest(actual_hex, expected_hex)
            status = "ok" if is_valid else "mismatch"
            return is_valid

        if len(parts) == 3:
            algorithm, salt, expected_hex = parts
            if algorithm != _PBKDF2_ALGORITHM:
                return False
            configured_hex = _pbkdf2_sha256(password, salt, _current_pbkdf2_iterations())
            current_hex = _pbkdf2_sha256(password, salt, _PBKDF2_MIN_ITERATIONS)
            legacy_hex = _pbkdf2_sha256(password, salt, _PBKDF2_LEGACY_ITERATIONS)
            is_valid = (
                secrets.compare_digest(configured_hex, expected_hex)
                or secrets.compare_digest(current_hex, expected_hex)
                or secrets.compare_digest(legacy_hex, expected_hex)
            )
            status = "ok" if is_valid else "mismatch"
            return is_valid

        return False
    except Exception:
        status = "error"
        raise
    finally:
        _record_auth_hash_latency("verify", status, time.perf_counter() - started)


__all__ = [
    "AuthTokenRecord",
    "UserRecord",
    "_auth_hash_slo_ms",
    "_current_pbkdf2_iterations",
    "_hash_password",
    "_pbkdf2_sha256",
    "_record_auth_hash_latency",
    "_verify_password",
]
