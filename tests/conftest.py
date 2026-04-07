"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import fakeredis
import fakeredis.aioredis
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config():
    return make_test_config


@pytest.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    try:
        yield redis
    finally:
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if callable(close):
            maybe = close()
            if hasattr(maybe, "__await__"):
                await maybe


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


async def collect_async_chunks(gen):
    return [chunk async for chunk in gen]
