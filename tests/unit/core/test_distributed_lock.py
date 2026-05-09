import asyncio

import pytest

from core.distributed_lock import DistributedLockLease, RedisDistributedLock

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self, *, acquire_result=True, release_result=1) -> None:
        self.acquire_result = acquire_result
        self.release_result = release_result
        self.set_calls = []
        self.eval_calls = []
        self.closed = False

    async def set(self, key, token, *, nx, px):
        self.set_calls.append((key, token, nx, px))
        return self.acquire_result

    async def eval(self, script, numkeys, key, token):
        self.eval_calls.append((script, numkeys, key, token))
        return self.release_result

    async def aclose(self):
        self.closed = True


async def test_redis_distributed_lock_acquire_and_token_checked_release() -> None:
    redis = FakeRedis(acquire_result=True, release_result=1)
    lock = RedisDistributedLock(redis, timeout_seconds=0.1)

    lease = await lock.acquire("sidar:test-lock", ttl_seconds=5)

    assert isinstance(lease, DistributedLockLease)
    assert lease.key == "sidar:test-lock"
    assert lease.ttl_ms == 5000
    [(key, token, nx, px)] = redis.set_calls
    assert key == "sidar:test-lock"
    assert token == lease.token
    assert nx is True
    assert px == 5000

    assert await lock.release(lease) is True
    assert redis.eval_calls[0][1:] == (1, "sidar:test-lock", lease.token)

    await lock.close()
    assert redis.closed is True


async def test_redis_distributed_lock_returns_none_when_lease_is_busy() -> None:
    redis = FakeRedis(acquire_result=False)
    lock = RedisDistributedLock(redis, timeout_seconds=0.1)

    assert await lock.acquire("sidar:test-lock", ttl_seconds=5) is None


async def test_redis_distributed_lock_rejects_empty_keys() -> None:
    lock = RedisDistributedLock(FakeRedis(), timeout_seconds=0.1)

    with pytest.raises(ValueError, match="key cannot be empty"):
        await lock.acquire("   ", ttl_seconds=5)


async def test_redis_distributed_lock_surfaces_timeout() -> None:
    class SlowRedis(FakeRedis):
        async def set(self, key, token, *, nx, px):
            await asyncio.sleep(0.2)
            return True

    lock = RedisDistributedLock(SlowRedis(), timeout_seconds=0.05)

    with pytest.raises(TimeoutError):
        await lock.acquire("sidar:test-lock", ttl_seconds=5)
