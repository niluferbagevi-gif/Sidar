"""SQLite -> PostgreSQL veri taşıma scripti.

Kullanım örneği:
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite-path data/sidar.db \
        --postgres-dsn postgresql://user:pass@localhost:5432/sidar
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

TABLES_IN_ORDER = [
    "users",
    "auth_tokens",
    "user_quotas",
    "provider_usage_daily",
    "sessions",
    "messages",
    "schema_versions",
]
TABLES_ALLOWLIST = frozenset(TABLES_IN_ORDER)


def _safe_table_name(table: str) -> str:
    if table not in TABLES_ALLOWLIST:
        raise ValueError(f"Geçersiz tablo adı: {table}")
    return table


def _load_rows(sqlite_path: Path, table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    table = _safe_table_name(table)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {table}"  # nosec B608 - tablo adı kontrollü TABLES listesinden gelir.
        ).fetchall()
        if not rows:
            cols = [
                r[1]
                for r in conn.execute(
                    f"PRAGMA table_info({table})"  # nosec B608 - tablo adı kontrollü TABLES listesinden gelir.
                ).fetchall()
            ]
            return cols, []
        cols = list(rows[0].keys())
        return cols, [tuple(row[col] for col in cols) for row in rows]
    finally:
        conn.close()


async def _copy_table(conn: Any, sqlite_path: Path, table: str, dry_run: bool) -> int:
    table = _safe_table_name(table)
    columns, rows = _load_rows(sqlite_path, table)
    if not columns:
        return 0

    placeholders = ", ".join(f"${idx}" for idx in range(1, len(columns) + 1))
    col_list = ", ".join(columns)
    query = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"  # nosec B608

    if dry_run:
        return len(rows)

    async with conn.transaction():
        await conn.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")  # nosec B608
        for row in rows:
            await conn.execute(query, *row)
    return len(rows)


async def migrate(sqlite_path: Path, postgres_dsn: str, dry_run: bool) -> None:
    try:
        import asyncpg
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Bu script için 'asyncpg' bağımlılığı gereklidir.") from exc

    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite dosyası bulunamadı: {sqlite_path}")

    conn = await asyncpg.connect(dsn=postgres_dsn)
    try:
        for table in TABLES_IN_ORDER:
            count = await _copy_table(conn, sqlite_path, table, dry_run=dry_run)
            mode = "DRY-RUN" if dry_run else "MIGRATED"
            print(f"[{mode}] {table}: {count} row")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite verilerini PostgreSQL'e taşır.")
    parser.add_argument("--sqlite-path", required=True, help="Kaynak sqlite db dosya yolu")
    parser.add_argument("--postgres-dsn", required=True, help="Hedef PostgreSQL DSN")
    parser.add_argument(
        "--dry-run", action="store_true", help="Yalnızca okunacak satır sayılarını raporla"
    )
    args = parser.parse_args()

    asyncio.run(migrate(Path(args.sqlite_path), args.postgres_dsn, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
