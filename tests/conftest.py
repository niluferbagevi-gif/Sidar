"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, AsyncGenerator, Callable
from unittest.mock import MagicMock

import pytest

from agent.core.event_stream import AgentEvent
import agent.sidar_agent as sidar_agent_module
from tests.helpers import make_test_config


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
        if hasattr(server, "connected"):
            server.connected = False


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
def sidar_agent_factory(mock_config: MagicMock) -> Callable[..., Any]:
    """SidarAgent için test örneği üreticisi."""

    def _create_agent(**overrides: Any) -> Any:
        # Technical debt düzeltildi: Ajan standart inisyalizasyonla başlatılır.
        config = overrides.pop("cfg", mock_config())
        agent = sidar_agent_module.SidarAgent(config=config)

        # Yalnızca testin ezmesi gereken alanları override et.
        for key, value in overrides.items():
            setattr(agent, key, value)
        return agent

    return _create_agent




@pytest.fixture
def respx_mock_router():
    respx = pytest.importorskip("respx")
    with respx.mock(assert_all_called=False) as router:
        yield router
