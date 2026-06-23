"""Authentication records and password helpers for ``core.db``."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import low_level as argon2_low_level

logger = logging.getLogger(__name__)


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


_ARGON2ID_ALGORITHM = "argon2id"
_ARGON2ID_VERSION = argon2_low_level.ARGON2_VERSION
_ARGON2ID_MEMORY_COST_KIB = 7168
_ARGON2ID_TIME_COST = 5
_ARGON2ID_PARALLELISM = 1
_ARGON2ID_HASH_LEN = 32
_ARGON2ID_SALT_BYTES = 16
_ARGON2ID_MEMORY_COST_ENV = "SIDAR_ARGON2ID_MEMORY_COST_KIB"
_ARGON2ID_TIME_COST_ENV = "SIDAR_ARGON2ID_TIME_COST"
_ARGON2ID_PARALLELISM_ENV = "SIDAR_ARGON2ID_PARALLELISM"
_PASSWORD_HASH_ALGORITHM_ENV = "SIDAR_PASSWORD_HASH_ALGORITHM"
_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_MIN_ITERATIONS = 600000
_PBKDF2_LEGACY_ITERATIONS = 120000
_PBKDF2_ITERATIONS_ENV = "SIDAR_PBKDF2_ITERATIONS"
_AUTH_HASH_SLO_MS_ENV = "SIDAR_AUTH_HASH_SLO_MS"


def _read_int_env_with_floor(env_key: str, default: int, minimum: int) -> int:
    raw_value = os.getenv(env_key, "").strip()
    if not raw_value:
        return default
    try:
        configured = int(raw_value)
    except ValueError:
        logger.warning("%s geçersiz (%r); varsayılan %s kullanılacak.", env_key, raw_value, default)
        return default
    if configured < minimum:
        logger.warning("%s=%s güvenli minimum %s altında; minimum değer kullanılacak.", env_key, configured, minimum)
        return minimum
    return configured


def _current_password_hash_algorithm() -> str:
    """Resolve the preferred password hashing algorithm for newly stored hashes."""
    raw_value = os.getenv(_PASSWORD_HASH_ALGORITHM_ENV, _ARGON2ID_ALGORITHM).strip().lower()
    if raw_value in {_ARGON2ID_ALGORITHM, _PBKDF2_ALGORITHM}:
        return raw_value
    logger.warning(
        "%s=%r desteklenmiyor; Argon2id varsayılanı kullanılacak.",
        _PASSWORD_HASH_ALGORITHM_ENV,
        raw_value,
    )
    return _ARGON2ID_ALGORITHM


def _minimum_argon2id_time_cost(memory_cost: int) -> int:
    """Map Argon2id memory to OWASP's equal-defense minimum time-cost ladder."""
    if memory_cost < 9216:
        return 5
    if memory_cost < 12288:
        return 4
    if memory_cost < 19456:
        return 3
    if memory_cost < 47104:
        return 2
    return 1


def _current_argon2id_params() -> dict[str, int]:
    """Return OWASP-aligned Argon2id parameters with safe lower bounds."""
    memory_cost = _read_int_env_with_floor(
        _ARGON2ID_MEMORY_COST_ENV, _ARGON2ID_MEMORY_COST_KIB, 7168
    )
    min_time_cost = _minimum_argon2id_time_cost(memory_cost)
    time_cost = _read_int_env_with_floor(
        _ARGON2ID_TIME_COST_ENV, _ARGON2ID_TIME_COST, min_time_cost
    )
    return {
        "memory_cost": memory_cost,
        "time_cost": time_cost,
        "parallelism": _read_int_env_with_floor(
            _ARGON2ID_PARALLELISM_ENV, _ARGON2ID_PARALLELISM, 1
        ),
    }


def _current_pbkdf2_iterations() -> int:
    """Return the configured PBKDF2 work factor without allowing insecure downgrades."""
    return _read_int_env_with_floor(
        _PBKDF2_ITERATIONS_ENV,
        _PBKDF2_MIN_ITERATIONS,
        _PBKDF2_MIN_ITERATIONS,
    )


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


def _argon2id_hash(
    password: str,
    salt_hex: str,
    *,
    memory_cost: int,
    time_cost: int,
    parallelism: int,
) -> str:
    digest = argon2_low_level.hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=_ARGON2ID_HASH_LEN,
        type=argon2_low_level.Type.ID,
        version=_ARGON2ID_VERSION,
    )
    return digest.hex()


def _hash_password(password: str, salt: str | None = None) -> str:
    real_salt = salt or secrets.token_hex(_ARGON2ID_SALT_BYTES)
    algorithm = _current_password_hash_algorithm()
    started = time.perf_counter()
    status = "ok"
    try:
        if algorithm == _PBKDF2_ALGORITHM:
            iterations = _current_pbkdf2_iterations()
            digest_hex = _pbkdf2_sha256(password, real_salt, iterations)
            return f"{_PBKDF2_ALGORITHM}${iterations}${real_salt}${digest_hex}"

        params = _current_argon2id_params()
        digest_hex = _argon2id_hash(password, real_salt, **params)
        return (
            f"{_ARGON2ID_ALGORITHM}$v={_ARGON2ID_VERSION}"
            f"$m={params['memory_cost']},t={params['time_cost']},p={params['parallelism']}"
            f"${real_salt}${digest_hex}"
        )
    except Exception:
        status = "error"
        raise
    finally:
        _record_auth_hash_latency("hash", status, time.perf_counter() - started)


def _parse_argon2id_params(params_text: str) -> dict[str, int] | None:
    params: dict[str, int] = {}
    for item in params_text.split(","):
        key, sep, value = item.partition("=")
        if not sep:
            return None
        if key not in {"m", "t", "p"}:
            return None
        try:
            params[key] = int(value)
        except ValueError:
            return None
    if not {"m", "t", "p"}.issubset(params):
        return None
    return {
        "memory_cost": params["m"],
        "time_cost": params["t"],
        "parallelism": params["p"],
    }


def _verify_argon2id_password(password: str, parts: list[str]) -> bool:
    if len(parts) != 5:
        return False
    _, version_text, params_text, salt_hex, expected_hex = parts
    if version_text != f"v={_ARGON2ID_VERSION}":
        return False
    params = _parse_argon2id_params(params_text)
    if params is None:
        return False
    try:
        actual_hex = _argon2id_hash(password, salt_hex, **params)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual_hex, expected_hex)


def _verify_pbkdf2_password(password: str, parts: list[str]) -> bool:
    if len(parts) == 4:
        algorithm, iterations_text, salt, expected_hex = parts
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        try:
            iterations = int(iterations_text)
        except ValueError:
            return False
        actual_hex = _pbkdf2_sha256(password, salt, iterations)
        return secrets.compare_digest(actual_hex, expected_hex)

    if len(parts) == 3:
        algorithm, salt, expected_hex = parts
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        configured_hex = _pbkdf2_sha256(password, salt, _current_pbkdf2_iterations())
        current_hex = _pbkdf2_sha256(password, salt, _PBKDF2_MIN_ITERATIONS)
        legacy_hex = _pbkdf2_sha256(password, salt, _PBKDF2_LEGACY_ITERATIONS)
        return (
            secrets.compare_digest(configured_hex, expected_hex)
            or secrets.compare_digest(current_hex, expected_hex)
            or secrets.compare_digest(legacy_hex, expected_hex)
        )
    return False


def _verify_password(password: str, encoded: str) -> bool:
    started = time.perf_counter()
    status = "invalid"
    parts = encoded.split("$")
    try:
        algorithm = parts[0] if parts else ""
        if algorithm == _ARGON2ID_ALGORITHM:
            is_valid = _verify_argon2id_password(password, parts)
        elif algorithm == _PBKDF2_ALGORITHM:
            is_valid = _verify_pbkdf2_password(password, parts)
        else:
            return False
        status = "ok" if is_valid else "mismatch"
        return is_valid
    except Exception:
        status = "error"
        raise
    finally:
        _record_auth_hash_latency("verify", status, time.perf_counter() - started)


def _expires_in(days: int = 7) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


__all__ = [
    "AuthTokenRecord",
    "_ARGON2ID_ALGORITHM",
    "_ARGON2ID_HASH_LEN",
    "_ARGON2ID_MEMORY_COST_ENV",
    "_ARGON2ID_MEMORY_COST_KIB",
    "_minimum_argon2id_time_cost",
    "_ARGON2ID_PARALLELISM",
    "_ARGON2ID_PARALLELISM_ENV",
    "_ARGON2ID_SALT_BYTES",
    "_ARGON2ID_TIME_COST",
    "_ARGON2ID_TIME_COST_ENV",
    "_ARGON2ID_VERSION",
    "_AUTH_HASH_SLO_MS_ENV",
    "_PASSWORD_HASH_ALGORITHM_ENV",
    "_PBKDF2_ALGORITHM",
    "_PBKDF2_ITERATIONS_ENV",
    "_PBKDF2_LEGACY_ITERATIONS",
    "_PBKDF2_MIN_ITERATIONS",
    "UserRecord",
    "_argon2id_hash",
    "_auth_hash_slo_ms",
    "_current_argon2id_params",
    "_current_password_hash_algorithm",
    "_current_pbkdf2_iterations",
    "_expires_in",
    "_hash_password",
    "_parse_argon2id_params",
    "_pbkdf2_sha256",
    "_record_auth_hash_latency",
    "_verify_argon2id_password",
    "_verify_password",
    "_verify_pbkdf2_password",
]
