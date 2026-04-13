"""PostgreSQL asyncpg havuzu için hafif yük/stres testi.

Örnek:
  python scripts/load_test_db_pool.py \
    --database-url postgresql://sidar:sidar@localhost:5432/sidar \
    --concurrency 50 \
    --requests 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from statistics import mean

from config import Config
from core.db import Database


async def _run_once(db: Database, acquire_timeout_s: float) -> float | None:
    assert db._pg_pool is not None
    started = time.perf_counter()
    try:
        async with db._pg_pool.acquire(timeout=acquire_timeout_s) as conn:
            await conn.execute("SELECT 1")
    except Exception:
        return None
    return (time.perf_counter() - started) * 1000


async def run_load_test(
    database_url: str,
    concurrency: int,
    requests: int,
    warmup_requests: int,
    acquire_timeout_s: float,
) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_POOL_SIZE"] = str(max(1, min(concurrency, 100)))

    db = Database(Config())
    await db.connect()
    try:
        if db._backend != "postgresql":
            raise RuntimeError("Bu test yalnızca PostgreSQL backend ile çalışır.")

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _worker() -> float | None:
            async with sem:
                return await _run_once(db, acquire_timeout_s=acquire_timeout_s)

        warmup_count = max(0, warmup_requests)
        if warmup_count > 0:
            await asyncio.gather(*(_worker() for _ in range(warmup_count)))

        print(
            "POOL_LOAD_TEST_START "
            f"backend={db._backend} pool_size={db.pool_size} "
            f"concurrency={concurrency} requests={requests} "
            f"warmup_requests={warmup_count} acquire_timeout_s={acquire_timeout_s:.2f}"
        )

        started = time.perf_counter()
        results = await asyncio.gather(*(_worker() for _ in range(max(1, requests))))
        elapsed = time.perf_counter() - started

        latencies = sorted(lat for lat in results if lat is not None)
        success_count = len(latencies)
        failed_count = len(results) - success_count
        if success_count == 0:
            print(
                "POOL_LOAD_TEST_FAIL "
                f"backend={db._backend} pool_size={db.pool_size} "
                f"concurrency={concurrency} requests={requests} "
                f"success=0 failed={failed_count} elapsed_s={elapsed:.2f}"
            )
            return

        p50 = latencies[success_count // 2]
        p95 = latencies[max(0, int(success_count * 0.95) - 1)]
        avg = mean(latencies)
        rps = success_count / elapsed if elapsed > 0 else 0.0

        print(
            "POOL_LOAD_TEST_OK "
            f"backend={db._backend} pool_size={db.pool_size} "
            f"concurrency={concurrency} requests={requests} "
            f"success={success_count} failed={failed_count} "
            f"elapsed_s={elapsed:.2f} rps={rps:.2f} "
            f"avg_ms={avg:.2f} p50_ms={p50:.2f} p95_ms={p95:.2f}"
        )
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="asyncpg pool smoke/load test")
    parser.add_argument("--database-url", required=True, help="PostgreSQL DSN")
    parser.add_argument("--concurrency", type=int, default=50, help="Eşzamanlı worker sayısı")
    parser.add_argument("--requests", type=int, default=300, help="Toplam istek sayısı")
    parser.add_argument(
        "--warmup-requests",
        type=int,
        default=10,
        help="Ölçüm öncesi ısınma amaçlı istek sayısı (ölçümlere dahil edilmez)",
    )
    parser.add_argument(
        "--acquire-timeout",
        type=float,
        default=5.0,
        help="Pool acquire timeout süresi (saniye)",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency en az 1 olmalıdır.")
    if args.requests < 1:
        raise SystemExit("--requests en az 1 olmalıdır.")
    if args.warmup_requests < 0:
        raise SystemExit("--warmup-requests negatif olamaz.")
    if args.acquire_timeout <= 0:
        raise SystemExit("--acquire-timeout 0'dan büyük olmalıdır.")

    asyncio.run(
        run_load_test(
            args.database_url,
            args.concurrency,
            args.requests,
            args.warmup_requests,
            args.acquire_timeout,
        )
    )


if __name__ == "__main__":
    main()