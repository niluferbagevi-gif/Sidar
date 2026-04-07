"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, AsyncGenerator, Callable
from unittest.mock import MagicMock

import pytest

from agent.core.event_stream import AgentEvent


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config():
    return make_test_config


@pytest.fixture
async def fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    try:
        yield redis
    finally:
        if hasattr(redis, "aclose"):
            await redis.aclose()
        else:
            await redis.close()


@pytest.fixture
def fake_llm_response() -> Callable[..., Any]:
    """LLM istemcisi için deterministik, başarılı bir async yanıt döner."""

    async def _mock_response(prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "content": f"mock-response:{prompt[:32]}",
            "usage": {"total_tokens": 10},
            "meta": kwargs,
        }

    return _mock_response


@pytest.fixture
def fake_event_stream() -> Callable[[], AsyncGenerator[AgentEvent, None]]:
    """Ajan event stream çıktılarını deterministik olarak simüle eder."""

    async def _stream() -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(ts=1.0, source="system", message="initializing")
        yield AgentEvent(ts=2.0, source="assistant", message="İşlem tamam.")

    return _stream


@pytest.fixture
def fake_social_api() -> MagicMock:
    """Sosyal medya API çağrıları için ortak fake adaptör."""
    api = MagicMock()
    api.fetch_profile.return_value = {"id": "user-1", "username": "mock_user", "followers": 42}
    api.fetch_posts.return_value = [{"id": "post-1", "text": "mock post", "likes": 7}]
    api.publish.return_value = {"ok": True, "post_id": "published-1"}
    return api


@pytest.fixture
def fake_video_stream() -> MagicMock:
    """Video analiz pipeline'ı için deterministik fake akış."""
    stream = MagicMock()
    stream.read_frames.return_value = [
        {"frame_id": 1, "timestamp": 0.0},
        {"frame_id": 2, "timestamp": 0.04},
    ]
    stream.metadata.return_value = {"fps": 25, "duration_sec": 2}
    return stream


@pytest.fixture
def agent_factory(mock_config: MagicMock) -> Callable[..., Any]:
    """Testler için standartlaştırılmış ajan üretim fabrikası."""

    def _create_agent(agent_class: type, **kwargs: Any) -> Any:
        return agent_class(config=mock_config, **kwargs)

    return _create_agent




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
        "COST_ROUTING_ENABLED": True,
        "COST_ROUTING_THRESHOLD": 0.05,
        "ENTITY_MEMORY_TTL": 3600,
        "MAX_MEMORY_ENTITIES": 100,
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
