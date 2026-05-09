"""Distributed lock helpers for cross-pod Sidar coordination."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class DistributedLockLease:
    """Acquired lock metadata used to safely release a Redis lease."""

    key: str
    token: str
    ttl_ms: int
    backend: str = "redis"


class RedisDistributedLock:
    """Small Redis SET NX PX based lock for best-effort cross-process exclusion.

    The lock is intentionally lease-based: if the owner pod dies, Redis expires the
    key and another pod can make progress. Release uses a token-checked Lua script
    so one pod cannot delete another pod's renewed/reacquired lease.
    """

    def __init__(self, redis: Any, *, timeout_seconds: float = 0.25) -> None:
        self._redis = redis
        self._timeout_seconds = max(0.05, float(timeout_seconds or 0.25))

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        max_connections: int = 10,
        timeout_seconds: float = 0.25,
    ) -> RedisDistributedLock:
        client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            max_connections=max(1, int(max_connections or 10)),
        )
        return cls(client, timeout_seconds=timeout_seconds)

    async def acquire(self, key: str, *, ttl_seconds: int) -> DistributedLockLease | None:
        """Return a lease when acquired, or ``None`` when another owner holds it."""
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("Distributed lock key cannot be empty")
        ttl_ms = max(1000, int(ttl_seconds or 1) * 1000)
        token = secrets.token_urlsafe(24)
        acquired = await asyncio.wait_for(
            self._redis.set(normalized_key, token, nx=True, px=ttl_ms),
            timeout=self._timeout_seconds,
        )
        if not acquired:
            return None
        return DistributedLockLease(key=normalized_key, token=token, ttl_ms=ttl_ms)

    async def release(self, lease: DistributedLockLease) -> bool:
        """Release only the lock still owned by ``lease``."""
        released = await asyncio.wait_for(
            self._redis.eval(_RELEASE_LOCK_SCRIPT, 1, lease.key, lease.token),
            timeout=self._timeout_seconds,
        )
        return int(released or 0) == 1

    async def close(self) -> None:
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is None:
            return
        result = close()
        if asyncio.iscoroutine(result):
            await result
