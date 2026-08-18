"""Synchronize the Redis URL password across Sidar dotenv files.

Mirrors ``scripts/sync_database_passwords.py``'s role for PostgreSQL, but for
``REDIS_PASSWORD``: keeps any explicit ``SIDAR_REDIS_URL``/``REDIS_URL``
credential aligned with the effective ``REDIS_PASSWORD`` without printing
secret values. It is intentionally idempotent, like the PostgreSQL sync tool,
so it is safe to run repeatedly (e.g. from Doctor auto-fix or a rotation
flow) whenever password drift is detected.

Dotenv-chain discovery (``.env`` -> ``.env.advanced`` -> ``.env.<SIDAR_ENV>``
-> ``DOTENV_FILE`` -> ``SIDAR_KEYS_FILE``) is not PostgreSQL-specific, so this
module reuses ``scripts.sync_database_passwords.discover_env_chain`` rather
than re-implementing Sidar's dotenv precedence a second time.

Unlike the PostgreSQL tool, this module does not offer a
``--remove-explicit-urls`` mode: ``core.config_rate_limit.resolve_redis_url``
already auto-injects ``REDIS_PASSWORD`` into an *unauthenticated*
``localhost``/``127.0.0.1``/``::1`` URL at runtime (see that function's
docstring), but has no equivalent DSN-builder for non-local Redis hosts the
way ``config.py`` builds ``DATABASE_URL`` from ``POSTGRES_*`` parts. Removing
an explicit non-local ``SIDAR_REDIS_URL`` here would silently drop the host,
so explicit URLs are only ever repaired in place, never removed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from scripts.sync_database_passwords import (
    DEFAULT_ENV_FILE,
    EnvFileSpec,
    _parse_env_text,
    _read_assignments,
    _replace_assignment_line,
    discover_env_chain,
)

REDIS_URL_KEYS = ("SIDAR_REDIS_URL", "REDIS_URL")
# Keys _effective_env_from_specs() below resolves while walking the dotenv
# chain. Deliberately NOT sync_database_passwords.ENV_CHAIN_KEYS: that tuple
# only tracks POSTGRES_PASSWORD/DATABASE_URL keys, so reusing it here would
# silently resolve an empty REDIS_PASSWORD/SIDAR_REDIS_URL from every file in
# the chain (caught live while writing this module's tests).
ENV_CHAIN_KEYS = (*REDIS_URL_KEYS, "REDIS_PASSWORD", "SIDAR_ENV", "DOTENV_FILE", "SIDAR_KEYS_FILE")


def _apply_assignments_to_env(
    env: dict[str, str],
    assignments: dict[str, Any],
    *,
    override: bool,
) -> None:
    for key in ENV_CHAIN_KEYS:
        assignment = assignments.get(key)
        if assignment is None:
            continue
        if override or key not in env:
            env[key] = assignment.value


def _effective_env_from_specs(specs: list[EnvFileSpec]) -> dict[str, str]:
    """Resolve the effective dotenv chain with Sidar's override semantics."""
    effective_env = dict(os.environ)
    for spec in specs:
        _apply_assignments_to_env(
            effective_env, _read_assignments(spec.path), override=spec.override
        )
    return effective_env


def _redis_url_with_password(redis_url: str, redis_password: str) -> str | None:
    """Return ``redis_url`` with its credentials replaced by ``redis_password``.

    Returns ``None`` when ``redis_url`` is not a ``redis``/``rediss`` URL Sidar
    can safely rewrite. Unlike PostgreSQL URLs, a username is optional
    (``redis://:password@host:port/db`` is the common form Sidar itself
    generates), so an absent username is preserved rather than rejected.
    """
    parsed = urlsplit(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        return None
    if not parsed.hostname:
        return None

    username = quote(unquote(parsed.username), safe="") if parsed.username else ""
    encoded_password = quote(redis_password, safe="")
    host = parsed.hostname
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{username}:{encoded_password}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _sync_env_text_with_password(
    text: str,
    redis_password: str,
    *,
    sync_redis_password_assignment: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Return updated env text using an already-resolved effective password."""
    if not redis_password:
        raise ValueError("REDIS_PASSWORD is not set in the effective env chain")

    assignments = _parse_env_text(text)
    lines = text.splitlines()
    changed_keys: list[str] = []
    skipped: dict[str, str] = {}

    if sync_redis_password_assignment:
        password_assignment = assignments.get("REDIS_PASSWORD")
        if password_assignment is None:
            lines.append(f"REDIS_PASSWORD={redis_password}")
            changed_keys.append("REDIS_PASSWORD")
        elif password_assignment.value != redis_password:
            _replace_assignment_line(lines, password_assignment, redis_password)
            changed_keys.append("REDIS_PASSWORD")

    for key in REDIS_URL_KEYS:
        assignment = assignments.get(key)
        if assignment is None or not assignment.value:
            skipped[key] = "missing"
            continue
        updated = _redis_url_with_password(assignment.value, redis_password)
        if updated is None:
            skipped[key] = "not_a_redis_url"
            continue
        if updated != assignment.value:
            _replace_assignment_line(lines, assignment, updated)
            changed_keys.append(key)

    trailing_newline = "\n" if text.endswith("\n") or lines else ""
    updated_text = "\n".join(lines) + trailing_newline
    summary = {
        "changed": bool(changed_keys),
        "changed_keys": changed_keys,
        "skipped": skipped,
        "checked_keys": list(REDIS_URL_KEYS),
        "redis_password_set": True,
        "strategy": "sync_passwords",
    }
    return updated_text, summary


def sync_env_text(text: str) -> tuple[str, dict[str, Any]]:
    """Return updated env text plus a redacted summary for a single env file."""
    assignments = _parse_env_text(text)
    redis_password = assignments.get("REDIS_PASSWORD")
    if redis_password is None or not redis_password.value:
        raise ValueError("REDIS_PASSWORD is not set in the env file")
    return _sync_env_text_with_password(text, redis_password.value)


def sync_env_file(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Any]:
    if not env_file.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {env_file}")
    original = env_file.read_text(encoding="utf-8")
    updated, summary = sync_env_text(original)
    if updated != original:
        env_file.write_text(updated, encoding="utf-8")
    return {"env_file": str(env_file), **summary}


def _base_redis_password(base_env_file: Path) -> str:
    assignment = _read_assignments(base_env_file).get("REDIS_PASSWORD")
    return assignment.value if assignment is not None else ""


def _effective_redis_password(specs: list[EnvFileSpec]) -> str:
    return _effective_env_from_specs(specs).get("REDIS_PASSWORD", "")


def _effective_url_validation_warnings(effective_env: dict[str, str]) -> list[dict[str, str]]:
    """Validate effective URL passwords after syncing all files."""
    redis_password = effective_env.get("REDIS_PASSWORD", "")
    if not redis_password:
        return []

    ordered_keys = ("SIDAR_REDIS_URL", "REDIS_URL")
    candidates: list[tuple[str, str]] = []
    for key in ordered_keys:
        raw_url = effective_env.get(key, "").strip()
        if not raw_url:
            continue
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"redis", "rediss"}:
            continue
        candidates.append((key, unquote(parsed.password or "")))

    if not candidates:
        return []
    if candidates[0][0] == "SIDAR_REDIS_URL":
        candidates = [candidates[0]]

    warnings: list[dict[str, str]] = []
    for key, url_password in candidates:
        if url_password != redis_password:
            warnings.append(
                {
                    "severity": "critical",
                    "key": key,
                    "message": (
                        f"Effective {key} password still differs from REDIS_PASSWORD after "
                        "sync; check later dotenv overrides or unsupported dotenv syntax."
                    ),
                }
            )
    return warnings


def sync_env_chain(
    base_env_file: Path = DEFAULT_ENV_FILE,
    *,
    all_envs: bool = False,
) -> dict[str, Any]:
    specs = discover_env_chain(base_env_file, include_all_envs=all_envs)
    if not specs or not specs[0].path.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {base_env_file}")

    if all_envs:
        # Mirrors sync_database_passwords.sync_env_chain: don't let a stale
        # variant REDIS_PASSWORD become the effective password while
        # repairing every dotenv variant.
        redis_password = _base_redis_password(specs[0].path) or _effective_redis_password(
            discover_env_chain(base_env_file)
        )
    else:
        redis_password = _effective_redis_password(specs)
    if not redis_password:
        raise ValueError("REDIS_PASSWORD is not set in the env chain")

    file_summaries: list[dict[str, Any]] = []
    changed_files: list[str] = []
    changed_keys_by_file: dict[str, list[str]] = {}
    for spec in specs:
        if not spec.path.is_file():
            file_summaries.append(
                {
                    "label": spec.label,
                    "env_file": str(spec.path),
                    "exists": False,
                    "changed": False,
                    "changed_keys": [],
                    "skipped": {key: "file_missing" for key in REDIS_URL_KEYS},
                }
            )
            continue

        original = spec.path.read_text(encoding="utf-8")
        updated, summary = _sync_env_text_with_password(
            original,
            redis_password,
            sync_redis_password_assignment=all_envs,
        )
        if updated != original:
            spec.path.write_text(updated, encoding="utf-8")
            changed_files.append(str(spec.path))
            changed_keys_by_file[str(spec.path)] = list(summary["changed_keys"])
        file_summaries.append(
            {"label": spec.label, "env_file": str(spec.path), "exists": True, **summary}
        )

    effective_env_after_sync = _effective_env_from_specs(specs)
    warnings = _effective_url_validation_warnings(effective_env_after_sync)

    changed_keys = sorted({key for keys in changed_keys_by_file.values() for key in keys})
    no_change_guidance = (
        "No dotenv URL changes were needed. If Doctor still reports Redis password drift, "
        "reload the launcher environment or restart the parent process before rechecking."
        if not changed_files
        else ""
    )
    return {
        "env_file": str(specs[0].path),
        "changed": bool(changed_files),
        "no_change_guidance": no_change_guidance,
        "changed_keys": changed_keys,
        "changed_files": changed_files,
        "changed_keys_by_file": changed_keys_by_file,
        "checked_files": [str(spec.path) for spec in specs],
        "checked_keys": list(REDIS_URL_KEYS),
        "redis_password_set": True,
        "strategy": "sync_passwords",
        "all_envs": all_envs,
        "warnings": warnings,
        "file_summaries": file_summaries,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SIDAR_REDIS_URL ve REDIS_URL parolalarını REDIS_PASSWORD ile eşitle",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--env-file", default=str(DEFAULT_ENV_FILE), help="Güncellenecek env dosyası"
    )
    parser.add_argument(
        "--all-envs",
        action="store_true",
        help=(
            ".env değerini kaynak kabul ederek .env.development, .env.test ve "
            ".env.advanced dosyalarındaki Redis parolalarını/URL'lerini eşitle"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Detaylı JSON özeti yazdır",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = sync_env_chain(Path(args.env_file), all_envs=args.all_envs)
    except Exception as exc:
        print(f"❌ Redis parola senkronizasyonu başarısız: {exc}", file=sys.stderr)
        return 1

    if summary.get("changed"):
        print("✅ Redis URL parolaları REDIS_PASSWORD ile eşitlendi.", file=sys.stderr)
    else:
        print("ℹ️ Redis URL parolaları zaten REDIS_PASSWORD ile uyumlu.", file=sys.stderr)
        if summary.get("no_change_guidance"):
            print(f"ℹ️ {summary['no_change_guidance']}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.verbose else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
