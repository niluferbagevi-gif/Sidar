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
# Keys whose post-sync effective values the launcher re-applies to its own
# os.environ. POSTGRES_* helpers are included so config.get_database_url can
# rebuild a derived DSN when DATABASE_URL is not stored verbatim in any file.
SNAPSHOT_KEYS = (
    "DATABASE_URL",
    "SIDAR_CONTAINER_DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_CONTAINER_HOST",
)
ENV_CHAIN_KEYS = (
    *DATABASE_URL_KEYS,
    *SNAPSHOT_KEYS,
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


def _file_skip_diagnostics(
    *,
    spec: EnvFileSpec,
    assignments: dict[str, EnvAssignment],
    skipped: dict[str, str],
) -> dict[str, list[dict[str, str]]]:
    """Classify skipped URL keys into actionable warnings and informational notes.

    "missing" is the expected case for chained dotenv files since a single file
    typically owns each URL, so it is treated as an informational note (and
    only emitted when the same file also defines POSTGRES_PASSWORD or carries
    the override flag, where the absence is unusual enough to mention).
    Genuine misconfigurations (non-postgres URLs or missing usernames) remain
    warnings so they stand out.
    """
    diagnostics: dict[str, list[dict[str, str]]] = {"warnings": [], "notes": []}
    if not skipped:
        return diagnostics

    defines_password = bool(assignments.get("POSTGRES_PASSWORD"))
    for key, reason in skipped.items():
        if reason == "missing":
            if spec.override and defines_password:
                diagnostics["notes"].append(
                    {
                        "severity": "info",
                        "message": (
                            f"{spec.label} defines POSTGRES_PASSWORD but not {key}; an earlier "
                            "dotenv file is expected to provide the effective PostgreSQL URL. "
                            "Only investigate if Doctor still reports password drift."
                        ),
                    }
                )
            continue
        if reason == "not_postgresql_or_missing_username":
            diagnostics["warnings"].append(
                {
                    "severity": "warning",
                    "message": (
                        f"{spec.label} defines {key}, but it is not a PostgreSQL URL with a "
                        "username; password synchronization skipped that key."
                    ),
                }
            )
    return diagnostics


def _effective_url_validation_diagnostics(
    effective_env: dict[str, str],
) -> list[dict[str, str]]:
    """Validate effective URL passwords after syncing all files (critical severity)."""
    postgres_password = effective_env.get("POSTGRES_PASSWORD", "")
    if not postgres_password:
        return []

    diagnostics: list[dict[str, str]] = []
    for key in DATABASE_URL_KEYS:
        raw_url = effective_env.get(key, "").strip()
        if not raw_url:
            continue
        parsed = urlsplit(raw_url)
        if not parsed.scheme.startswith("postgresql") or not parsed.username:
            continue
        url_password = unquote(parsed.password or "")
        if url_password != postgres_password:
            diagnostics.append(
                {
                    "severity": "critical",
                    "message": (
                        f"Effective {key} password still differs from POSTGRES_PASSWORD after "
                        "sync; check later dotenv overrides or unsupported dotenv syntax."
                    ),
                }
            )
    return diagnostics


def sync_env_file(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Any]:
    if not env_file.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {env_file}")
    original = env_file.read_text(encoding="utf-8")
    updated, summary = sync_env_text(original)
    if updated != original:
        env_file.write_text(updated, encoding="utf-8")
    return {"env_file": str(env_file), **summary}


def _effective_snapshot(specs: list[EnvFileSpec]) -> dict[str, str]:
    """Resolve only the keys the launcher re-applies after a Doctor auto-fix."""
    effective_env = _effective_env_from_specs(specs)
    return {key: effective_env[key] for key in SNAPSHOT_KEYS if key in effective_env}


def _write_effective_snapshot(path: Path, snapshot: dict[str, str]) -> None:
    """Write the effective env snapshot atomically so the launcher reads a complete file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def sync_env_chain(base_env_file: Path = DEFAULT_ENV_FILE) -> dict[str, Any]:
    specs = discover_env_chain(base_env_file)
    if not specs or not specs[0].path.is_file():
        raise FileNotFoundError(f"Env dosyası bulunamadı: {base_env_file}")

    postgres_password = _effective_postgres_password(specs)
    if not postgres_password:
        raise ValueError("POSTGRES_PASSWORD is not set in the env chain")

    file_summaries: list[dict[str, Any]] = []
    changed_files: list[str] = []
    changed_keys_by_file: dict[str, list[str]] = {}
    warning_details: list[dict[str, str]] = []
    notes: list[str] = []
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
        updated, summary = _sync_env_text_with_password(original, postgres_password)
        diagnostics = _file_skip_diagnostics(
            spec=spec, assignments=assignments, skipped=summary["skipped"]
        )
        file_warning_messages = [item["message"] for item in diagnostics["warnings"]]
        file_note_messages = [item["message"] for item in diagnostics["notes"]]
        warning_details.extend(diagnostics["warnings"])
        notes.extend(file_note_messages)
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
                "warnings": file_warning_messages,
                "notes": file_note_messages,
            }
        )

    effective_env_after_sync = _effective_env_from_specs(specs)
    critical_diagnostics = _effective_url_validation_diagnostics(effective_env_after_sync)
    warning_details.extend(critical_diagnostics)

    warnings = [item["message"] for item in warning_details]
    critical_warnings = [
        item["message"] for item in warning_details if item.get("severity") == "critical"
    ]

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
        "postgres_password_set": True,
        "warnings": warnings,
        "warning_details": warning_details,
        "critical_warnings": critical_warnings,
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
        "--snapshot-out",
        default="",
        help=(
            "Sync sonrası etkin DB ortam değişkenlerini JSON dosyasına yaz "
            "(launcher os.environ'a doğrudan uygulasın)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = sync_env_chain(Path(args.env_file))
    except Exception as exc:
        print(f"❌ PostgreSQL parola senkronizasyonu başarısız: {exc}", file=sys.stderr)
        return 1

    snapshot_path = args.snapshot_out.strip()
    if snapshot_path:
        specs = discover_env_chain(Path(args.env_file))
        snapshot_env = _effective_snapshot(specs)
        snapshot_payload = {
            "env": snapshot_env,
            "critical_warnings": list(summary.get("critical_warnings", [])),
        }
        _write_effective_snapshot(Path(snapshot_path).expanduser(), snapshot_payload)
        summary["snapshot_out"] = str(Path(snapshot_path).expanduser())
        summary["snapshot_keys"] = sorted(snapshot_env.keys())

    if summary.get("changed"):
        print("✅ PostgreSQL URL parolaları POSTGRES_PASSWORD ile eşitlendi.", file=sys.stderr)
    else:
        print("ℹ️ PostgreSQL URL parolaları zaten POSTGRES_PASSWORD ile uyumlu.", file=sys.stderr)
        if summary.get("no_change_guidance"):
            print(f"ℹ️ {summary['no_change_guidance']}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
