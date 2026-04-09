"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Callable, Generator
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
import sqlalchemy
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

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

    async def _mock_response(
        prompt: str,
        mock_tool_calls: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "content": f"mock-response:{prompt[:32]}",
            "usage": {"total_tokens": 10},
            "meta": kwargs,
        }
        if mock_tool_calls:
            response["tool_calls"] = mock_tool_calls
        return response

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
    api = AsyncMock(
        spec=[
            "fetch_profile",
            "fetch_posts",
            "publish",
            "set_rate_limit_error",
            "set_timeout_error",
        ]
    )
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
    stream.read_frames = AsyncMock(return_value=[
        {"frame_id": 1, "timestamp": 0.0},
        {"frame_id": 2, "timestamp": 0.04},
    ])
    stream.metadata = AsyncMock(return_value={"fps": 25, "duration_sec": 2})
    return stream


@pytest.fixture
def fake_video_stream_error() -> AsyncMock:
    """Video analiz pipeline'ı için bozuk akış/hata senaryosu."""
    stream = AsyncMock()
    stream.read_frames = AsyncMock(side_effect=RuntimeError("corrupted video stream"))
    stream.metadata = AsyncMock(return_value={"fps": 0, "duration_sec": 0})
    return stream


@pytest.fixture
async def fake_db_session() -> AsyncGenerator[Any, None]:
    """In-memory SQLite için asenkron DB oturumu sağlar (entegrasyon benzeri testler için)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        async with SessionLocal() as db:
            try:
                yield db
            finally:
                await db.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def pg_db_session() -> AsyncGenerator[Any, None]:
    """Docker üzerinde geçici PostgreSQL ile asenkron DB oturumu sağlar."""
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"PostgreSQL test container başlatılamadı: {exc}")

    try:
        sync_url = container.get_connection_url()
        max_retries = 10
        for attempt in range(max_retries):
            try:
                sync_engine = sqlalchemy.create_engine(sync_url)
                with sync_engine.connect():
                    pass
                sync_engine.dispose()
                break
            except sqlalchemy.exc.OperationalError:
                if attempt == max_retries - 1:
                    pytest.fail("PostgreSQL container başlatılamadı veya hazır değil.")
                time.sleep(0.5)

        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1).replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )
        engine = create_async_engine(async_url)
        SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

        try:
            async with SessionLocal() as db:
                try:
                    yield db
                finally:
                    await db.rollback()
        finally:
            await engine.dispose()
    finally:
        container.stop()


@pytest.fixture
def frozen_time() -> Generator[FrozenDateTimeFactory, None, None]:
    """Tüm zaman bağımlı operasyonları deterministik hale getirmek için ortak fixture."""
    # freezegun, loaded modüllerin attribute'larını gezerken transformers'ın lazy
    # import zincirini tetikleyebiliyor; bu da opsiyonel sentencepiece bağımlılığı
    # yoksa test setup sırasında patlamaya neden oluyor.
    with freeze_time(
        "2026-04-01 12:00:00",
        ignore=["transformers", "tiktoken", "pydantic"],
    ) as frozen:
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

    def _create_agent(**kwargs: Any) -> Any:
        # Config yalnızca cfg/config ile geçirilebilir; diğer override yollarını engelle.
        config = kwargs.pop("cfg", kwargs.pop("config", mock_config()))
        if kwargs:
            raise ValueError(
                "Lütfen config parametrelerini mock_config() üzerinden geçin. "
                "Örn: sidar_agent_factory(cfg=mock_config(USE_GPU=True))"
            )

        return sidar_agent_module.SidarAgent(config=config)

    return _create_agent




@pytest.fixture
def respx_mock_router() -> Generator[Any, None, None]:
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


@pytest.fixture
def fake_coverage_code_manager() -> MagicMock:
    """Coverage testleri için standart MagicMock kullanan code manager."""
    mock_manager = MagicMock()

    mock_manager.run_pytest_and_collect.return_value = {
        "analysis": {"summary": "ok", "findings": []},
        "output": "OUT",
    }
    mock_manager.analyze_pytest_output.side_effect = lambda output: {
        "summary": f"ANALYZED:{output}",
        "findings": [{"target_path": "src/m.py"}],
    }
    mock_manager.read_file.side_effect = lambda path: (True, f"SOURCE:{path}")
    mock_manager.write_generated_test.side_effect = lambda path, content, append=True: (
        True,
        f"WROTE:{path}:{append}",
    )

    return mock_manager


@pytest.fixture
def fake_coverage_db_class() -> type:
    """Coverage DB için AsyncMock kullanan factory sınıfı."""

    class _FakeCoverageDB:
        def __init__(self, cfg: Any) -> None:
            self.cfg = cfg
            self.connect = AsyncMock()
            self.init_schema = AsyncMock()
            self.create_coverage_task = AsyncMock(return_value=SimpleNamespace(id=123))
            self.add_coverage_finding = AsyncMock()

    return _FakeCoverageDB


@pytest.fixture
def fake_vector_store() -> AsyncMock:
    """core/rag.py testleri için deterministik vector DB adaptörü."""
    mock_store = AsyncMock(spec=["search", "add_documents", "delete", "set_empty_result", "set_db_error"])

    mock_store.search.return_value = [
        {"id": "doc-1", "content": "mock context for RAG", "score": 0.95},
        {"id": "doc-2", "content": "secondary context", "score": 0.88},
    ]
    mock_store.add_documents.return_value = True

    def set_empty_result() -> None:
        mock_store.search.side_effect = None
        mock_store.search.return_value = []

    def set_db_error() -> None:
        mock_store.search.side_effect = ConnectionError("Vector DB connection lost")

    mock_store.set_empty_result = set_empty_result
    mock_store.set_db_error = set_db_error
    return mock_store


@pytest.fixture
def mock_httpx(monkeypatch: pytest.MonkeyPatch) -> Callable[..., SimpleNamespace]:
    """httpx modülünü testte kontrollü şekilde enjekte eden yardımcı fixture."""

    def _install(
        *,
        client_factory: Callable[..., Any],
        timeout_exception: type[Exception] | None = None,
        request_error: type[Exception] | None = None,
    ) -> SimpleNamespace:
        module = SimpleNamespace(
            AsyncClient=client_factory,
            TimeoutException=timeout_exception or type("TimeoutException", (Exception,), {}),
            RequestError=request_error or type("RequestError", (Exception,), {}),
        )
        monkeypatch.setitem(sys.modules, "httpx", module)
        return module

    return _install


@pytest.fixture
def mock_chromadb(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """chromadb/chromadb.config modüllerini tek noktadan enjekte eder."""

    def _install(
        *,
        persistent_client_factory: Callable[..., Any],
        settings_factory: Callable[..., Any] | None = None,
    ) -> None:
        monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=persistent_client_factory))
        monkeypatch.setitem(
            sys.modules,
            "chromadb.config",
            SimpleNamespace(Settings=settings_factory or (lambda **_kwargs: object())),
        )

    return _install


@pytest.fixture
def mock_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> Callable[[type], None]:
    """sentence_transformers modülünü merkezi fixture ile taklit eder."""

    def _install(sentence_transformer_cls: type) -> None:
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            SimpleNamespace(SentenceTransformer=sentence_transformer_cls),
        )

    return _install


@pytest.fixture
def mock_requests(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """requests modülünü testte belirli davranışlarla enjekte eder."""

    def _install(*, get_impl: Callable[..., Any]) -> None:
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get_impl))

    return _install
