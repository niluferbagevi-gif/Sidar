"""Rate limit, Redis and dependency-health settings for ``config.Config``."""

from __future__ import annotations

from dataclasses import dataclass

from core.config_env_helpers import (
    get_bool_env,
    get_float_prefixed_env,
    get_int_env,
    get_int_prefixed_env,
    get_list_env,
    get_prefixed_env,
)


@dataclass(frozen=True)
class RateLimitSettings:
    """API rate-limit, Redis and dependency healthcheck settings."""

    sidar_rate_limit_window: int
    sidar_rate_limit_chat: int
    sidar_rate_limit_mutations: int
    sidar_rate_limit_get_io: int
    sidar_redis_url: str
    sidar_redis_max_connections: int
    sidar_redis_connect_timeout: float
    sidar_redis_socket_timeout: float
    enable_distributed_agent_locks: bool
    distributed_agent_lock_required: bool
    distributed_agent_lock_ttl_seconds: int
    distributed_agent_lock_timeout_ms: int
    enable_dependency_healthchecks: bool
    healthcheck_connect_timeout_ms: int
    trusted_proxies: frozenset[str]
    max_rag_upload_bytes: int


# mypy/pyright-friendly alias for the small LLM settings surface this loader needs.
def load_rate_limit_settings(*, redis_max_connections_default: int) -> RateLimitSettings:
    """Load rate-limit, Redis and dependency-health settings from environment."""

    return RateLimitSettings(
        sidar_rate_limit_window=get_int_prefixed_env(
            "SIDAR_RATE_LIMIT_WINDOW", "RATE_LIMIT_WINDOW", 60
        ),
        sidar_rate_limit_chat=get_int_prefixed_env("SIDAR_RATE_LIMIT_CHAT", "RATE_LIMIT_CHAT", 20),
        sidar_rate_limit_mutations=get_int_prefixed_env(
            "SIDAR_RATE_LIMIT_MUTATIONS", "RATE_LIMIT_MUTATIONS", 60
        ),
        sidar_rate_limit_get_io=get_int_prefixed_env(
            "SIDAR_RATE_LIMIT_GET_IO", "RATE_LIMIT_GET_IO", 30
        ),
        sidar_redis_url=get_prefixed_env(
            "SIDAR_REDIS_URL", "REDIS_URL", "redis://localhost:6379/0"
        ),
        sidar_redis_max_connections=get_int_prefixed_env(
            "SIDAR_REDIS_MAX_CONNECTIONS",
            "REDIS_MAX_CONNECTIONS",
            redis_max_connections_default,
        ),
        sidar_redis_connect_timeout=get_float_prefixed_env(
            "SIDAR_REDIS_CONNECT_TIMEOUT", "REDIS_CONNECT_TIMEOUT", 0.5
        ),
        sidar_redis_socket_timeout=get_float_prefixed_env(
            "SIDAR_REDIS_SOCKET_TIMEOUT", "REDIS_SOCKET_TIMEOUT", 0.5
        ),
        enable_distributed_agent_locks=get_bool_env("ENABLE_DISTRIBUTED_AGENT_LOCKS", True),
        distributed_agent_lock_required=get_bool_env("DISTRIBUTED_AGENT_LOCK_REQUIRED", False),
        distributed_agent_lock_ttl_seconds=get_int_env("DISTRIBUTED_AGENT_LOCK_TTL_SECONDS", 1800),
        distributed_agent_lock_timeout_ms=get_int_env("DISTRIBUTED_AGENT_LOCK_TIMEOUT_MS", 250),
        enable_dependency_healthchecks=get_bool_env("ENABLE_DEPENDENCY_HEALTHCHECKS", False),
        healthcheck_connect_timeout_ms=get_int_env("HEALTHCHECK_CONNECT_TIMEOUT_MS", 250),
        trusted_proxies=frozenset(get_list_env("TRUSTED_PROXIES", ["127.0.0.1"])),
        max_rag_upload_bytes=get_int_env("MAX_RAG_UPLOAD_BYTES", 50 * 1024 * 1024),
    )
