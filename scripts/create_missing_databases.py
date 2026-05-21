from __future__ import annotations

import os
from pathlib import Path

import psycopg2


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def main() -> int:
    env_values = _read_env_file(Path(".env"))
    user = os.getenv("POSTGRES_USER") or env_values.get("POSTGRES_USER") or "sidar"
    password = os.getenv("POSTGRES_PASSWORD") or env_values.get("POSTGRES_PASSWORD") or ""
    host = os.getenv("POSTGRES_HOST") or env_values.get("POSTGRES_HOST") or "127.0.0.1"
    port = int(os.getenv("POSTGRES_PORT") or env_values.get("POSTGRES_PORT") or "5432")
    primary_db = os.getenv("POSTGRES_DB") or env_values.get("POSTGRES_DB") or "sidar"

    db_names = [primary_db, "sidar", "sidar_development", "sidar_test"]
    db_names = list(dict.fromkeys([name for name in db_names if name]))

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for db_name in db_names:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{user}"')
                    print(f"created: {db_name}")
                else:
                    print(f"exists: {db_name}")

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
