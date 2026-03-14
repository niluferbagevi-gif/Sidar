# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

"""PostgreSQL asyncpg havuzu için hafif yük/stres testi.

Örnek:
  python scripts/load_test_db_pool.py \
    --database-url postgresql://postgres:postgres@localhost:5432/sidar \
    --concurrency 50 \
    --requests 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

from config import Config
from core.db import Database


async def _run_once(db: Database) -> float:
    assert db._pg_pool is not None
    started = time.perf_counter()
    async with db._pg_pool.acquire() as conn:
        await conn.execute("SELECT 1")
    return (time.perf_counter() - started) * 1000


async def run_load_test(database_url: str, concurrency: int, requests: int) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_POOL_SIZE"] = str(max(1, min(concurrency, 100)))

    db = Database(Config())
    await db.connect()
    try:
        if db._backend != "postgresql":
            raise RuntimeError("Bu test yalnızca PostgreSQL backend ile çalışır.")

        sem = asyncio.Semaphore(max(1, concurrency))
        latencies: list[float] = []

        async def _worker() -> None:
            async with sem:
                latencies.append(await _run_once(db))

        started = time.perf_counter()
        await asyncio.gather(*(_worker() for _ in range(max(1, requests))))
        elapsed = time.perf_counter() - started

        p50 = sorted(latencies)[len(latencies) // 2]
        p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]

        print(
            "POOL_LOAD_TEST_OK "
            f"backend={db._backend} pool_size={db.pool_size} "
            f"concurrency={concurrency} requests={requests} "
            f"elapsed_s={elapsed:.2f} p50_ms={p50:.2f} p95_ms={p95:.2f}"
        )
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="asyncpg pool smoke/load test")
    parser.add_argument("--database-url", required=True, help="PostgreSQL DSN")
    parser.add_argument("--concurrency", type=int, default=50, help="Eşzamanlı worker sayısı")
    parser.add_argument("--requests", type=int, default=300, help="Toplam istek sayısı")
    args = parser.parse_args()

    asyncio.run(run_load_test(args.database_url, args.concurrency, args.requests))


if __name__ == "__main__":
    main()