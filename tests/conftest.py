"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock

import fakeredis
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config():
    return make_test_config()


@pytest.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    try:
        yield redis
    finally:
        close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
        if callable(close):
            maybe = close()
            if hasattr(maybe, "__await__"):
                await maybe




@pytest.fixture
def respx_mock_router():
    respx = pytest.importorskip("respx")
    with respx.mock(assert_all_called=False) as router:
        yield router


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

    mock_cfg = MagicMock()
    for key, value in base.items():
        setattr(mock_cfg, key, value)

    mock_cfg.initialize_directories.return_value = True
    mock_cfg.validate_critical_settings.return_value = True

    return mock_cfg



async def collect_async_chunks(gen):
    return [chunk async for chunk in gen]
