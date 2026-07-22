"""Redis-oriented pytest fixtures."""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio

_fakeredis_spec = importlib.util.find_spec("fakeredis")
fakeredis = importlib.import_module("fakeredis") if _fakeredis_spec is not None else None
TEST_REDIS_DECODE_RESPONSES = os.getenv("TEST_REDIS_DECODE_RESPONSES", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[Any, None]:
    """Provide an isolated fakeredis async client matching production decoding defaults."""
    if fakeredis is None:
        pytest.skip("fakeredis paketi kurulu değil; fake_redis fixture atlanıyor.")

    server = fakeredis.FakeServer()
    # Üretim tarafında event_stream / semantic cache / web_server Redis istemcileri
    # decode_responses=True kullanır.
    # Varsayılanı aynı tutuyoruz; bytes davranışı test etmek için
    # TEST_REDIS_DECODE_RESPONSES=false verilebilir.
    redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=TEST_REDIS_DECODE_RESPONSES)
    try:
        yield redis
    finally:
        if hasattr(redis, "aclose"):
            await redis.aclose()
        else:
            await redis.close()
        if hasattr(server, "connected"):
            server.connected = False
