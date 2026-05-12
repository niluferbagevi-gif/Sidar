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


async def test_redis_distributed_lock_from_url_configures_bounded_client(monkeypatch) -> None:
    import core.distributed_lock as distributed_lock

    captured = {}
    fake_client = FakeRedis()

    def fake_from_url(redis_url, **kwargs):
        captured["redis_url"] = redis_url
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(distributed_lock.Redis, "from_url", fake_from_url)

    lock = RedisDistributedLock.from_url(
        "redis://cache:6379/0", max_connections=0, timeout_seconds=0.75
    )

    assert lock._redis is fake_client
    assert lock._timeout_seconds == 0.75
    assert captured == {
        "redis_url": "redis://cache:6379/0",
        "decode_responses": True,
        "socket_connect_timeout": 0.75,
        "socket_timeout": 0.75,
        "max_connections": 10,
    }


async def test_redis_distributed_lock_release_surfaces_timeout() -> None:
    class SlowReleaseRedis(FakeRedis):
        async def eval(self, script, numkeys, key, token):
            await asyncio.sleep(0.2)
            return 1

    lock = RedisDistributedLock(SlowReleaseRedis(), timeout_seconds=0.05)
    lease = DistributedLockLease(key="sidar:test-lock", token="token", ttl_ms=1000)

    with pytest.raises(TimeoutError):
        await lock.release(lease)


async def test_redis_distributed_lock_surfaces_redis_disconnects() -> None:
    from redis.exceptions import ConnectionError

    class DisconnectingRedis(FakeRedis):
        async def set(self, key, token, *, nx, px):
            raise ConnectionError("redis connection lost during acquire")

        async def eval(self, script, numkeys, key, token):
            raise ConnectionError("redis connection lost during release")

    lock = RedisDistributedLock(DisconnectingRedis(), timeout_seconds=0.1)
    lease = DistributedLockLease(key="sidar:test-lock", token="token", ttl_ms=1000)

    with pytest.raises(ConnectionError, match="acquire"):
        await lock.acquire("sidar:test-lock", ttl_seconds=1)
    with pytest.raises(ConnectionError, match="release"):
        await lock.release(lease)


async def test_redis_distributed_lock_close_handles_missing_and_sync_close() -> None:
    class NoCloseRedis:
        pass

    await RedisDistributedLock(NoCloseRedis(), timeout_seconds=0.1).close()

    class SyncCloseRedis:
        def __init__(self) -> None:
            self.closed = False

        def close(self):
            self.closed = True
            return None

    redis = SyncCloseRedis()
    await RedisDistributedLock(redis, timeout_seconds=0.1).close()
    assert redis.closed is True


async def test_redis_distributed_lock_concurrent_acquire_only_one_winner() -> None:
    class ContendedRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self._held = False
            self._gate = asyncio.Lock()

        async def set(self, key, token, *, nx, px):
            async with self._gate:
                await asyncio.sleep(0)
                self.set_calls.append((key, token, nx, px))
                if self._held:
                    return False
                self._held = True
                return True

    redis = ContendedRedis()
    lock = RedisDistributedLock(redis, timeout_seconds=0.1)

    leases = await asyncio.gather(
        *[lock.acquire("sidar:contended", ttl_seconds=1) for _ in range(8)]
    )

    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1
    assert winners[0].key == "sidar:contended"
    assert len(redis.set_calls) == 8
