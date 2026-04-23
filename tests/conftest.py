"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Callable, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

_REQUIRED_TEST_MODULES = {
    "pytest_asyncio": "pytest-asyncio",
    "freezegun": "freezegun",
    "sqlalchemy": "sqlalchemy",
    "testcontainers": "testcontainers",
}
_missing_test_deps = [pkg_name for module_name, pkg_name in _REQUIRED_TEST_MODULES.items() if importlib.util.find_spec(module_name) is None]
if _missing_test_deps:
    missing = ", ".join(sorted(set(_missing_test_deps)))
    raise pytest.UsageError(
        f"Eksik test bağımlılıkları: {missing}. Önce `uv sync --all-extras` çalıştırın."
    )

import pytest_asyncio
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from testcontainers.postgres import PostgresContainer

try:
    from core.db import Database
    from agent.core.event_stream import AgentEvent
    import agent.sidar_agent as sidar_agent_module
except ModuleNotFoundError as exc:
    raise pytest.UsageError(
        "Proje runtime bağımlılıkları eksik görünüyor. Önce `uv sync --all-extras` çalıştırın."
    ) from exc

from tests.helpers import make_test_config

_fakeredis_spec = importlib.util.find_spec("fakeredis")
fakeredis = importlib.import_module("fakeredis") if _fakeredis_spec is not None else None
TEST_REDIS_DECODE_RESPONSES = os.getenv("TEST_REDIS_DECODE_RESPONSES", "true").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_FREEZEGUN_IGNORE_MODULES = (
    "transformers",
    "tiktoken",
    "pydantic",
    # LLM ekosisteminde lazy-import zinciri yoğun paketler:
    "tokenizers",
    "langchain",
    "langchain_core",
    "langchain_community",
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Not: `cli` modülünü burada global olarak import etmiyoruz.
# Böylece pytest-cov ölçümü başlamadan önce `cli.py` yüklenip
# "already-imported" kaynaklı kapsama sapması oluşturmaz.


@pytest.fixture
def mock_config() -> Callable[..., Any]:
    return make_test_config


def _resolve_db_schema_target_version() -> int | None:
    """Test config'te tanımlıysa hedef şema versiyonunu döndürür; yoksa head kullanır."""
    cfg = make_test_config()
    return cfg.DB_SCHEMA_TARGET_VERSION if hasattr(cfg, "DB_SCHEMA_TARGET_VERSION") else None


def _build_freezegun_ignore_modules() -> list[str]:
    extra_raw = os.getenv("TEST_FREEZEGUN_IGNORE_MODULES", "")
    extras = [item.strip() for item in extra_raw.split(",") if item.strip()]
    # Aynı modülün tekrar eklenmesini önleyip deterministik sıra korur.
    return list(dict.fromkeys([*DEFAULT_FREEZEGUN_IGNORE_MODULES, *extras]))


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[Any, None]:
    if fakeredis is None:
        pytest.skip("fakeredis paketi kurulu değil; fake_redis fixture atlanıyor.")

    server = fakeredis.FakeServer()
    # Üretim tarafında event_stream / semantic cache / web_server Redis istemcileri decode_responses=True kullanır.
    # Varsayılanı aynı tutuyoruz; bytes davranışı test etmek için TEST_REDIS_DECODE_RESPONSES=false verilebilir.
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


@pytest.fixture
def fake_llm_response() -> Callable[..., Any]:
    """LLM istemcisi için deterministik, başarılı bir async yanıt döner."""

    async def _mock_response(
        prompt: str,
        mock_tool_calls: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        mock_tokens = kwargs.pop("mock_tokens", 10)
        _ = kwargs
        response: dict[str, Any] = {
            "content": f"mock-response:{prompt[:32]}",
            "usage": {"total_tokens": mock_tokens},
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
    """Ajan event stream çıktılarını deterministik ve güncel zamanla simüle eder."""

    async def _stream() -> AsyncGenerator[AgentEvent, None]:
        now = time.time()
        yield AgentEvent(ts=now, source="system", message="initializing")
        yield AgentEvent(ts=now + 1.0, source="assistant", message="İşlem tamam.")

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
    # metadata çoğu stream implementasyonunda property olarak okunur.
    # Bu yüzden dict ataması yapıp testlerde sessizce AsyncMock zincirlenmesini önlüyoruz.
    stream.metadata = {"fps": 25, "duration_sec": 2}
    # Gelecekte metadata async API'ye taşınırsa fixture davranışı uyumlu kalsın.
    stream.get_metadata = AsyncMock(return_value=stream.metadata)
    return stream


@pytest.fixture
def fake_video_stream_error() -> AsyncMock:
    """Video analiz pipeline'ı için bozuk akış/hata senaryosu."""
    stream = AsyncMock()
    stream.read_frames = AsyncMock(side_effect=RuntimeError("corrupted video stream"))
    stream.metadata = {"fps": 0, "duration_sec": 0}
    stream.get_metadata = AsyncMock(return_value=stream.metadata)
    return stream


@pytest_asyncio.fixture
async def fake_db_session(tmp_path: Path) -> AsyncGenerator[Any, None]:
    """SQLite üzerinde asenkron DB oturumu sağlar (entegrasyon benzeri testler için)."""
    sqlite_path = tmp_path / "fake_session.db"
    database_url = f"sqlite+aiosqlite:///{sqlite_path}"

    schema_cfg = SimpleNamespace(
        DATABASE_URL=database_url,
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=_resolve_db_schema_target_version(),
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    schema_db = Database(schema_cfg)
    await schema_db.connect()
    await schema_db.init_schema()
    await schema_db.close()

    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        async with SessionLocal() as db:
            try:
                yield db
            finally:
                await db.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_db(tmp_path) -> AsyncGenerator[Database, None]:
    cfg = SimpleNamespace(
        # Varsayılan test DB'si in-memory tutularak disk I/O ve flaky kilitlenmeler azaltılır.
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=_resolve_db_schema_target_version(),
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()

    try:
        yield db
    finally:
        await db.close()


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    """Her xdist worker için bağımsız PostgreSQL container başlatır."""
    try:
        with PostgresContainer("postgres:16-alpine") as container:
            yield container
    except Exception as exc:
        if os.getenv("CI"):
            pytest.fail(f"CI ortamında PostgreSQL container zorunludur! Başlatılamadı: {exc}")
        pytest.skip(f"PostgreSQL test container başlatılamadı: {exc}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_schema_initialized(pg_container: PostgresContainer) -> str:
    """PostgreSQL şemasını tüm test oturumu boyunca yalnızca bir kez hazırlar."""
    sync_url = pg_container.get_connection_url()
    async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1).replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )

    schema_cfg = SimpleNamespace(
        DATABASE_URL=async_url,
        BASE_DIR=".",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=_resolve_db_schema_target_version(),
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    schema_db = Database(schema_cfg)
    await schema_db.connect()
    await schema_db.init_schema()
    await schema_db.close()

    return async_url


@pytest_asyncio.fixture
async def pg_db_session(pg_schema_initialized: str) -> AsyncGenerator[Any, None]:
    """Test başına rollback + tablo temizliği ile izole edilmiş PostgreSQL oturumu."""
    engine = create_async_engine(pg_schema_initialized)
    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

    async def _truncate_public_tables() -> None:
        # Commit edilen verilerin sonraki testlere sızmasını engellemek için
        # public şemasındaki tüm kullanıcı tablolarını temizler.
        async with engine.begin() as conn:
            await conn.execute(text("""
                DO $$
                DECLARE r RECORD;
                BEGIN
                  FOR r IN
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename != 'schema_versions'
                  LOOP
                    EXECUTE format(
                      'TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE',
                      'public',
                      r.tablename
                    );
                  END LOOP;
                END $$;
            """))

    try:
        # Önceki testte yarım kalan/commit edilen veriler varsa sıfırla.
        await _truncate_public_tables()
        async with SessionLocal() as db:
            try:
                yield db
            finally:
                await db.rollback()
    finally:
        # Test başarısız olsa bile sonraki test için temiz başlangıç sağla.
        await _truncate_public_tables()
        await engine.dispose()


@pytest.fixture
def frozen_time() -> Generator[FrozenDateTimeFactory, None, None]:
    """Tüm zaman bağımlı operasyonları deterministik hale getirmek için ortak fixture."""
    # freezegun, loaded modüllerin attribute'larını gezerken transformers'ın lazy
    # import zincirini tetikleyebiliyor; bu da opsiyonel sentencepiece bağımlılığı
    # yoksa test setup sırasında patlamaya neden oluyor.
    with freeze_time("2026-04-01 12:00:00", ignore=_build_freezegun_ignore_modules()) as frozen:
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
    # Varsayılanı sıkı tut: test içinde kaydedilen her route en az bir kez çağrılmalı.
    with respx.mock(assert_all_called=True) as router:
        yield router


@pytest.fixture
def respx_mock_router_relaxed() -> Generator[Any, None, None]:
    """Bazı rotaların bilinçli olarak çağrılmadığı senaryolar için gevşek router."""
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

    mock_manager.run_pytest_and_collect = AsyncMock(return_value={
        "analysis": {"summary": "ok", "findings": []},
        "output": "OUT",
    })
    mock_manager.analyze_pytest_output = AsyncMock(side_effect=lambda output: {
        "summary": f"ANALYZED:{output}",
        "findings": [{"target_path": "src/m.py"}],
    })
    mock_manager.read_file = AsyncMock(side_effect=lambda path: (True, f"SOURCE:{path}"))
    mock_manager.write_generated_test = AsyncMock(side_effect=lambda path, content, append=True: (
        True,
        f"WROTE:{path}:{append}",
    ))

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
def fake_llm_tool_sequence() -> Callable[[list[str]], AsyncMock]:
    """Araç çağrısı akışları için sıralı LLM çıktısı üreten yardımcı fixture."""

    def _build(responses: list[str]) -> AsyncMock:
        return AsyncMock(side_effect=list(responses))

    return _build


@pytest.fixture
def fake_web_search_result() -> Callable[[bool, str], AsyncMock]:
    """Web arama katmanı için deterministik sonuç üreten yardımcı fixture."""

    def _build(ok: bool, payload: str) -> AsyncMock:
        return AsyncMock(return_value=(ok, payload))

    return _build

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
def mock_chromadb(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """chromadb/chromadb.config bağımlılıklarını gerçek modüller üstünden patch eder."""

    def _install(
        *,
        persistent_client_factory: Callable[..., Any],
        settings_factory: Callable[..., Any] | None = None,
    ) -> None:
        chromadb = pytest.importorskip("chromadb", exc_type=ImportError)
        chromadb_config = pytest.importorskip("chromadb.config", exc_type=ImportError)
        monkeypatch.setattr(chromadb, "PersistentClient", persistent_client_factory)
        if settings_factory is not None:
            monkeypatch.setattr(chromadb_config, "Settings", settings_factory)

    return _install


@pytest.fixture
def mock_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> Callable[[type], None]:
    """sentence_transformers bağımlılığını gerçek modül üstünden patch eder."""

    def _install(sentence_transformer_cls: type) -> None:
        sentence_transformers = pytest.importorskip("sentence_transformers")
        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", sentence_transformer_cls)

    return _install


@pytest.fixture
def mock_requests(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """requests bağımlılığını gerçek modül üstünden patch eder."""

    def _install(*, get_impl: Callable[..., Any]) -> None:
        requests = pytest.importorskip("requests")
        monkeypatch.setattr(requests, "get", get_impl)

    return _install
