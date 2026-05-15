"""Synchronize an existing development PostgreSQL role password with `.env`.

This helper is intentionally opt-in: by default it prints the sanitized plan and
only mutates the Docker Compose PostgreSQL service when `--apply` is supplied.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess  # nosec B404 - fixed argv, no shell=True
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values.setdefault(key, value)
    return values


def _env(name: str, file_values: dict[str, str], default: str = "") -> str:
    return os.getenv(name, file_values.get(name, default)).strip()


def _quote_sql_identifier(value: str) -> str:
    if not value:
        raise ValueError("SQL identifier cannot be empty")
    return '"' + value.replace('"', '""') + '"'


def _quote_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _redact(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def build_alter_user_sql(username: str, password: str) -> str:
    """Build a safely quoted ALTER ROLE statement for psql."""
    return f"ALTER USER {_quote_sql_identifier(username)} WITH PASSWORD {_quote_sql_literal(password)};"


def build_docker_compose_command(
    *,
    service: str,
    admin_user: str,
    admin_database: str,
    sql: str,
) -> list[str]:
    return [
        "docker",
        "compose",
        "exec",
        "-T",
        service,
        "psql",
        "-U",
        admin_user,
        "-d",
        admin_database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]


def _validate_inputs(username: str, password: str, service: str) -> list[str]:
    errors: list[str] = []
    if not username:
        errors.append("POSTGRES_USER is empty")
    if not password:
        errors.append("POSTGRES_PASSWORD is empty")
    if password in {"postgres", "sidar", "password", "changeme"} or password.startswith(
        "replace-with-"
    ):
        errors.append("POSTGRES_PASSWORD still looks like a default/placeholder value")
    if not service:
        errors.append("PostgreSQL compose service name is empty")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync the existing Docker Compose PostgreSQL user password from .env."
    )
    parser.add_argument("--env-file", default=str(BASE_DIR / ".env"), help="Path to the .env file")
    parser.add_argument(
        "--service",
        default="",
        help="Docker Compose PostgreSQL service name (default: POSTGRES_SERVICE or postgres)",
    )
    parser.add_argument(
        "--admin-user",
        default="",
        help="Admin role used by psql (default: POSTGRES_ADMIN_USER or postgres)",
    )
    parser.add_argument(
        "--admin-database",
        default="postgres",
        help="Database used for the ALTER USER command (default: postgres)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run docker compose exec; without this flag only a redacted dry-run is printed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the redacted plan without mutating PostgreSQL (default behavior).",
    )
    args = parser.parse_args(argv)

    env_path = Path(args.env_file).expanduser().resolve()
    file_values = _parse_env_file(env_path)
    username = _env("POSTGRES_USER", file_values, "sidar")
    password = _env("POSTGRES_PASSWORD", file_values)
    service = args.service.strip() or _env("POSTGRES_SERVICE", file_values, "postgres")
    admin_user = args.admin_user.strip() or _env("POSTGRES_ADMIN_USER", file_values, "postgres")
    admin_database = args.admin_database.strip() or "postgres"

    errors = _validate_inputs(username, password, service)
    if errors:
        for error in errors:
            print(f"❌ {error}", file=sys.stderr)
        return 2

    sql = build_alter_user_sql(username, password)
    command = build_docker_compose_command(
        service=service,
        admin_user=admin_user,
        admin_database=admin_database,
        sql=sql,
    )
    redacted_sql = build_alter_user_sql(username, "***")
    redacted_command = command.copy()
    redacted_command[-1] = redacted_sql

    print("Sidar PostgreSQL parola eşitleme planı")
    print(f"  .env          : {env_path}")
    print(f"  service       : {service}")
    print(f"  target user   : {username}")
    print(f"  target passwd : {_redact(password)}")
    print("  command       : " + shlex.join(redacted_command))

    if not args.apply:
        print("Dry-run tamamlandı. Uygulamak için: uv run python -m scripts.sync_postgres_password --apply")
        return 0

    completed = subprocess.run(command, check=False)  # nosec B603 - fixed argv, operator initiated
    if completed.returncode == 0:
        print("✅ PostgreSQL kullanıcı parolası .env ile eşitlendi.")
    else:
        print("❌ PostgreSQL parola eşitleme başarısız oldu.", file=sys.stderr)
    return int(completed.returncode)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
