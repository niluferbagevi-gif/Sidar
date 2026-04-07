"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config():
    return make_test_config


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def fake_httpx_classes():
    return SimpleNamespace(
        FakeResponse=FakeResponse,
        FakeStreamCM=FakeStreamCM,
        FakeAsyncClient=FakeAsyncClient,
    )
def make_test_config(**overrides):
    base = {
        "LLM_MAX_RETRIES": 2,
        "LLM_RETRY_BASE_DELAY": 0.01,
        "LLM_RETRY_MAX_DELAY": 0.02,
        "ENABLE_SEMANTIC_CACHE": True,
        "SEMANTIC_CACHE_THRESHOLD": 0.9,
        "SEMANTIC_CACHE_TTL": 60,
        "SEMANTIC_CACHE_MAX_ITEMS": 2,
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_MAX_CONNECTIONS": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakePipe:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def hset(self, key: str, mapping: dict[str, str]):
        self.ops.append(("hset", key, mapping))

    def expire(self, key: str, ttl: int):
        self.ops.append(("expire", key, ttl))

    def lrem(self, _index_key: str, _count: int, key: str):
        self.ops.append(("lrem", key))

    def lpush(self, _index_key: str, key: str):
        self.ops.append(("lpush", key))

    def ltrim(self, _index_key: str, _start: int, end: int):
        self.ops.append(("ltrim", end))

    async def execute(self):
        for op in self.ops:
            if op[0] == "hset":
                self.redis.hashes[op[1]] = op[2]
            elif op[0] == "lrem":
                self.redis.index = [k for k in self.redis.index if k != op[1]]
            elif op[0] == "lpush":
                self.redis.index.insert(0, op[1])
            elif op[0] == "ltrim":
                self.redis.index = self.redis.index[: op[1] + 1]


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.index: list[str] = []

    async def lrange(self, _key: str, _start: int, _end: int):
        return list(self.index)

    async def hgetall(self, key: str):
        return self.hashes.get(key, {})

    async def llen(self, _key: str):
        return len(self.index)

    def pipeline(self, transaction: bool = True):
        return FakePipe(self)


class FakeResponse:
    def __init__(self, *, payload=None, lines=None, bytes_chunks=None, status_ok=True):
        self._payload = payload or {}
        self._lines = lines or []
        self._bytes_chunks = bytes_chunks or []
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            err = Exception("http")
            setattr(err, "status_code", 500)
            raise err

    def json(self):
        return self._payload

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aiter_bytes(self):
        for chunk in self._bytes_chunks:
            yield chunk


class FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *_exc):
        return False


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self._post_response = kwargs.pop("_post_response", None)
        self._get_response = kwargs.pop("_get_response", None)
        self._stream_response = kwargs.pop("_stream_response", None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_args, **_kwargs):
        return self._post_response or FakeResponse(payload={})

    async def get(self, *_args, **_kwargs):
        return self._get_response or FakeResponse(payload={})

    def stream(self, *_args, **_kwargs):
        return FakeStreamCM(self._stream_response or FakeResponse())

    async def aclose(self):
        return None
