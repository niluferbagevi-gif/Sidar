"""Synchronize PostgreSQL URL passwords in a Sidar env file.

The script keeps ``DATABASE_URL`` and ``SIDAR_CONTAINER_DATABASE_URL`` aligned
with ``POSTGRES_PASSWORD`` without printing secret values. It is intentionally
idempotent so Doctor auto-fix can offer it safely when database_env detects
password drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DATABASE_URL_KEYS = ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL")


@dataclass(frozen=True)
class EnvAssignment:
    key: str
    value: str
    quote_char: str
    export_prefix: str
    line_index: int


def _parse_assignment(line: str, line_index: int) -> EnvAssignment | None:
    stripped = line.lstrip()
    leading = line[: len(line) - len(stripped)]
    export_prefix = ""
    body = stripped
    if body.startswith("export "):
        export_prefix = f"{leading}export "
        body = body[len("export ") :]
    else:
        export_prefix = leading

    if not body or body.startswith("#") or "=" not in body:
        return None
    key, raw_value = body.split("=", 1)
    key = key.strip()
    if not key or any(char.isspace() for char in key):
        return None

    value = raw_value.strip()
    quote_char = ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote_char = value[0]
        value = value[1:-1]
    return EnvAssignment(
        key=key,
        value=value,
        quote_char=quote_char,
        export_prefix=export_prefix,
        line_index=line_index,
    )


def _parse_env_text(text: str) -> dict[str, EnvAssignment]:
    assignments: dict[str, EnvAssignment] = {}
    for index, line in enumerate(text.splitlines()):
        assignment = _parse_assignment(line, index)
        if assignment is not None:
            assignments[assignment.key] = assignment
    return assignments


def _quote_env_value(value: str, quote_char: str) -> str:
    if not quote_char:
        return value
    escaped = value.replace(quote_char, f"\\{quote_char}")
    return f"{quote_char}{escaped}{quote_char}"


def _replace_assignment_line(lines: list[str], assignment: EnvAssignment, value: str) -> None:
    lines[assignment.line_index] = (
        f"{assignment.export_prefix}{assignment.key}="
        f"{_quote_env_value(value, assignment.quote_char)}"
    )


def _postgres_url_with_password(database_url: str, postgres_password: str) -> str | None:
    parsed = urlsplit(database_url)
    if not parsed.scheme.startswith("postgresql"):
        return None
    if not parsed.username:
        return None

    encoded_user = quote(unquote(parsed.username), safe="")
    encoded_password = quote(postgres_password, safe="")
    host = parsed.hostname or ""
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{encoded_user}:{encoded_password}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def sync_env_text(text: str) -> tuple[str, dict[str, Any]]:
    """Return updated env text plus a redacted summary."""
    assignments = _parse_env_text(text)
    postgres_password = assignments.get("POSTGRES_PASSWORD")
    if postgres_password is None or not postgres_password.value:
        raise ValueError("POSTGRES_PASSWORD is not set in the env file")

    lines = text.splitlines()
    changed_keys: list[str] = []
    skipped: dict[str, str] = {}
    for key in DATABASE_URL_KEYS:
        assignment = assignments.get(key)
        if assignment is None or not assignment.value:
            skipped[key] = "missing"
            continue
        updated = _postgres_url_with_password(assignment.value, postgres_password.value)
        if updated is None:
            skipped[key] = "not_postgresql_or_missing_username"
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
        "checked_keys": list(DATABASE_URL_KEYS),
        "postgres_password_set": True,
    }
    return updated_text, summary


def sync_env_file(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Any]:
    if not env_file.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {env_file}")
    original = env_file.read_text(encoding="utf-8")
    updated, summary = sync_env_text(original)
    if updated != original:
        env_file.write_text(updated, encoding="utf-8")
    return {"env_file": str(env_file), **summary}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DATABASE_URL ve SIDAR_CONTAINER_DATABASE_URL parolalarını POSTGRES_PASSWORD ile eşitle",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Güncellenecek env dosyası")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = sync_env_file(Path(args.env_file))
    except Exception as exc:
        print(f"❌ PostgreSQL parola senkronizasyonu başarısız: {exc}", file=sys.stderr)
        return 1

    if summary.get("changed"):
        print("✅ PostgreSQL URL parolaları POSTGRES_PASSWORD ile eşitlendi.", file=sys.stderr)
    else:
        print("ℹ️ PostgreSQL URL parolaları zaten POSTGRES_PASSWORD ile uyumlu.", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
