"""Synchronize the stored PostgreSQL role password with Sidar's POSTGRES_PASSWORD.

This repair targets the case where dotenv parity is correct, but an existing
local Docker PostgreSQL volume still contains an older password for POSTGRES_USER.
It never prints the password and sends the ALTER USER statement through stdin
instead of embedding secrets in the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWED_ENVS = {"", "development", "dev", "local", "test", "testing"}


def _load_dotenv_defaults(path: Path | None = None) -> None:
    """Populate missing process env values from Sidar's local dotenv file.

    The installer invokes this module as a subprocess after rewriting ``.env``.
    Docker Compose reads that file automatically, but Python subprocesses do not;
    loading only missing keys keeps explicit operator overrides authoritative while
    allowing the rotation command to use the freshly generated POSTGRES_PASSWORD.
    """
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _redacted_summary(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_alter_user_sql(*, postgres_user: str, postgres_password: str) -> str:
    return f"""
\\set ON_ERROR_STOP on
DO $$
DECLARE
    target_user text := {_sql_literal(postgres_user)};
    target_password text := {_sql_literal(postgres_password)};
BEGIN
    IF target_user = '' THEN
        RAISE EXCEPTION 'POSTGRES_USER is empty';
    END IF;
    EXECUTE format('ALTER USER %I WITH PASSWORD %L', target_user, target_password);
END
$$;
""".lstrip()


def _check_environment_allowed(*, allow_non_dev: bool) -> None:
    sidar_env = os.getenv("SIDAR_ENV", "").strip().lower()
    if allow_non_dev or sidar_env in DEFAULT_ALLOWED_ENVS:
        return
    raise RuntimeError(
        "Refusing to mutate PostgreSQL credentials outside a local/development profile. "
        "Set SIDAR_ENV=development or pass --allow-non-dev intentionally."
    )


def _docker_compose_command() -> list[str]:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("docker executable not found on PATH")
    postgres_user = os.getenv("POSTGRES_USER", "sidar").strip() or "sidar"
    return [
        docker,
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        os.getenv("POSTGRES_ADMIN_USER", postgres_user).strip() or postgres_user,
        "-d",
        os.getenv("POSTGRES_ADMIN_DB", os.getenv("POSTGRES_DB", "sidar")).strip() or "sidar",
        "-v",
        "ON_ERROR_STOP=1",
        "--quiet",
    ]


def sync_postgres_password_with_docker_compose(*, allow_non_dev: bool = False) -> dict[str, Any]:
    """Run ALTER USER inside the local Docker Compose PostgreSQL service."""
    _load_dotenv_defaults()
    _check_environment_allowed(allow_non_dev=allow_non_dev)
    postgres_user = os.getenv("POSTGRES_USER", "sidar").strip() or "sidar"
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    if not postgres_password:
        raise RuntimeError("POSTGRES_PASSWORD is not set")

    cmd = _docker_compose_command()
    sql = _build_alter_user_sql(
        postgres_user=postgres_user,
        postgres_password=postgres_password,
    )
    completed = subprocess.run(  # nosec B603 - fixed command list, SQL passed via stdin.
        cmd,
        cwd=PROJECT_ROOT,
        input=sql,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    output = (completed.stdout or "").replace(postgres_password, "***")
    if completed.returncode != 0:
        raise RuntimeError(
            "docker compose PostgreSQL password sync failed "
            f"with exit code {completed.returncode}: {output.strip()}"
        )
    return _redacted_summary(
        changed=True,
        method="docker-compose",
        service="postgres",
        postgres_user=postgres_user,
        postgres_password_set=True,
        command="docker compose exec -T postgres psql -U <admin> -d <admin_db>",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mevcut yerel PostgreSQL rol parolasını POSTGRES_PASSWORD ile eşitle "
            "(Docker volume eski parola ile başlatıldıysa kullanılır)"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--method",
        choices=("docker-compose",),
        default="docker-compose",
        help="Parola eşitleme yöntemi",
    )
    parser.add_argument(
        "--allow-non-dev",
        action="store_true",
        help="SIDAR_ENV production gibi yerel olmayan profillerde bilinçli çalıştır",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.method == "docker-compose":
            summary = sync_postgres_password_with_docker_compose(
                allow_non_dev=args.allow_non_dev
            )
        else:  # pragma: no cover - argparse choices prevent this path.
            raise RuntimeError(f"Unsupported method: {args.method}")
    except Exception as exc:
        print(f"❌ PostgreSQL kullanıcı parolası eşitlenemedi: {exc}", file=sys.stderr)
        return 1

    print("✅ PostgreSQL kullanıcı parolası POSTGRES_PASSWORD ile eşitlendi.", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
