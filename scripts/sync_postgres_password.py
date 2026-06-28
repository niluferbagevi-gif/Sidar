"""Synchronize the live PostgreSQL role password with Sidar's effective env chain.

This repair targets the case where dotenv parity is correct, but an existing
Docker PostgreSQL volume still contains an older password for ``POSTGRES_USER``.
It reads the effective Sidar dotenv chain, never prints the password, and sends
``ALTER USER ... WITH PASSWORD ...`` through ``docker exec`` stdin instead of
embedding secrets in the command line.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_database_passwords import (  # noqa: E402
    DEFAULT_ENV_FILE,
    _effective_env_from_specs,
    discover_env_chain,
)

DEFAULT_ALLOWED_ENVS = {"development", "dev", "local", "test", "testing"}
DEFAULT_POSTGRES_CONTAINER = "sidar_postgres"


class PostgresSyncError(RuntimeError):
    """Raised when live PostgreSQL password synchronization cannot continue."""


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


def _effective_env(env_file: Path = DEFAULT_ENV_FILE) -> tuple[dict[str, str], list[str]]:
    specs = discover_env_chain(env_file)
    if not specs or not specs[0].path.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {env_file}")
    return _effective_env_from_specs(specs), [str(spec.path) for spec in specs]


def _check_environment_allowed(*, env: dict[str, str], allow_non_dev: bool) -> None:
    sidar_env = env.get("SIDAR_ENV", "").strip().lower()
    if allow_non_dev or sidar_env in DEFAULT_ALLOWED_ENVS:
        return
    if not sidar_env:
        raise PostgresSyncError(
            "SIDAR_ENV must be set to a local/development profile before mutating "
            "PostgreSQL credentials."
        )
    raise PostgresSyncError(
        "Refusing to mutate PostgreSQL credentials outside a local/development profile. "
        "Set SIDAR_ENV=development or pass --allow-non-dev intentionally."
    )


def _postgres_container_name(env: dict[str, str], explicit_container: str | None = None) -> str:
    return (
        explicit_container
        or env.get("SIDAR_POSTGRES_CONTAINER", "").strip()
        or env.get("POSTGRES_CONTAINER_NAME", "").strip()
        or DEFAULT_POSTGRES_CONTAINER
    )


def _pre_harden_password_file(env: dict[str, str]) -> Path | None:
    password_file = env.get("PRE_HARDEN_DB_PASSWORD_FILE", "").strip()
    if not password_file:
        return None
    return Path(password_file).expanduser()


def _read_pre_harden_password(env: dict[str, str]) -> str:
    direct_password = env.get("PRE_HARDEN_DB_PASSWORD", "").strip()
    if direct_password:
        return direct_password

    password_file = _pre_harden_password_file(env)
    if password_file is None or not password_file.is_file():
        return ""
    return password_file.read_text(encoding="utf-8").strip()


def _remove_pre_harden_password_file(env: dict[str, str]) -> None:
    password_file = _pre_harden_password_file(env)
    if password_file is None:
        return
    try:
        password_file.unlink(missing_ok=True)
    except OSError:
        return


def _sync_timeout_seconds() -> int:
    raw_timeout = os.getenv("SIDAR_PG_SYNC_TIMEOUT", "90").strip()
    try:
        timeout = int(raw_timeout)
    except ValueError:
        return 90
    return max(timeout, 1)


def _docker_exec_command(
    env: dict[str, str], *, postgres_container: str | None = None, auth_password: str = ""
) -> list[str]:
    docker = shutil.which("docker")
    if not docker:
        raise PostgresSyncError("docker executable not found on PATH")
    postgres_user = env.get("POSTGRES_USER", "sidar").strip() or "sidar"
    admin_user = env.get("POSTGRES_ADMIN_USER", "").strip() or postgres_user
    admin_db = (
        env.get("POSTGRES_ADMIN_DB", "").strip() or env.get("POSTGRES_DB", "").strip() or "postgres"
    )
    container = _postgres_container_name(env, explicit_container=postgres_container)
    cmd = [docker, "exec", "-i"]
    if auth_password:
        cmd += ["-e", f"PGPASSWORD={auth_password}"]
    cmd += [
        container,
        "psql",
        "-U",
        admin_user,
        "-d",
        admin_db,
        "-v",
        "ON_ERROR_STOP=1",
        "--quiet",
    ]
    return cmd


def _auth_password_candidates(env: dict[str, str], postgres_password: str) -> list[str]:
    candidates = [_read_pre_harden_password(env), postgres_password]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _redact_passwords(output: str, passwords: list[str]) -> str:
    redacted = output
    for password in passwords:
        if password:
            redacted = redacted.replace(password, "***")
    return redacted


def sync_postgres_password_with_docker_exec(
    *,
    allow_non_dev: bool = False,
    env_file: Path = DEFAULT_ENV_FILE,
    postgres_container: str | None = None,
) -> dict[str, Any]:
    """Run ALTER USER inside the running PostgreSQL container via docker exec."""
    effective_env, checked_files = _effective_env(env_file)
    _check_environment_allowed(env=effective_env, allow_non_dev=allow_non_dev)
    postgres_user = effective_env.get("POSTGRES_USER", "sidar").strip() or "sidar"
    postgres_password = effective_env.get("POSTGRES_PASSWORD", "").strip()
    if not postgres_password:
        raise PostgresSyncError("POSTGRES_PASSWORD is not set in the effective env chain")

    sql = _build_alter_user_sql(
        postgres_user=postgres_user,
        postgres_password=postgres_password,
    )
    container = _postgres_container_name(effective_env, explicit_container=postgres_container)
    auth_passwords = _auth_password_candidates(effective_env, postgres_password)
    completed: subprocess.CompletedProcess[str] | None = None
    cmd: list[str] = []
    for auth_password in auth_passwords:
        cmd = _docker_exec_command(
            effective_env,
            postgres_container=postgres_container,
            auth_password=auth_password,
        )
        completed = subprocess.run(  # Fixed command list; SQL is passed via stdin.  # nosec B603
            cmd,
            cwd=PROJECT_ROOT,
            input=sql,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=_sync_timeout_seconds(),
        )
        if completed.returncode == 0:
            break

    if completed is None:
        raise PostgresSyncError("No PostgreSQL authentication password candidate is available")

    output = _redact_passwords(completed.stdout or "", auth_passwords)
    if completed.returncode != 0:
        raise PostgresSyncError(
            "docker exec PostgreSQL password sync failed "
            f"with exit code {completed.returncode}: {output.strip()}"
        )
    _remove_pre_harden_password_file(effective_env)
    return _redacted_summary(
        changed=True,
        method="docker-exec",
        container=container,
        service="postgres",
        postgres_user=postgres_user,
        postgres_password_set=True,
        checked_files=checked_files,
        command="docker exec -i -e PGPASSWORD=*** <postgres_container> psql -U <admin> -d <admin_db>",
    )


def sync_postgres_password_with_docker_compose(
    *,
    allow_non_dev: bool = False,
    env_file: Path = DEFAULT_ENV_FILE,
    postgres_container: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper; implementation now uses docker exec directly."""
    return sync_postgres_password_with_docker_exec(
        allow_non_dev=allow_non_dev,
        env_file=env_file,
        postgres_container=postgres_container,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mevcut PostgreSQL rol parolasını etkili POSTGRES_PASSWORD ile eşitle "
            "(Docker volume eski parola ile başlatıldıysa kullanılır)"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--method",
        choices=("docker-exec", "docker-compose"),
        default="docker-exec",
        help=(
            "Parola eşitleme yöntemi. docker-compose geriye dönük uyumluluk alias'ıdır; "
            "uygulama yine docker exec kullanır."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Etkili dotenv zincirini başlatan temel env dosyası",
    )
    parser.add_argument(
        "--postgres-container",
        default="",
        help="docker exec hedef container adı/ID'si; boşsa sidar_postgres kullanılır",
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
        if args.method in {"docker-exec", "docker-compose"}:
            summary = sync_postgres_password_with_docker_exec(
                allow_non_dev=args.allow_non_dev,
                env_file=Path(args.env_file),
                postgres_container=args.postgres_container or None,
            )
        else:  # pragma: no cover - argparse choices prevent this path.
            raise PostgresSyncError(f"Unsupported method: {args.method}")
    except Exception as exc:
        print(f"❌ PostgreSQL kullanıcı parolası eşitlenemedi: {exc}", file=sys.stderr)
        return 1

    print("✅ PostgreSQL kullanıcı parolası POSTGRES_PASSWORD ile eşitlendi.", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
