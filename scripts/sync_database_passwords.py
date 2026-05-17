"""Synchronize PostgreSQL URL passwords across Sidar dotenv files.

The script keeps ``DATABASE_URL`` and ``SIDAR_CONTAINER_DATABASE_URL`` aligned
with the effective ``POSTGRES_PASSWORD`` without printing secret values. It is
intentionally idempotent so Doctor auto-fix can offer it safely when
``database_env`` detects password drift, including drift introduced by later
dotenv overrides such as ``.env.development`` or ``SIDAR_KEYS_FILE``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DATABASE_URL_KEYS = ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL")
ENV_CHAIN_KEYS = (
    *DATABASE_URL_KEYS,
    "POSTGRES_PASSWORD",
    "SIDAR_ENV",
    "DOTENV_FILE",
    "SIDAR_KEYS_FILE",
)


@dataclass(frozen=True)
class EnvFileSpec:
    label: str
    path: Path
    override: bool


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


def _remove_assignment_lines(text: str, keys: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    """Remove selected dotenv assignments so config.py can derive them from POSTGRES_*."""
    assignments = _parse_env_text(text)
    remove_indexes = {
        assignment.line_index for key in keys if (assignment := assignments.get(key)) is not None
    }
    removed_keys = [key for key in keys if key in assignments]
    postgres_assignment = assignments.get("POSTGRES_PASSWORD")
    postgres_password_set = bool(postgres_assignment and postgres_assignment.value)
    if not remove_indexes:
        return text, {
            "changed": False,
            "changed_keys": [],
            "removed_keys": [],
            "skipped": {key: "missing" for key in keys},
            "checked_keys": list(keys),
            "postgres_password_set": postgres_password_set,
        }

    lines = [line for index, line in enumerate(text.splitlines()) if index not in remove_indexes]
    trailing_newline = "\n" if text.endswith("\n") or lines else ""
    skipped = {key: "missing" for key in keys if key not in assignments}
    return "\n".join(lines) + trailing_newline, {
        "changed": True,
        "changed_keys": removed_keys,
        "removed_keys": removed_keys,
        "skipped": skipped,
        "checked_keys": list(keys),
        "postgres_password_set": postgres_password_set,
    }


def prune_env_text(text: str) -> tuple[str, dict[str, Any]]:
    """Remove explicit database URL assignments and rely on POSTGRES_* derivation."""
    return _remove_assignment_lines(text, DATABASE_URL_KEYS)


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


def _sync_env_text_with_password(text: str, postgres_password: str) -> tuple[str, dict[str, Any]]:
    """Return updated env text using an already-resolved effective password."""
    if not postgres_password:
        raise ValueError("POSTGRES_PASSWORD is not set in the effective env chain")

    assignments = _parse_env_text(text)
    lines = text.splitlines()
    changed_keys: list[str] = []
    skipped: dict[str, str] = {}
    for key in DATABASE_URL_KEYS:
        assignment = assignments.get(key)
        if assignment is None or not assignment.value:
            skipped[key] = "missing"
            continue
        updated = _postgres_url_with_password(assignment.value, postgres_password)
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


def sync_env_text(text: str) -> tuple[str, dict[str, Any]]:
    """Return updated env text plus a redacted summary for a single env file."""
    assignments = _parse_env_text(text)
    postgres_password = assignments.get("POSTGRES_PASSWORD")
    if postgres_password is None or not postgres_password.value:
        raise ValueError("POSTGRES_PASSWORD is not set in the env file")
    return _sync_env_text_with_password(text, postgres_password.value)


def _resolve_chain_path(raw_path: str, *, root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


def _read_assignments(path: Path) -> dict[str, EnvAssignment]:
    if not path.is_file():
        return {}
    return _parse_env_text(path.read_text(encoding="utf-8"))


def _apply_assignments_to_env(
    env: dict[str, str],
    assignments: dict[str, EnvAssignment],
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


def _append_existing_spec(specs: list[EnvFileSpec], seen: set[Path], spec: EnvFileSpec) -> None:
    resolved = spec.path.expanduser().resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    specs.append(EnvFileSpec(spec.label, resolved, spec.override))


def discover_env_chain(base_env_file: Path = DEFAULT_ENV_FILE) -> list[EnvFileSpec]:
    """Discover Sidar's dotenv chain without mutating ``os.environ``."""
    base_env_file = base_env_file.expanduser()
    if not base_env_file.is_absolute():
        base_env_file = (PROJECT_ROOT / base_env_file).resolve()
    root = base_env_file.parent
    effective_env = dict(os.environ)
    specs: list[EnvFileSpec] = []
    seen: set[Path] = set()

    for spec in (
        EnvFileSpec("base", base_env_file, False),
        EnvFileSpec("advanced", root / ".env.advanced", False),
    ):
        _append_existing_spec(specs, seen, spec)
        _apply_assignments_to_env(
            effective_env, _read_assignments(spec.path), override=spec.override
        )

    sidar_env = effective_env.get("SIDAR_ENV", "").strip().lower()
    # Development is Sidar's common local override file and was historically
    # missed by the auto-fix when SIDAR_ENV was not exported in the shell.
    environment_names = [sidar_env] if sidar_env else ["development"]
    for env_name in environment_names:
        spec = EnvFileSpec(f"environment:{env_name}", root / f".env.{env_name}", True)
        _append_existing_spec(specs, seen, spec)
        _apply_assignments_to_env(effective_env, _read_assignments(spec.path), override=True)

    explicit_dotenv = effective_env.get("DOTENV_FILE", "").strip()
    if explicit_dotenv:
        spec = EnvFileSpec(
            "explicit:DOTENV_FILE",
            _resolve_chain_path(explicit_dotenv, root=root),
            True,
        )
        _append_existing_spec(specs, seen, spec)
        _apply_assignments_to_env(effective_env, _read_assignments(spec.path), override=True)

    sidar_keys_file = effective_env.get("SIDAR_KEYS_FILE", "~/.sidar_keys.env").strip()
    if sidar_keys_file:
        spec = EnvFileSpec(
            "secret:SIDAR_KEYS_FILE",
            _resolve_chain_path(sidar_keys_file, root=root),
            True,
        )
        _append_existing_spec(specs, seen, spec)
        _apply_assignments_to_env(effective_env, _read_assignments(spec.path), override=True)
    return specs


def _effective_postgres_password(specs: list[EnvFileSpec]) -> str:
    return _effective_env_from_specs(specs).get("POSTGRES_PASSWORD", "")


def _message_entry(message: str, *, severity: str, **metadata: str) -> dict[str, str]:
    """Build a machine-readable, secret-free sync diagnostic entry."""
    return {"severity": severity, "message": message, **metadata}


def _file_skip_diagnostics(
    *,
    spec: EnvFileSpec,
    assignments: dict[str, EnvAssignment],
    skipped: dict[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Explain skipped URL keys without treating normal chained-dotenv absence as warnings."""
    warnings: list[dict[str, str]] = []
    notes: list[dict[str, str]] = []
    if not skipped:
        return warnings, notes

    defines_password = bool(assignments.get("POSTGRES_PASSWORD"))
    for key, reason in skipped.items():
        if reason == "missing":
            if spec.override and defines_password:
                notes.append(
                    _message_entry(
                        f"{spec.label} defines POSTGRES_PASSWORD but does not define {key}; "
                        "the effective PostgreSQL URL is expected to come from an earlier "
                        "dotenv file in chained configurations.",
                        severity="info",
                        key=key,
                        label=spec.label,
                    )
                )
            continue
        if reason == "not_postgresql_or_missing_username":
            warnings.append(
                _message_entry(
                    f"{spec.label} defines {key}, but it is not a PostgreSQL URL with a username; "
                    "password synchronization skipped that key.",
                    severity="warning",
                    key=key,
                    label=spec.label,
                )
            )
    return warnings, notes


def _effective_url_validation_warnings(effective_env: dict[str, str]) -> list[dict[str, str]]:
    """Validate effective URL passwords after syncing all files."""
    postgres_password = effective_env.get("POSTGRES_PASSWORD", "")
    if not postgres_password:
        return []

    warnings: list[dict[str, str]] = []
    for key in DATABASE_URL_KEYS:
        raw_url = effective_env.get(key, "").strip()
        if not raw_url:
            continue
        parsed = urlsplit(raw_url)
        if not parsed.scheme.startswith("postgresql") or not parsed.username:
            continue
        url_password = unquote(parsed.password or "")
        if url_password != postgres_password:
            warnings.append(
                _message_entry(
                    f"Effective {key} password still differs from POSTGRES_PASSWORD after sync; "
                    "a parent-process environment value or later dotenv override may still be active. "
                    "Restart the launcher, unset the inherited variable, or use --prefer-derived if URL rows are not needed.",
                    severity="critical",
                    key=key,
                )
            )
    return warnings


def sync_env_file(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Any]:
    if not env_file.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {env_file}")
    original = env_file.read_text(encoding="utf-8")
    updated, summary = sync_env_text(original)
    if updated != original:
        env_file.write_text(updated, encoding="utf-8")
    return {"env_file": str(env_file), **summary}


def sync_env_chain(
    base_env_file: Path = DEFAULT_ENV_FILE, *, prefer_derived: bool = False
) -> dict[str, Any]:
    specs = discover_env_chain(base_env_file)
    if not specs or not specs[0].path.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {base_env_file}")

    postgres_password = _effective_postgres_password(specs)
    if not prefer_derived and not postgres_password:
        raise ValueError("POSTGRES_PASSWORD is not set in the env chain")

    file_summaries: list[dict[str, Any]] = []
    changed_files: list[str] = []
    changed_keys_by_file: dict[str, list[str]] = {}
    warnings: list[dict[str, str]] = []
    notes: list[dict[str, str]] = []
    for spec in specs:
        if not spec.path.is_file():
            skipped = {key: "file_missing" for key in DATABASE_URL_KEYS}
            file_summaries.append(
                {
                    "label": spec.label,
                    "env_file": str(spec.path),
                    "exists": False,
                    "changed": False,
                    "changed_keys": [],
                    "skipped": skipped,
                    "warnings": [],
                    "notes": [],
                }
            )
            continue

        original = spec.path.read_text(encoding="utf-8")
        assignments = _parse_env_text(original)
        if prefer_derived:
            updated, summary = prune_env_text(original)
        else:
            updated, summary = _sync_env_text_with_password(original, postgres_password)
        file_warnings, file_notes = _file_skip_diagnostics(
            spec=spec, assignments=assignments, skipped=summary["skipped"]
        )
        warnings.extend(file_warnings)
        notes.extend(file_notes)
        if updated != original:
            spec.path.write_text(updated, encoding="utf-8")
            changed_files.append(str(spec.path))
            changed_keys_by_file[str(spec.path)] = list(summary["changed_keys"])
        file_summaries.append(
            {
                "label": spec.label,
                "env_file": str(spec.path),
                "exists": True,
                **summary,
                "warnings": file_warnings,
                "notes": file_notes,
            }
        )

    effective_env_after_sync = _effective_env_from_specs(specs)
    if prefer_derived:
        for key in DATABASE_URL_KEYS:
            raw_url = effective_env_after_sync.get(key, "").strip()
            if raw_url:
                warnings.append(
                    _message_entry(
                        f"Effective {key} is still set after removal; a parent-process environment value or later dotenv source still defines it.",
                        severity="critical",
                        key=key,
                    )
                )
    else:
        warnings.extend(_effective_url_validation_warnings(effective_env_after_sync))

    changed_keys = sorted({key for keys in changed_keys_by_file.values() for key in keys})
    no_change_guidance = (
        "No dotenv URL changes were needed. If Doctor still reports database_env drift, "
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
        "checked_keys": list(DATABASE_URL_KEYS),
        "postgres_password_set": bool(postgres_password),
        "prefer_derived": prefer_derived,
        "warnings": warnings,
        "notes": notes,
        "file_summaries": file_summaries,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DATABASE_URL ve SIDAR_CONTAINER_DATABASE_URL parolalarını POSTGRES_PASSWORD ile eşitle",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--env-file", default=str(DEFAULT_ENV_FILE), help="Güncellenecek env dosyası"
    )
    parser.add_argument(
        "--prefer-derived",
        action="store_true",
        help=(
            "DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL satırlarını kaldırıp "
            "config.py içindeki POSTGRES_* tabanlı dinamik üretimi tercih et"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = sync_env_chain(Path(args.env_file), prefer_derived=args.prefer_derived)
    except Exception as exc:
        print(f"❌ PostgreSQL parola senkronizasyonu başarısız: {exc}", file=sys.stderr)
        return 1

    if summary.get("changed"):
        if summary.get("prefer_derived"):
            print(
                "✅ PostgreSQL URL satırları kaldırıldı; bağlantılar POSTGRES_* değerlerinden üretilecek.",
                file=sys.stderr,
            )
        else:
            print("✅ PostgreSQL URL parolaları POSTGRES_PASSWORD ile eşitlendi.", file=sys.stderr)
    else:
        print("ℹ️ PostgreSQL URL parolaları zaten POSTGRES_PASSWORD ile uyumlu.", file=sys.stderr)
        if summary.get("no_change_guidance"):
            print(f"ℹ️ {summary['no_change_guidance']}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
