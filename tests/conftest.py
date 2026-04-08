"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, AsyncGenerator, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from agent.core.event_stream import AgentEvent
import agent.sidar_agent as sidar_agent_module
from tests.helpers import make_test_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def mock_config() -> Callable[..., Any]:
    return make_test_config


@pytest.fixture
async def fake_redis() -> AsyncGenerator[Any, None]:
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
def fake_llm_error() -> Callable[..., Any]:
    """LLM istemcisi için deterministik hata (rate-limit/timeout) döner."""

    async def _mock_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = (args, kwargs)
        raise RuntimeError("rate limit exceeded")

    return _mock_error


@pytest.fixture
def fake_event_stream() -> Callable[[], AsyncGenerator[AgentEvent, None]]:
    """Ajan event stream çıktılarını deterministik olarak simüle eder."""

    async def _stream() -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent(ts=1.0, source="system", message="initializing")
        yield AgentEvent(ts=2.0, source="assistant", message="İşlem tamam.")

    return _stream


@pytest.fixture
def fake_social_api() -> AsyncMock:
    """Sosyal medya API çağrıları için ortak asenkron fake adaptör."""
    api = AsyncMock()
    api.fetch_profile.return_value = {"id": "user-1", "username": "mock_user", "followers": 42}
    api.fetch_posts.return_value = [{"id": "post-1", "text": "mock post", "likes": 7}]
    api.publish.return_value = {"ok": True, "post_id": "published-1"}

    def set_rate_limit_error() -> None:
        api.fetch_profile.side_effect = RuntimeError("API Rate Limit")

    def set_timeout_error() -> None:
        api.fetch_posts.side_effect = TimeoutError("API request timed out")

    api.set_rate_limit_error = set_rate_limit_error
    api.set_timeout_error = set_timeout_error
    return api


@pytest.fixture
def fake_video_stream() -> AsyncMock:
    """Video analiz pipeline'ı için deterministik asenkron fake akış."""
    stream = AsyncMock()
    stream.read_frames.return_value = [
        {"frame_id": 1, "timestamp": 0.0},
        {"frame_id": 2, "timestamp": 0.04},
    ]
    stream.metadata.return_value = {"fps": 25, "duration_sec": 2}
    return stream


@pytest.fixture
def fake_video_stream_error() -> AsyncMock:
    """Video analiz pipeline'ı için bozuk akış/hata senaryosu."""
    stream = AsyncMock()
    stream.read_frames.side_effect = RuntimeError("corrupted video stream")
    stream.metadata.return_value = {"fps": 0, "duration_sec": 0}
    return stream


@pytest.fixture
async def fake_db_session() -> AsyncGenerator[Any, None]:
    """In-memory SQLite için asenkron DB oturumu sağlar (entegrasyon benzeri testler için)."""
    asyncio_sqla = pytest.importorskip("sqlalchemy.ext.asyncio")
    orm = pytest.importorskip("sqlalchemy.orm")

    create_async_engine = asyncio_sqla.create_async_engine
    async_sessionmaker = asyncio_sqla.async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

    async with SessionLocal() as db:
        try:
            yield db
        finally:
            await db.rollback()
            await db.close()
            await engine.dispose()


@pytest.fixture
def frozen_time():
    """Tüm zaman bağımlı operasyonları deterministik hale getirmek için ortak fixture."""
    # freezegun, loaded modüllerin attribute'larını gezerken transformers'ın lazy
    # import zincirini tetikleyebiliyor; bu da opsiyonel sentencepiece bağımlılığı
    # yoksa test setup sırasında patlamaya neden oluyor.
    with freeze_time("2026-04-01 12:00:00", ignore=["transformers"]) as frozen:
        yield frozen


@pytest.fixture
def agent_factory(mock_config: Callable[..., Any]) -> Callable[..., Any]:
    """Testler için standartlaştırılmış ajan üretim fabrikası."""

    def _create_agent(agent_class: type, **kwargs: Any) -> Any:
        return agent_class(config=mock_config(), **kwargs)

    return _create_agent


@pytest.fixture
def sidar_agent_factory(mock_config: Callable[..., Any]) -> Callable[..., Any]:
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


@pytest.fixture
def fake_lsp_client() -> AsyncMock:
    """v5.x core/lsp.py testleri için deterministik Language Server Fake adaptörü."""
    client = AsyncMock()
    client.request_hover.return_value = {"contents": "mocked LSP hover documentation"}
    client.request_diagnostics.return_value = [
        {"line": 10, "message": "mocked error", "severity": 1},
    ]

    def set_timeout() -> None:
        client.request_hover.side_effect = TimeoutError("LSP connection timed out")

    client.set_timeout = set_timeout
    return client
