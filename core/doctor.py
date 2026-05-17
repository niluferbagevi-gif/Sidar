"""Installation/readiness doctor for Sidar.

The doctor intentionally performs lightweight, bounded checks so it can be used
both from `sidar doctor` and from installer subcommands without becoming another
opaque installation phase.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sidar_assets.paths import migrations_path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = BASE_DIR / "artifacts" / "install" / "doctor.json"


@dataclass
class DoctorCheck:
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


WEAK_SECRET_VALUES = {
    "",
    "sidar",
    "admin",
    "password",
    "changeme",
    "change_me",
    "secret",
    "default",
    "test",
    "example",
    "postgres",
    "root",
    "123456",
    "12345678",
}


def _run_command(cmd: list[str], *, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # nosec B603  # noqa: S603 - command list is internally constructed.
            cmd,
            cwd=BASE_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, f"timeout after {timeout}s\n{output}".strip()


def _status_from_bool(ok: bool, warn: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warn else "fail"


def _is_weak_secret(value: str | None) -> bool:
    normalized = (value or "").strip()
    return normalized.lower() in WEAK_SECRET_VALUES or len(normalized) < 24


def check_uv() -> DoctorCheck:
    uv_path = shutil.which("uv")
    if not uv_path:
        return DoctorCheck("uv", "fail", "uv executable not found on PATH")

    version_rc, version_out = _run_command([uv_path, "--version"])
    lock_rc, lock_out = _run_command([uv_path, "lock", "--check"], timeout=60)
    status = "pass" if version_rc == 0 and lock_rc == 0 else "fail"
    return DoctorCheck(
        "uv",
        status,
        "uv and uv.lock are ready" if status == "pass" else "uv lock validation failed",
        {"path": uv_path, "version": version_out, "lock_check": lock_out},
    )


def _is_postgres_url(parsed: Any) -> bool:
    return bool(parsed and str(parsed.scheme).startswith("postgresql"))


def _normalize_postgres_dsn(database_url: str) -> str:
    return str(database_url or "").replace("postgresql+asyncpg://", "postgresql://", 1)


def _redact_url(database_url: str) -> str:
    text = str(database_url or "").strip()
    if not text or "://" not in text:
        return text
    scheme, rest = text.split("://", 1)
    if "@" not in rest:
        return text
    credentials, host_part = rest.split("@", 1)
    if ":" not in credentials:
        return text
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host_part}"


def _redact_exception_text(exc: BaseException, *, database_url: str = "") -> str:
    text = str(exc)
    candidates = {database_url, _normalize_postgres_dsn(database_url), _redact_url(database_url)}
    parsed = urlparse(database_url) if database_url else None
    password = unquote(str(getattr(parsed, "password", "") or "")) if parsed else ""
    if password:
        candidates.add(password)
    for candidate in sorted((value for value in candidates if value), key=len, reverse=True):
        text = text.replace(candidate, "***" if candidate == password else _redact_url(candidate))
    return text


def _postgres_connectivity_failure_guidance(exc: BaseException) -> tuple[str, dict[str, Any]]:
    text = f"{type(exc).__name__} {exc}".lower()
    common_commands = [
        "docker compose ps postgres",
        "uv run python -m core.doctor artifacts/install/doctor.json",
    ]
    if any(
        marker in text
        for marker in (
            "password authentication failed",
            "authentication failed",
            "invalid password",
            "28p01",
            "permission denied",
            "auth",
        )
    ):
        return (
            "PostgreSQL authentication failed; verify DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL/POSTGRES_PASSWORD parity. "
            "If a Docker volume already existed, sync the stored PostgreSQL user password or reset the dev volume. "
            "Sidar will enter SQLite degraded mode and pgvector will fall back to BM25.",
            {
                "failure_category": "authentication",
                "root_cause_hints": [
                    "DATABASE_URL password does not match POSTGRES_PASSWORD",
                    "SIDAR_CONTAINER_DATABASE_URL uses different credentials than DATABASE_URL",
                    "PostgreSQL Docker volume was initialized with an older password",
                    "sidar user exists with a different password in PostgreSQL",
                ],
                "remediation_steps": [
                    "Compare POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DATABASE_URL and SIDAR_CONTAINER_DATABASE_URL in .env.",
                    "If the env values are correct but auth still fails, run ALTER USER for the existing PostgreSQL user or reset the PostgreSQL volume in development only.",
                    "Restart PostgreSQL and rerun `uv run python -m core.doctor artifacts/install/doctor.json`.",
                ],
                "recommended_commands": common_commands
                + [
                    "docker compose exec postgres psql -U postgres -d postgres -c \"ALTER USER <POSTGRES_USER> WITH PASSWORD '<POSTGRES_PASSWORD>';\"",
                    "# development only: docker compose down && docker volume rm <sidar_postgres_data> && docker compose up -d postgres",
                ],
            },
        )
    if any(
        marker in text for marker in ("role", "does not exist", "3d000", "invalid catalog name")
    ):
        return (
            "PostgreSQL is reachable but the expected user/database is missing; verify POSTGRES_USER and POSTGRES_DB initialization.",
            {
                "failure_category": "missing_role_or_database",
                "root_cause_hints": [
                    "sidar user or sidar database was not created",
                    "DATABASE_URL points to a database name that differs from POSTGRES_DB",
                    "Existing Docker volume was initialized before current .env values",
                ],
                "remediation_steps": [
                    "Check POSTGRES_USER and POSTGRES_DB in .env.",
                    "Create the missing role/database or reset the development PostgreSQL volume.",
                ],
                "recommended_commands": common_commands,
            },
        )
    if any(marker in text for marker in ("timeout", "timed out", "zaman aş")):
        return (
            "PostgreSQL connectivity smoke timed out; verify the service, host, port and container networking.",
            {
                "failure_category": "timeout",
                "root_cause_hints": [
                    "PostgreSQL service is slow or unavailable",
                    "DATABASE_URL host/port is unreachable from this process",
                ],
                "recommended_commands": common_commands,
            },
        )
    if any(
        marker in text
        for marker in (
            "connectionrefusederror",
            "connection refused",
            "could not connect",
            "server closed",
            "connection failed",
            "connection reset",
        )
    ):
        return (
            "PostgreSQL connectivity smoke failed; verify that the container/service is running and DATABASE_URL host/port are correct.",
            {
                "failure_category": "connection",
                "root_cause_hints": [
                    "PostgreSQL container is not running",
                    "DATABASE_URL points to localhost from the wrong runtime context",
                    "Port 5432 is not published or reachable",
                ],
                "recommended_commands": common_commands,
            },
        )
    return (
        "PostgreSQL connectivity smoke failed; Sidar will enter SQLite degraded mode and pgvector/BM25 fallback may be used",
        {
            "failure_category": "unknown",
            "root_cause_hints": [
                "Verify .env database credentials",
                "Verify PostgreSQL service status and networking",
            ],
            "recommended_commands": common_commands,
        },
    )


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _parse_env_file_values(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for source attribution without exposing secrets."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _dotenv_source_report(keys: tuple[str, ...]) -> dict[str, Any]:
    """Return best-effort source files for effective env values loaded by config.py."""
    try:
        from config import get_dotenv_load_report
    except Exception:
        return {"sources": {}, "definitions": {key: [] for key in keys}}

    sources: dict[str, dict[str, str]] = {}
    definitions: dict[str, list[dict[str, str]]] = {key: [] for key in keys}
    for event in get_dotenv_load_report():
        if not event.get("loaded") or not event.get("path"):
            continue
        path = Path(str(event["path"]))
        values = _parse_env_file_values(path)
        for key in keys:
            if key not in values:
                continue
            source = {
                "label": str(event.get("label", "")),
                "path": str(path),
                "override": str(bool(event.get("override"))),
            }
            definitions[key].append(source)
            if values[key] == os.getenv(key, "") or bool(event.get("override")):
                sources[key] = source
    return {"sources": sources, "definitions": definitions}


def _source_message(key: str, sources: dict[str, dict[str, str]]) -> str:
    source = sources.get(key) or {}
    path = source.get("path", "")
    label = source.get("label", "")
    if not path or label == "base":
        return ""
    return f"{key} is overridden in {path}"


def _database_name(parsed: Any) -> str:
    return str(getattr(parsed, "path", "") or "").lstrip("/").split("/", 1)[0]


def _validate_postgres_env_sync(
    *,
    label: str,
    parsed: Any,
    postgres_user: str,
    postgres_password: str,
    postgres_db: str,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if not _is_postgres_url(parsed):
        return failures, warnings

    url_user = unquote(str(getattr(parsed, "username", "") or ""))
    url_password = unquote(str(getattr(parsed, "password", "") or ""))
    url_db = _database_name(parsed)

    if _is_weak_secret(url_password):
        failures.append(f"{label} contains an empty or weak database password")
    if postgres_user and url_user and url_user != postgres_user:
        failures.append(f"{label} user does not match POSTGRES_USER")
    if postgres_password and url_password and url_password != postgres_password:
        failures.append(
            f"{label} password does not match POSTGRES_PASSWORD; PostgreSQL may reject authentication"
        )
    if postgres_db and url_db and url_db != postgres_db:
        warnings.append(f"{label} database name does not match POSTGRES_DB")
    return failures, warnings


def _validate_database_url_pair_sync(
    *,
    database_parsed: Any,
    container_parsed: Any,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if not (_is_postgres_url(database_parsed) and _is_postgres_url(container_parsed)):
        return failures, warnings

    database_user = unquote(str(getattr(database_parsed, "username", "") or ""))
    container_user = unquote(str(getattr(container_parsed, "username", "") or ""))
    database_password = unquote(str(getattr(database_parsed, "password", "") or ""))
    container_password = unquote(str(getattr(container_parsed, "password", "") or ""))
    database_name = _database_name(database_parsed)
    container_name = _database_name(container_parsed)

    if database_user and container_user and database_user != container_user:
        failures.append("DATABASE_URL user does not match SIDAR_CONTAINER_DATABASE_URL user")
    if database_password and container_password and database_password != container_password:
        failures.append(
            "DATABASE_URL password does not match SIDAR_CONTAINER_DATABASE_URL password; "
            "local and Docker PostgreSQL authentication will drift"
        )
    if database_name and container_name and database_name != container_name:
        warnings.append("DATABASE_URL database name does not match SIDAR_CONTAINER_DATABASE_URL")
    return failures, warnings


def check_database_env() -> DoctorCheck:
    database_url = os.getenv("DATABASE_URL", "").strip()
    container_url = os.getenv("SIDAR_CONTAINER_DATABASE_URL", "").strip()
    postgres_user = os.getenv("POSTGRES_USER", "").strip()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    postgres_db = os.getenv("POSTGRES_DB", "").strip()
    parsed = urlparse(database_url) if database_url else None
    container_parsed = urlparse(container_url) if container_url else None
    source_report = _dotenv_source_report(
        ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL", "POSTGRES_PASSWORD")
    )
    env_sources = source_report.get("sources", {})
    env_definitions = source_report.get("definitions", {})

    failures: list[str] = []
    warnings: list[str] = []
    if not database_url:
        warnings.append("DATABASE_URL is not set; database readiness cannot be fully verified")
    else:
        sync_failures, sync_warnings = _validate_postgres_env_sync(
            label="DATABASE_URL",
            parsed=parsed,
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            postgres_db=postgres_db,
        )
        failures.extend(sync_failures)
        warnings.extend(sync_warnings)
    if postgres_password and _is_weak_secret(postgres_password):
        failures.append("POSTGRES_PASSWORD is weak")
    if container_url:
        container_failures, container_warnings = _validate_postgres_env_sync(
            label="SIDAR_CONTAINER_DATABASE_URL",
            parsed=container_parsed,
            postgres_user=postgres_user,
            postgres_password=postgres_password,
            postgres_db=postgres_db,
        )
        failures.extend(container_failures)
        warnings.extend(container_warnings)
    if database_url and container_url:
        pair_failures, pair_warnings = _validate_database_url_pair_sync(
            database_parsed=parsed,
            container_parsed=container_parsed,
        )
        failures.extend(pair_failures)
        warnings.extend(pair_warnings)
    if container_url and "sidar:sidar@" in container_url:
        failures.append("SIDAR_CONTAINER_DATABASE_URL uses the legacy default password")

    if failures:
        for key in ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL"):
            source_note = _source_message(key, env_sources)
            if source_note and source_note not in failures:
                failures.append(source_note)

    status = "fail" if failures else ("warn" if warnings else "pass")
    message = "; ".join(failures or warnings or ["database environment looks secure"])
    return DoctorCheck(
        "database_env",
        status,
        message,
        {
            "database_url_set": bool(database_url),
            "container_database_url_set": bool(container_url),
            "postgres_user_set": bool(postgres_user),
            "postgres_password_set": bool(postgres_password),
            "postgres_db_set": bool(postgres_db),
            "scheme": parsed.scheme if parsed else "",
            "container_scheme": container_parsed.scheme if container_parsed else "",
            "database_url_source": (env_sources.get("DATABASE_URL") or {}).get("path", ""),
            "container_database_url_source": (
                env_sources.get("SIDAR_CONTAINER_DATABASE_URL") or {}
            ).get("path", ""),
            "postgres_password_source": (env_sources.get("POSTGRES_PASSWORD") or {}).get(
                "path", ""
            ),
            "env_source_definitions": env_definitions,
            "auto_fix": "uv run python -m scripts.sync_database_passwords",
            "recommended_commands": [
                "uv run python -m scripts.sync_database_passwords",
                "uv run python -m core.doctor artifacts/install/doctor.json",
                "docker compose ps postgres",
            ],
            "root_cause_hints": [
                "DATABASE_URL, SIDAR_CONTAINER_DATABASE_URL ve POSTGRES_PASSWORD değerleri aynı parolayı kullanmalı",
                "URL içindeki parola POSTGRES_PASSWORD ile eşleşmeli ve URL-encoded olmalı",
                "Mevcut PostgreSQL Docker volume eski parola ile başlatılmış olabilir",
            ],
            "remediation_steps": [
                "uv run python -m scripts.sync_database_passwords ile dotenv zincirindeki PostgreSQL URL parolalarını POSTGRES_PASSWORD ile eşitleyin.",
                "Env değerleri doğruysa fakat bağlantı hâlâ başarısızsa PostgreSQL kullanıcısının kayıtlı parolasını ALTER USER ile güncelleyin veya yalnız geliştirme ortamında volume resetleyin.",
            ],
        },
    )


def _run_coro_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result["error"] = exc

    thread = threading.Thread(target=_target, name="sidar-doctor-async-probe", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


async def _probe_postgres_connectivity(
    database_url: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    import asyncpg

    conn = await asyncio.wait_for(
        asyncpg.connect(dsn=_normalize_postgres_dsn(database_url)),
        timeout=timeout_seconds,
    )
    try:
        one = await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=timeout_seconds)
        vector_installed = await asyncio.wait_for(
            conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"),
            timeout=timeout_seconds,
        )
        return {"select_1": one == 1, "pgvector_extension_installed": bool(vector_installed)}
    finally:
        await conn.close()


def check_database_connectivity() -> DoctorCheck:
    database_url = os.getenv("DATABASE_URL", "").strip()
    parsed = urlparse(database_url) if database_url else None
    details: dict[str, Any] = {
        "database_url_set": bool(database_url),
        "database_url": _redact_url(database_url),
        "scheme": parsed.scheme if parsed else "",
        "recommended_commands": [
            "docker compose ps postgres",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ],
    }
    if not database_url:
        return DoctorCheck(
            "database_connectivity",
            "warn",
            "DATABASE_URL is not set; PostgreSQL connectivity smoke was skipped",
            details,
        )
    if not _is_postgres_url(parsed):
        return DoctorCheck(
            "database_connectivity",
            "pass",
            "non-PostgreSQL DATABASE_URL configured; PostgreSQL connectivity smoke skipped",
            details,
        )

    timeout_seconds = max(0.1, int(os.getenv("HEALTHCHECK_CONNECT_TIMEOUT_MS", "250")) / 1000)
    details["timeout_seconds"] = timeout_seconds
    try:
        probe = _run_coro_sync(
            _probe_postgres_connectivity(database_url, timeout_seconds=timeout_seconds)
        )
        details.update(probe)
    except ModuleNotFoundError as exc:
        details["error"] = _redact_exception_text(exc, database_url=database_url)
        return DoctorCheck(
            "database_connectivity",
            "warn",
            "asyncpg is unavailable; run `uv sync --all-extras` before PostgreSQL smoke checks",
            details,
        )
    except Exception as exc:
        details["error"] = _redact_exception_text(exc, database_url=database_url)
        details["error_type"] = type(exc).__name__
        message, guidance = _postgres_connectivity_failure_guidance(exc)
        details.update(guidance)
        return DoctorCheck("database_connectivity", "warn", message, details)

    if os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower() == "pgvector" and not details.get(
        "pgvector_extension_installed"
    ):
        return DoctorCheck(
            "database_connectivity",
            "warn",
            "PostgreSQL is reachable, but pgvector extension is not installed yet",
            details,
        )
    return DoctorCheck(
        "database_connectivity",
        "pass",
        "PostgreSQL connectivity smoke passed",
        details,
    )


def check_rag_readiness() -> DoctorCheck:
    vector_backend = os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower() or "chroma"
    graph_enabled = _get_bool_env("ENABLE_GRAPH_RAG", True)
    rag_dir = Path(os.getenv("RAG_DIR", "data/rag"))
    if not rag_dir.is_absolute():
        rag_dir = BASE_DIR / rag_dir

    index_path = rag_dir / "index.json"
    entity_graph_path = rag_dir / "entity_graph.json"
    index_exists = index_path.exists()
    entity_graph_exists = entity_graph_path.exists()
    index = _load_json_object(index_path)
    entity_graph = _load_json_object(entity_graph_path)
    entity_nodes = entity_graph.get("nodes", {}) if isinstance(entity_graph, dict) else {}
    entity_edges = entity_graph.get("edges", []) if isinstance(entity_graph, dict) else []
    document_count = len(index)
    entity_node_count = len(entity_nodes) if isinstance(entity_nodes, dict) else 0
    entity_edge_count = len(entity_edges) if isinstance(entity_edges, list) else 0

    details: dict[str, Any] = {
        "vector_backend": vector_backend,
        "graph_rag_enabled": graph_enabled,
        "rag_dir": str(rag_dir),
        "index_path": str(index_path),
        "index_exists": index_exists,
        "entity_graph_path": str(entity_graph_path),
        "entity_graph_exists": entity_graph_exists,
        "document_count": document_count,
        "entity_node_count": entity_node_count,
        "entity_edge_count": entity_edge_count,
        "bm25_fallback": "SQLite FTS5",
    }

    blockers: list[str] = []
    warnings: list[str] = []
    if vector_backend == "pgvector":
        database_check = check_database_env()
        details["database_env_status"] = database_check.status
        if database_check.status == "fail":
            blockers.append(
                "pgvector backend is configured but database environment parity failed; semantic RAG is blocked until database_env is fixed"
            )
            details["blocked_by"] = "database_env"
            details["database_env_message"] = database_check.message
            details["database_env_auto_fix"] = database_check.details.get(
                "auto_fix", "uv run python -m scripts.sync_database_passwords"
            )
    if not graph_enabled:
        warnings.append("GraphRAG is disabled by ENABLE_GRAPH_RAG=false")
    if document_count == 0:
        if not index_exists:
            warnings.append(
                "RAG index file is missing at data/rag/index.json; run "
                "`uv run python -m scripts.seed_rag` to create the local seed index or add "
                'external sources with `uv run python cli.py -c "belge ekle <url>"`; '
                "searches will rely on code graph/keyword/BM25 only until then"
            )
        else:
            warnings.append(
                "RAG has no indexed documents yet; run `uv run python -m scripts.seed_rag` "
                'or add external sources with `uv run python cli.py -c "belge ekle <url>"`; '
                "searches will rely on code graph/keyword/BM25 only until then"
            )
    if entity_node_count == 0 and graph_enabled:
        warnings.append(
            "GraphRAG entity memory is empty until documents are indexed or entity extraction runs"
        )

    if blockers:
        details["auto_fix"] = "uv run python -m scripts.sync_database_passwords"
        details["recommended_commands"] = [
            "uv run python -m scripts.sync_database_passwords",
            "uv run python -m core.doctor artifacts/install/doctor.json",
            "docker compose ps postgres",
        ]
        details["follow_up_commands"] = [
            "uv run python -m scripts.seed_rag",
            'uv run python cli.py -c "belge ekle <url>"',
        ]
        status = "warn"
        message = "; ".join(blockers + warnings)
    elif document_count == 0:
        details["auto_fix"] = "uv run python -m scripts.seed_rag"
        details["recommended_commands"] = [
            "uv run python -m scripts.seed_rag",
            'uv run python cli.py -c "belge ekle <url>"',
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ]
        status = "warn"
        message = "; ".join(warnings)
    else:
        details["auto_fix"] = ""
        details["recommended_commands"] = [
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ]
        status = "warn" if warnings else "pass"
        message = "; ".join(warnings or ["RAG readiness looks healthy"])
    return DoctorCheck("rag_readiness", status, message, details)


def _read_env_file_assignments(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE assignments from a dotenv file without expanding secrets."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def check_environment_profile() -> DoctorCheck:
    """Validate that the selected SIDAR_ENV profile has an isolated dotenv file."""
    profile = os.getenv("SIDAR_ENV", "").strip().lower()
    details: dict[str, Any] = {
        "sidar_env": profile,
        "base_env_path": str(BASE_DIR / ".env"),
        "advanced_env_path": str(BASE_DIR / ".env.advanced"),
        "recommended_commands": [
            "uv run python -m scripts.bootstrap_env --profile development",
            "cp .env.development.example .env.development",
        ],
    }
    if not profile:
        return DoctorCheck(
            "environment_profile",
            "pass",
            "SIDAR_ENV profile is not set; base dotenv/default settings are in use",
            details,
        )

    profile_path = BASE_DIR / f".env.{profile}"
    template_path = BASE_DIR / f".env.{profile}.example"
    details.update(
        {
            "profile_env_path": str(profile_path),
            "profile_env_exists": profile_path.exists(),
            "profile_template_path": str(template_path),
            "profile_template_exists": template_path.exists(),
        }
    )

    if profile == "test":
        return DoctorCheck(
            "environment_profile",
            "pass",
            "SIDAR_ENV=test uses test fixtures/process environment isolation",
            details,
        )
    if profile_path.exists():
        profile_values = _read_env_file_assignments(profile_path)
        effective_postgres_db = profile_values.get("POSTGRES_DB") or os.getenv("POSTGRES_DB", "")
        details["profile_postgres_db"] = effective_postgres_db
        if profile in {"development", "dev", "local"} and effective_postgres_db in {
            "sidar",
            "postgres",
        }:
            details["recommended_commands"] = [
                f"uv run python -m scripts.bootstrap_env --profile {profile} --force",
                (
                    f"edit .env.{profile} and set "
                    f"POSTGRES_DB=sidar_{profile if profile != 'dev' else 'development'}"
                ),
            ]
            return DoctorCheck(
                "environment_profile",
                "warn",
                (
                    f"SIDAR_ENV={profile} has .env.{profile}, but "
                    f"POSTGRES_DB={effective_postgres_db!r} is not isolated from the "
                    "base/production database"
                ),
                details,
            )
        return DoctorCheck(
            "environment_profile",
            "pass",
            f"SIDAR_ENV={profile} isolated dotenv file is present",
            details,
        )

    if template_path.exists():
        command = f"uv run python -m scripts.bootstrap_env --profile {profile}"
        details["recommended_commands"] = [command, f"cp .env.{profile}.example .env.{profile}"]
        return DoctorCheck(
            "environment_profile",
            "warn",
            f"SIDAR_ENV={profile} is active but .env.{profile} is missing; create it from .env.{profile}.example to isolate local settings",
            details,
        )

    return DoctorCheck(
        "environment_profile",
        "warn",
        f"SIDAR_ENV={profile} is active but no .env.{profile} or .env.{profile}.example file exists",
        details,
    )


def check_gpu_memory_config() -> DoctorCheck:
    """Report effective local model and VRAM budget settings."""
    from config import Config, normalize_gpu_memory_fractions

    provider = str(getattr(Config, "AI_PROVIDER", "ollama") or "ollama").strip().lower()
    coding_model = str(getattr(Config, "CODING_MODEL", "") or "").strip()
    access_level = str(getattr(Config, "ACCESS_LEVEL", "") or "").strip().lower()
    llm_fraction = float(getattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    rag_fraction = float(getattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    legacy_fraction = float(getattr(Config, "GPU_MEMORY_FRACTION", 0.0) or 0.0)
    budget = normalize_gpu_memory_fractions(llm_fraction, rag_fraction)
    total = llm_fraction + rag_fraction
    details: dict[str, Any] = {
        "ai_provider": provider,
        "coding_model": coding_model,
        "access_level": access_level,
        "gpu_memory_fraction": legacy_fraction,
        "llm_gpu_memory_fraction": llm_fraction,
        "rag_gpu_memory_fraction": rag_fraction,
        "total_gpu_memory_fraction": round(total, 4),
        "effective_gpu_memory_fraction": budget["gpu"],
        "effective_llm_gpu_memory_fraction": budget["llm"],
        "effective_rag_gpu_memory_fraction": budget["rag"],
        "normalized": budget["normalized"],
        "recommended_commands": [
            "uv run python -m scripts.bootstrap_env --profile development",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ],
    }

    warnings: list[str] = []
    if budget["normalized"]:
        warnings.append(
            "LLM/RAG VRAM fractions exceed 100% or are non-positive; Sidar will normalize the effective GPU budget to 80%"
        )
    elif total > 0.95:
        warnings.append(
            "LLM/RAG VRAM fractions are very high; consider lowering .env.development limits before bulk RAG ingestion"
        )
    if provider == "ollama" and coding_model != "qwen2.5-coder:7b":
        warnings.append(
            "local Ollama coding model differs from the Sidar standard qwen2.5-coder:7b"
        )
    if access_level != "sandbox":
        warnings.append("CLI access level is not sandbox; verify this is intentional")

    status = "warn" if warnings else "pass"
    message = "; ".join(warnings or ["Local model and VRAM configuration look safe"])
    return DoctorCheck("gpu_memory_config", status, message, details)


def _parse_migration_revisions() -> tuple[list[str], list[str]]:
    revisions: list[str] = []
    down_revisions: list[str] = []
    versions_dir = migrations_path() / "versions"
    for file_path in sorted(versions_dir.glob("*.py")):
        text = file_path.read_text(encoding="utf-8")
        rev_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        down_match = re.search(r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if rev_match:
            revisions.append(rev_match.group(1))
        if down_match:
            down_revisions.append(down_match.group(1))
    return revisions, down_revisions


def check_migrations() -> DoctorCheck:
    revisions, down_revisions = _parse_migration_revisions()
    heads = sorted(set(revisions) - set(down_revisions))
    if not revisions:
        return DoctorCheck("migrations", "fail", "no Alembic migration revisions found")

    rc, output = _run_command([sys.executable, "-m", "alembic", "heads"], timeout=30)
    status = "pass" if rc == 0 and all(head in output for head in heads) else "warn"
    return DoctorCheck(
        "migrations",
        status,
        "Alembic heads are discoverable"
        if status == "pass"
        else "Alembic head command could not be fully verified",
        {"expected_heads": heads, "revision_count": len(revisions), "alembic_heads_output": output},
    )


def check_agent_catalog() -> DoctorCheck:
    required_roles = {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
    try:
        from agent.registry import AgentCatalog

        registered = {spec.role_name for spec in AgentCatalog.list_all()}
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("agent_catalog", "fail", f"AgentCatalog failed to load: {exc}")

    missing = sorted(required_roles - registered)
    return DoctorCheck(
        "agent_catalog",
        _status_from_bool(not missing),
        "all built-in roles are registered"
        if not missing
        else f"missing roles: {', '.join(missing)}",
        {"required_roles": sorted(required_roles), "registered_roles": sorted(registered)},
    )


def check_supervisor_routing() -> DoctorCheck:
    try:
        from agent.core.supervisor import SupervisorAgent

        samples = {
            "research": "web kaynak araştır",
            "review": "pull request review incele",
            "marketing": "seo kampanya metni üret",
            "coverage": "pytest coverage eksik test yaz",
            "code": "dosyaya fonksiyon ekle",
        }
        observed = {
            expected: SupervisorAgent._intent(prompt) for expected, prompt in samples.items()
        }
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("supervisor_routing", "fail", f"Supervisor routing check failed: {exc}")

    mismatches = {expected: actual for expected, actual in observed.items() if expected != actual}
    return DoctorCheck(
        "supervisor_routing",
        _status_from_bool(not mismatches),
        "Supervisor intent routing smoke checks passed"
        if not mismatches
        else f"routing mismatches: {mismatches}",
        {"observed": observed},
    )


def check_websocket_routes() -> DoctorCheck:
    try:
        from web_server import app

        websocket_paths = sorted(
            getattr(route, "path", "")
            for route in app.routes
            if "WebSocket" in route.__class__.__name__
        )
    except Exception as exc:  # pragma: no cover - defensive runtime path
        source = (BASE_DIR / "web_server.py").read_text(encoding="utf-8")
        required = {"/ws/chat", "/ws/voice"}
        static_paths = sorted(path for path in required if f'@app.websocket("{path}")' in source)
        missing_static = sorted(required - set(static_paths))
        return DoctorCheck(
            "websocket_routes",
            "warn" if not missing_static else "fail",
            "web_server import failed, but websocket decorators were found statically"
            if not missing_static
            else f"web_server import failed and static routes are missing: {missing_static}",
            {
                "required": sorted(required),
                "websocket_paths": static_paths,
                "import_error": str(exc),
            },
        )

    required = {"/ws/chat", "/ws/voice"}
    missing = sorted(required - set(websocket_paths))
    return DoctorCheck(
        "websocket_routes",
        _status_from_bool(not missing),
        "required websocket routes are mounted"
        if not missing
        else f"missing websocket routes: {missing}",
        {"required": sorted(required), "websocket_paths": websocket_paths},
    )


def check_gpu() -> DoctorCheck:
    details: dict[str, Any] = {"detected": False, "run_gpu_stress": False}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        rc, output = _run_command(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=10
        )
        if rc == 0 and output:
            details.update(
                {"detected": True, "source": "nvidia-smi", "devices": output.splitlines()}
            )
    if not details["detected"]:
        try:
            import torch

            if torch.cuda.is_available():
                details.update(
                    {
                        "detected": True,
                        "source": "torch",
                        "devices": [
                            torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                        ],
                    }
                )
        except Exception as exc:
            details["torch_error"] = str(exc)

    details["run_gpu_stress"] = bool(details["detected"])
    return DoctorCheck(
        "gpu",
        "pass" if details["detected"] else "warn",
        "GPU detected; RUN_GPU_STRESS should be enabled"
        if details["detected"]
        else "GPU not detected; GPU stress tests remain opt-in",
        details,
    )


def _ollama_base_url() -> str:
    raw = os.getenv("OLLAMA_URL", "http://localhost:11434/api").rstrip("/")
    return raw if raw.endswith("/api") else f"{raw}/api"


def check_model(coding_model: str | None = None, *, smoke: bool = True) -> DoctorCheck:
    model = (coding_model or os.getenv("CODING_MODEL") or "qwen2.5-coder:7b").strip()
    model_prefix = model.split(":", 1)[0]
    base = _ollama_base_url()
    details: dict[str, Any] = {
        "model": model,
        "ollama_url": base,
        "present": False,
        "json_smoke": False,
    }
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            tags = client.get(f"{base}/tags")
            tags.raise_for_status()
            models = tags.json().get("models", [])
            names = {str(item.get("name", "")) for item in models if isinstance(item, dict)}
            details["present"] = model in names or any(
                name.startswith(model_prefix) for name in names
            )
            details["available_models"] = sorted(names)[:20]
            if smoke and details["present"]:
                prompt = 'Return exactly this JSON and nothing else: {"sidar_doctor": true}'
                response = client.post(
                    f"{base}/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                    timeout=60,
                )
                response.raise_for_status()
                text = str(response.json().get("response", "")).strip()
                details["smoke_response"] = text[:500]
                parsed = json.loads(text)
                details["json_smoke"] = parsed.get("sidar_doctor") is True
    except Exception as exc:
        details["error"] = str(exc)
        return DoctorCheck("model", "warn", "Ollama/model check could not be completed", details)

    if not details["present"]:
        return DoctorCheck("model", "warn", f"coding model is not present: {model}", details)
    if smoke and not details["json_smoke"]:
        return DoctorCheck(
            "model", "fail", "coding model did not return valid JSON smoke output", details
        )
    return DoctorCheck("model", "pass", "coding model is present and JSON smoke passed", details)


def run_doctor_report(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    include_model_smoke: bool = True,
) -> dict[str, Any]:
    checks = [
        check_uv(),
        check_environment_profile(),
        check_gpu_memory_config(),
        check_database_env(),
        check_database_connectivity(),
        check_rag_readiness(),
        check_migrations(),
        check_agent_catalog(),
        check_supervisor_routing(),
        check_websocket_routes(),
        check_gpu(),
        check_model(smoke=include_model_smoke),
    ]
    statuses = [check.status for check in checks]
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "overall_status": overall,
        "run_gpu_stress": any(
            check.name == "gpu" and bool(check.details.get("run_gpu_stress")) for check in checks
        ),
        "checks": [check.as_dict() for check in checks],
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    report = run_doctor_report(output_path=output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall_status"] in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
