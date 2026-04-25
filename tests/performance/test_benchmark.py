"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.db import Database
from scripts.coverage_hotspots import FileCoverage, format_table

pytestmark = pytest.mark.benchmark
pytest.importorskip("pytest_benchmark")


@pytest.fixture(scope="module")
def large_dataset_rows() -> list[FileCoverage]:
    return [
        FileCoverage(
            path=f"module_{index // 100}/file_{index:05d}.py",
            covered=(index % 120) + 1,
            missed=index % 7,
        )
        for index in range(10_000)
    ]


def test_format_table_handles_large_dataset_quickly(benchmark, large_dataset_rows) -> None:
    output = benchmark(format_table, large_dataset_rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "module_0/file_00000.py" in output
    assert "module_99/file_09999.py" in output


def _postgresql_benchmark_url() -> str | None:
    """Benchmark için kullanılacak PostgreSQL URL'sini ortamdan bulur."""
    candidates = (
        "SIDAR_BENCHMARK_POSTGRES_URL",
        "TEST_DATABASE_URL",
        "DATABASE_URL",
    )
    for env_name in candidates:
        raw = os.getenv(env_name, "").strip()
        lowered = raw.lower()
        if lowered.startswith("postgresql://") or lowered.startswith("postgresql+asyncpg://"):
            return raw
    return None


def _make_cfg(base_dir: Path, database_url: str) -> SimpleNamespace:
    worker_count = _pytest_worker_count()
    pool_budget = _benchmark_pool_budget()
    per_worker_pool_size = max(1, pool_budget // max(1, worker_count))
    return SimpleNamespace(
        DATABASE_URL=database_url,
        BASE_DIR=str(base_dir),
        DB_POOL_SIZE=per_worker_pool_size,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )


def _pytest_worker_count() -> int:
    raw = os.getenv("PYTEST_XDIST_WORKER_COUNT", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _benchmark_pool_budget() -> int:
    raw = os.getenv("SIDAR_BENCHMARK_POOL_BUDGET", "60").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 60


async def _initialize_schema_safely(db: Database) -> None:
    """PostgreSQL benchmark şemasını process'ler arası advisory lock ile kurar."""
    if getattr(db, "_backend", "") != "postgresql":
        await db.init_schema()
        return

    pool = getattr(db, "_pg_pool", None)
    if pool is None:
        raise RuntimeError("PostgreSQL pool başlatılmadan şema kurulamaz.")

    # Sabit lock-id ile xdist worker'ları arasında DDL yarışını engeller.
    lock_id = 4_226_031
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", lock_id)
        try:
            await db.init_schema()
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)


def _benchmark_db_variants() -> list[object]:
    variants: list[object] = [
        pytest.param("sqlite", id="sqlite"),
    ]
    if _postgresql_benchmark_url():
        variants.append(pytest.param("postgresql", id="postgresql"))
    return variants


@pytest.fixture(params=_benchmark_db_variants())
def benchmark_multi_user_db(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> tuple[Database, asyncio.AbstractEventLoop]:
    backend = request.param
    if backend == "postgresql":
        pg_url = _postgresql_benchmark_url()
        if not pg_url:
            pytest.skip("PostgreSQL benchmark URL bulunamadı.")
        database_url = pg_url
    else:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'benchmark_multi_user_scale.db'}"

    cfg = _make_cfg(tmp_path, database_url)
    db = Database(cfg)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(db.connect())
        loop.run_until_complete(_initialize_schema_safely(db))
    except Exception as exc:
        loop.close()
        if backend == "postgresql":
            pytest.skip(f"PostgreSQL benchmark backend kullanılamadı: {exc}")
        raise
    try:
        yield db, loop
    finally:
        loop.run_until_complete(db.close())
        loop.close()


def test_multi_user_session_message_workload_scales_with_concurrency(
    benchmark,
    benchmark_multi_user_db: tuple[Database, asyncio.AbstractEventLoop],
) -> None:
    """Çoklu kullanıcı + oturum + mesaj yazım iş yükünü benchmark eder ve bütünlüğü doğrular."""
    users = 20
    messages_per_session = 8
    db, loop = benchmark_multi_user_db

    async def _workload(run_id: str) -> int:
        created_users = await asyncio.gather(
            # Benchmark odak noktası oturum+mesaj akışı olduğu için burada
            # pahalı PBKDF2 parola hash maliyetini devre dışı bırakıyoruz.
            *[db.create_user(f"user_{run_id}_{idx}", tenant_id=f"tenant-{idx % 4}") for idx in range(users)]
        )
        sessions = await asyncio.gather(
            *[db.create_session(user.id, f"session-{run_id}-{i}") for i, user in enumerate(created_users)]
        )

        inserted = await db.add_messages_bulk(
            [
                {
                    "session_id": session.id,
                    "role": "user",
                    "content": f"hello-{j}",
                    "tokens_used": j,
                }
                for session in sessions
                for j in range(messages_per_session)
            ]
        )
        assert inserted == users * messages_per_session

        grouped_messages = await db.get_messages_for_sessions([session.id for session in sessions])
        per_session_messages = [grouped_messages.get(session.id, []) for session in sessions]
        assert all(len(items) == messages_per_session for items in per_session_messages)
        assert all([m.tokens_used for m in items] == list(range(messages_per_session)) for items in per_session_messages)
        return sum(len(items) for items in per_session_messages)

    def _run_once() -> int:
        return loop.run_until_complete(_workload(uuid4().hex))

    total_messages = benchmark.pedantic(
        _run_once,
        warmup_rounds=3,
        rounds=12,
        iterations=1,
    )
    assert total_messages == users * messages_per_session


def test_user_registration_password_hash_cpu_cost(
    benchmark,
    benchmark_multi_user_db: tuple[Database, asyncio.AbstractEventLoop],
) -> None:
    """PBKDF2 maliyetini içeren kullanıcı kayıt akışını benchmark eder."""
    db, loop = benchmark_multi_user_db

    def _run_once() -> str:
        username = f"bench-reg-{uuid4().hex}"
        user = loop.run_until_complete(
            db.register_user(
                username=username,
                password="benchmark-password-123!",
                tenant_id="benchmark-tenant",
            )
        )
        return user.id

    user_id = benchmark.pedantic(
        _run_once,
        warmup_rounds=1,
        rounds=5,
        iterations=1,
    )
    assert isinstance(user_id, str) and bool(user_id.strip())


def test_user_authentication_password_verify_cpu_cost(
    benchmark,
    benchmark_multi_user_db: tuple[Database, asyncio.AbstractEventLoop],
) -> None:
    """PBKDF2 doğrulama maliyetini ölçmek için login akışını benchmark eder."""
    db, loop = benchmark_multi_user_db
    username = f"bench-auth-{uuid4().hex}"
    password = "benchmark-password-123!"

    created = loop.run_until_complete(
        db.register_user(
            username=username,
            password=password,
            tenant_id="benchmark-tenant",
        )
    )
    assert created.id

    def _run_once() -> str | None:
        user = loop.run_until_complete(db.authenticate_user(username, password))
        return None if user is None else user.id

    authenticated_user_id = benchmark.pedantic(
        _run_once,
        warmup_rounds=1,
        rounds=5,
        iterations=1,
    )
    assert authenticated_user_id == created.id
