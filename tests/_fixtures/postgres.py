"""Database and PostgreSQL pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from testcontainers.postgres import PostgresContainer

from tests.helpers import make_test_config


def _resolve_db_schema_target_version() -> int | None:
    """Test config'te tanımlıysa hedef şema versiyonunu döndürür; yoksa head kullanır."""
    cfg = make_test_config()
    return cfg.DB_SCHEMA_TARGET_VERSION if hasattr(cfg, "DB_SCHEMA_TARGET_VERSION") else None


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
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    from core.db import Database

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
async def sqlite_db(tmp_path: Path) -> AsyncGenerator[Any, None]:
    """Provide an initialized in-memory SQLite Database instance."""
    cfg = SimpleNamespace(
        # Varsayılan test DB'si in-memory tutularak disk I/O ve flaky kilitlenmeler azaltılır.
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=_resolve_db_schema_target_version(),
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    from core.db import Database

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
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    from core.db import Database

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
            await conn.execute(
                text("""
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
            """)
            )

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
