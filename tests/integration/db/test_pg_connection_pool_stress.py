"""PostgreSQL bağlantı havuzu (asyncpg pool) altında eşzamanlı yük testleri.

``.github/workflows/ci.yml``'deki ``pg-stress`` job'ı bir PostgreSQL 16 servis
konteyneri ayağa kaldırıp ``DATABASE_URL``'i ona işaret ettiriyor, şemayı
``alembic upgrade head`` ile migrate ediyor ve ardından yalnızca
``-m pg_stress`` ile işaretlenmiş testleri çalıştırıyor
(``uv run pytest -v -m pg_stress tests/integration/db/ --timeout=120 -x``).

``pg_stress`` marker'ı ``pyproject.toml``'da kayıtlıydı ve
``tests/_fixtures/postgres.py`` içinde gerçek bir Postgres'e karşı test
çalıştırmak için testcontainers tabanlı fixture'lar (``pg_container``,
``pg_schema_initialized``, ``pg_db_session``) hazırdı, ancak repo genelinde
bu marker'ı taşıyan tek bir test bile yoktu (bkz. ``gpu_stress`` marker'ı ile
karşılaştırma — o, ``tests/performance/test_gpu_benchmark.py`` ve
``tests/smoke/test_gpu_inference.py``'de gerçek testlere uygulanmış). Sonuç:
job her gerçekten çalıştığında (``needs: production-readiness`` zinciri genelde
self-hosted runner kullanılabilirliğine takılıp job'ı skip/cancel ettiği için
bu nadirdi) ``pytest -m pg_stress`` 9 test topluyor, 9'unu da eleyip
"0 selected" ile exit code 5 (pytest'in "test toplanamadı" kodu) veriyordu.
Bu, ``main`` üzerinde de aynı şekilde mevcuttu (marker orada da hiçbir teste
uygulanmamıştı) — bu PR'ın diff'inin sebep olduğu bir regresyon değil.

Bu dosya, job'ın adının vaat ettiği şeyi -- gerçek bir bağlantı havuzunu
eşzamanlı yük altında sınamayı -- yapan testleri sağlar. Havuzu doğrudan
``core.db.Database`` üzerinden, CI job'ının zaten sağladığı ``DATABASE_URL``
ortam değişkeniyle kurar (ayrı bir testcontainers Postgres'i başlatmak yerine
job'ın kendi servis konteynerini kullanır); yerelde gerçek bir PostgreSQL
``DATABASE_URL``'i yoksa nazikçe skip eder.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from core.db import Database

pytestmark = [pytest.mark.pg_stress, pytest.mark.asyncio]


def _postgres_database_url() -> str | None:
    """``DATABASE_URL`` gerçekten bir PostgreSQL DSN'i mi işaret ediyor kontrol eder."""
    url = os.environ.get("DATABASE_URL", "")
    lowered = url.lower()
    if lowered.startswith("postgresql://") or lowered.startswith("postgresql+asyncpg://"):
        return url
    return None


def _require_postgres_url() -> str:
    url = _postgres_database_url()
    if url is not None:
        return url
    if os.getenv("CI"):
        pytest.fail(
            "pg_stress testleri CI'da gerçek bir PostgreSQL DATABASE_URL'i gerektirir "
            "(.github/workflows/ci.yml pg-stress job'ının 'services: postgres' bloğuna "
            "ve DATABASE_URL env'ine bakın)."
        )
    pytest.skip(
        "DATABASE_URL PostgreSQL'i işaret etmiyor; pg_stress testleri yalnızca gerçek "
        "bir PostgreSQL örneğine karşı (örn. `docker run -p 5432:5432 postgres:16`) "
        "çalıştırılabilir."
    )
    raise AssertionError("unreachable")  # pragma: no cover - pytest.skip/fail never returns


@pytest.fixture
def pg_stress_config() -> SimpleNamespace:
    """Havuzu kasıtlı olarak küçük tutan, gerçek Postgres'e işaret eden test cfg'si.

    ``DB_DEGRADED_MODE_ON_POSTGRES_FAILURE=False``: bu testlerin amacı gerçek bir
    PostgreSQL havuzunu sınamak; bağlantı kurulamazsa sessizce SQLite'a düşüp
    yeşil geçmek yerine testin açıkça patlamasını istiyoruz.
    """
    return SimpleNamespace(
        DATABASE_URL=_require_postgres_url(),
        BASE_DIR=".",
        DB_POOL_SIZE=3,
        DB_POOL_MIN_SIZE=1,
        DB_DEGRADED_MODE_ON_POSTGRES_FAILURE=False,
    )


async def _open_db(cfg: SimpleNamespace) -> Database:
    db = Database(cfg)
    await db.connect()
    assert db.degraded_mode is False, (
        f"PostgreSQL havuzu kurulamadı, degraded mode'a düşüldü: {db.degraded_reason}"
    )
    assert db._pg_pool is not None
    return db


async def test_pool_serves_concurrency_beyond_configured_pool_size(pg_stress_config) -> None:
    """``pool_size``'dan kat kat fazla eşzamanlı istemci, hatasız/deadlock'suz tamamlanmalı."""
    db = await _open_db(pg_stress_config)
    try:
        concurrency = db.pool_size * 5

        async def _round_trip(i: int) -> int:
            async with db._pg_pool.acquire() as conn:
                return await conn.fetchval("SELECT $1::int", i)

        results = await asyncio.wait_for(
            asyncio.gather(*(_round_trip(i) for i in range(concurrency))),
            timeout=30,
        )
        assert results == list(range(concurrency))
    finally:
        await db.close()


async def test_pool_recovers_after_repeated_exhaustion_bursts(pg_stress_config) -> None:
    """Havuzu art arda birden çok kez doyurmak sonraki turların bağlantı almasını engellememeli."""
    db = await _open_db(pg_stress_config)
    try:

        async def _hold_briefly() -> None:
            async with db._pg_pool.acquire() as conn:
                await conn.execute("SELECT pg_sleep(0.05)")

        for _ in range(3):
            await asyncio.wait_for(
                asyncio.gather(*(_hold_briefly() for _ in range(db.pool_size * 2))),
                timeout=30,
            )

        async with db._pg_pool.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1
    finally:
        await db.close()


async def test_concurrent_writers_do_not_lose_or_duplicate_rows(pg_stress_config) -> None:
    """Eşzamanlı INSERT'ler yarış koşulundan bağımsız olarak beklenen satır sayısını üretmeli."""
    db = await _open_db(pg_stress_config)
    table = "pg_stress_scratch"
    try:
        async with db._pg_pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
            await conn.execute(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, worker INT NOT NULL)")

        writers = db.pool_size * 4

        async def _insert(i: int) -> None:
            async with db._pg_pool.acquire() as conn:
                await conn.execute(f"INSERT INTO {table} (worker) VALUES ($1)", i)

        await asyncio.wait_for(
            asyncio.gather(*(_insert(i) for i in range(writers))),
            timeout=30,
        )

        async with db._pg_pool.acquire() as conn:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            workers = {row["worker"] for row in await conn.fetch(f"SELECT worker FROM {table}")}
        assert count == writers
        assert workers == set(range(writers))
    finally:
        async with db._pg_pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await db.close()
