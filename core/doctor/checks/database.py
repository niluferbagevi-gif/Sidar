"""Database and pgvector Doctor checks."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import unquote

import core.doctor as _doctor
from core.doctor import DoctorCheck
from core.doctor.models import redact_sensitive_text as _redact_sensitive_text


def _is_postgres_url(parsed: Any) -> bool:
    return bool(parsed and str(parsed.scheme).startswith("postgresql"))


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
    text = _redact_sensitive_text(str(exc))
    candidates = {
        database_url,
        _doctor._normalize_postgres_dsn(database_url),
        _redact_url(database_url),
    }
    parsed, _ = _doctor._parse_url(database_url)
    password = unquote(str(getattr(parsed, "password", "") or "")) if parsed else ""
    if password:
        candidates.add(password)
    for candidate in sorted((value for value in candidates if value), key=len, reverse=True):
        text = text.replace(candidate, "***" if candidate == password else _redact_url(candidate))
    return _redact_sensitive_text(text)


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
            "PostgreSQL authentication failed; verify "
            "DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL/POSTGRES_PASSWORD parity. "
            "If a Docker volume already existed, sync the stored PostgreSQL user password or reset "
            "the dev volume. "
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
                    "If Doctor/database_env is already pass but auth still fails, synchronize the "
                    "stored PostgreSQL role password in the existing Docker volume.",
                    "Run uv run python -m scripts.sync_postgres_password so the password is read "
                    "from POSTGRES_PASSWORD without exposing it in the shell command.",
                    "Restart PostgreSQL and rerun `uv run python -m core.doctor "
                    "artifacts/install/doctor.json`.",
                ],
                "auto_fix": "uv run python -m scripts.sync_postgres_password",
                "recommended_commands": [
                    "uv run python -m scripts.sync_postgres_password",
                    *common_commands,
                    "# development only: docker compose down && docker volume rm "
                    "<sidar_postgres_data> && docker compose up -d postgres",
                ],
            },
        )
    if any(
        marker in text for marker in ("role", "does not exist", "3d000", "invalid catalog name")
    ):
        return (
            "PostgreSQL is reachable but the expected user/database is missing; verify "
            "POSTGRES_USER and POSTGRES_DB initialization.",
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
                "auto_fix": "uv run python -m scripts.create_missing_databases",
                "recommended_commands": common_commands,
            },
        )
    if "ssl" in text and any(
        marker in text for marker in ("cannot be changed now", "cantchangeruntimeparamerror")
    ):
        return (
            'DATABASE_URL contains an unsupported ssl query value (e.g. "ssl=disable") that '
            "asyncpg forwards to PostgreSQL as a startup parameter; PostgreSQL rejects it "
            "because ssl is a server-only GUC. This is not a certificate/handshake problem.",
            {
                "failure_category": "invalid_ssl_query_param",
                "root_cause_hints": [
                    "DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL has a libpq-style sslmode value "
                    '(e.g. "?ssl=disable") that asyncpg does not understand as a client-side '
                    "flag",
                    "asyncpg passes the unrecognized value through as a server startup "
                    'parameter, and PostgreSQL refuses it with `parameter "ssl" cannot be '
                    "changed now`",
                    "This is usually a legacy value left over from an older install/config; "
                    "the current auto-derivation path never emits ssl=<value>",
                ],
                "remediation_steps": [
                    "Run uv run python -m scripts.sync_database_passwords "
                    "--remove-explicit-urls to drop the explicit DATABASE_URL/"
                    "SIDAR_CONTAINER_DATABASE_URL and let Sidar re-derive them from "
                    "POSTGRES_* parts.",
                    "If an explicit URL must be kept, remove the ssl query parameter "
                    "entirely (asyncpg does not accept libpq sslmode strings such as "
                    "disable/allow/prefer/require).",
                ],
                "auto_fix": (
                    "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
                ),
                "recommended_commands": [
                    "uv run python -m scripts.sync_database_passwords --remove-explicit-urls",
                    *common_commands,
                ],
            },
        )
    if any(
        marker in text
        for marker in (
            "ssl",
            "tls",
            "certificate verify failed",
            "handshake",
        )
    ):
        return (
            "PostgreSQL TLS/SSL handshake failed; verify certificate trust, SSL mode and "
            "proxy/network interception settings.",
            {
                "failure_category": "tls",
                "root_cause_hints": [
                    "PostgreSQL certificate is untrusted or expired",
                    "DATABASE_URL SSL mode does not match the server configuration",
                    "A proxy or network appliance interrupted the TLS handshake",
                ],
                "recommended_commands": common_commands,
            },
        )
    if any(marker in text for marker in ("timeout", "timed out", "zaman aş")):
        return (
            "PostgreSQL connectivity smoke timed out; verify the service, host, port and container "
            "networking.",
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
            "PostgreSQL connectivity smoke failed; verify that the container/service is running "
            "and DATABASE_URL host/port are correct.",
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
        "PostgreSQL connectivity smoke failed; Sidar will enter SQLite degraded mode and "
        "pgvector/BM25 fallback may be used",
        {
            "failure_category": "unknown",
            "root_cause_hints": [
                "Verify .env database credentials",
                "Verify PostgreSQL service status and networking",
            ],
            "recommended_commands": common_commands,
        },
    )


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

    # ``parse_qsl`` is deliberately avoided here: Doctor only needs the key and
    # malformed percent escapes in a DSN must not make the readiness report crash.
    query_keys = {
        item.partition("=")[0].strip().lower()
        for item in str(getattr(parsed, "query", "") or "").split("&")
        if item.partition("=")[0].strip()
    }
    if "ssl" in query_keys:
        failures.append(
            f"{label} contains unsupported ssl query parameter; remove it instead of using "
            "libpq-style ssl=disable/allow/prefer/require with asyncpg"
        )

    url_user = unquote(str(getattr(parsed, "username", "") or ""))
    url_password = unquote(str(getattr(parsed, "password", "") or ""))
    url_db = _database_name(parsed)

    if _doctor._is_weak_secret(url_password):
        failures.append(f"{label} contains an empty or weak database password")
    if postgres_user and url_user and url_user != postgres_user:
        failures.append(f"{label} user does not match POSTGRES_USER")
    if postgres_password and url_password and url_password != postgres_password:
        failures.append(
            f"{label} password does not match POSTGRES_PASSWORD; PostgreSQL may reject "
            f"authentication"
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
    database_url, container_url, explicit_database_url, explicit_container_url = (
        _doctor._resolved_database_urls()
    )
    postgres_user = os.getenv("POSTGRES_USER", "").strip()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    postgres_db = os.getenv("POSTGRES_DB", "").strip()
    parsed, database_url_parse_error = _doctor._parse_url(database_url)
    container_parsed, container_url_parse_error = _doctor._parse_url(container_url)
    source_report = _doctor._dotenv_source_report(
        ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL", "POSTGRES_PASSWORD")
    )
    env_sources = source_report.get("sources", {})
    env_definitions = source_report.get("definitions", {})

    failures: list[str] = []
    warnings: list[str] = []
    if database_url_parse_error:
        failures.append(f"DATABASE_URL is malformed: {database_url_parse_error}")
    if container_url_parse_error:
        failures.append(f"SIDAR_CONTAINER_DATABASE_URL is malformed: {container_url_parse_error}")
    if not database_url:
        warnings.append(
            "DATABASE_URL could not be resolved; database readiness cannot be fully verified"
        )
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
    if postgres_password and _doctor._is_weak_secret(postgres_password):
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

    # An explicit DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL that isn't defined in any
    # dotenv file Sidar itself loads (env_sources) is inherited from the parent
    # process/shell environment (an old `export`, a Docker Compose `environment:`/
    # `env_file` injection, systemd, etc.). scripts.sync_database_passwords only edits
    # dotenv files, so it reports "no explicit URL found" and cannot fix this — without
    # this note, Doctor keeps flagging the same drift after every "successful" auto-fix.
    database_url_unattributed = bool(explicit_database_url) and "DATABASE_URL" not in env_sources
    container_url_unattributed = (
        bool(explicit_container_url) and "SIDAR_CONTAINER_DATABASE_URL" not in env_sources
    )
    for key, unattributed in (
        ("DATABASE_URL", database_url_unattributed),
        ("SIDAR_CONTAINER_DATABASE_URL", container_url_unattributed),
    ):
        if not unattributed:
            continue
        if not any(msg.startswith(f"{key} ") for msg in (*failures, *warnings)):
            continue
        source_diagnostic = (
            f"{key} is set but not defined in Sidar's dotenv chain (.env, .env.advanced, "
            ".env.<SIDAR_ENV>, DOTENV_FILE, SIDAR_KEYS_FILE); it is inherited from the parent "
            "process/shell environment (or a Docker Compose environment:/env_file injection), "
            "so scripts.sync_database_passwords cannot edit it. Unset it in the parent shell or "
            "Docker Compose config, or restart the launcher, before rechecking."
        )
        # Keep source attribution visible in the top-level message even when the
        # underlying URL defect is a failure (Doctor otherwise renders failures
        # instead of warnings).
        (failures if failures else warnings).append(source_diagnostic)

    if (explicit_database_url or explicit_container_url) and failures:
        warnings.append(
            "Explicit DATABASE_URL/SIDAR_CONTAINER_DATABASE_URL is set; prefer derived "
            "POSTGRES_* flow and run scripts.sync_database_passwords --remove-explicit-urls "
            "for long-term safety"
        )

    if failures:
        for key in ("DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL"):
            source_note = _source_message(key, env_sources)
            if source_note and source_note not in failures:
                failures.append(source_note)

    status = "fail" if failures else ("warn" if warnings else "pass")
    message = "; ".join(failures or warnings or ["database environment looks secure"])
    failure_reason = "; ".join(failures) if failures else ""
    database_config_missing = not database_url and not postgres_password
    bootstrap_command = "uv run python -m scripts.bootstrap_env --profile development"
    sync_command = "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    auto_fix = bootstrap_command if database_config_missing else sync_command
    recommended_commands = (
        [
            bootstrap_command,
            "SIDAR_ENV=development uv run python -m core.doctor artifacts/install/doctor.json",
            "docker compose up -d postgres",
        ]
        if database_config_missing
        else [
            *(
                ["unset DATABASE_URL SIDAR_CONTAINER_DATABASE_URL"]
                if database_url_unattributed or container_url_unattributed
                else []
            ),
            sync_command,
            "uv run python -m scripts.sync_database_passwords",
            "uv run python -m core.doctor artifacts/install/doctor.json",
            "docker compose ps postgres",
        ]
    )
    return DoctorCheck(
        "database_env",
        status,
        message,
        {
            "database_url_set": bool(database_url),
            "container_database_url_set": bool(container_url),
            "database_url_explicit": explicit_database_url,
            "container_database_url_explicit": explicit_container_url,
            "database_url_derived": bool(database_url) and not explicit_database_url,
            "container_database_url_derived": bool(container_url) and not explicit_container_url,
            "postgres_user_set": bool(postgres_user),
            "postgres_password_set": bool(postgres_password),
            "postgres_db_set": bool(postgres_db),
            "failure_reason": failure_reason,
            "scheme": parsed.scheme if parsed else "",
            "container_scheme": container_parsed.scheme if container_parsed else "",
            "database_url_source": (env_sources.get("DATABASE_URL") or {}).get("path", ""),
            "container_database_url_source": (
                env_sources.get("SIDAR_CONTAINER_DATABASE_URL") or {}
            ).get("path", ""),
            "database_url_source_unattributed": database_url_unattributed,
            "container_database_url_source_unattributed": container_url_unattributed,
            "postgres_password_source": (env_sources.get("POSTGRES_PASSWORD") or {}).get(
                "path", ""
            ),
            "env_source_definitions": env_definitions,
            "auto_fix": auto_fix,
            "recommended_commands": recommended_commands,
            "root_cause_hints": [
                "DATABASE_URL ve SIDAR_CONTAINER_DATABASE_URL aktif dotenv zincirinde tanımlı "
                "değilse Sidar bunları POSTGRES_* parçalarından otomatik üretir",
                "Açık PostgreSQL URL tanımları tutulacaksa URL içindeki parola "
                "POSTGRES_PASSWORD ile eşleşmeli ve URL-encoded olmalı",
            ],
            "remediation_steps": [
                *(
                    [
                        "DATABASE_URL veya SIDAR_CONTAINER_DATABASE_URL parent shell/process "
                        "ortamından geliyorsa önce `unset DATABASE_URL "
                        "SIDAR_CONTAINER_DATABASE_URL` çalıştırın; bir alt süreç parent shell "
                        "değişkenlerini silemeyeceği için dosya tabanlı auto-fix tek başına bu "
                        "override'ı düzeltemez. Ardından Doctor'ı aynı shell'de yeniden çalıştırın."
                    ]
                    if database_url_unattributed or container_url_unattributed
                    else []
                ),
                "Kalıcı çözüm için uv run python -m scripts.sync_database_passwords "
                "--remove-explicit-urls ile dotenv zincirindeki açık DATABASE_URL ve "
                "SIDAR_CONTAINER_DATABASE_URL tanımlarını kaldırıp Sidar'ın POSTGRES_* "
                "parçalarından üretmesine izin verin.",
                "Açık URL tutmanız gerekiyorsa uv run python -m scripts.sync_database_passwords "
                "ile dotenv zincirindeki PostgreSQL URL parolalarını POSTGRES_PASSWORD ile "
                "eşitleyin.",
                "Env değerleri doğruysa fakat bağlantı hâlâ başarısızsa PostgreSQL "
                "kullanıcısının kayıtlı parolasını ALTER USER ile güncelleyin veya yalnız "
                "geliştirme ortamında volume resetleyin.",
            ],
        },
    )


def check_database_connectivity() -> DoctorCheck:
    database_url, _, explicit_database_url, _ = _doctor._resolved_database_urls()
    parsed, parse_error = _doctor._parse_url(database_url)
    details: dict[str, Any] = {
        "database_url_set": bool(database_url),
        "database_url_explicit": explicit_database_url,
        "database_url_derived": bool(database_url) and not explicit_database_url,
        "database_url": _redact_url(database_url),
        "scheme": parsed.scheme if parsed else "",
        "recommended_commands": [
            "docker compose ps postgres",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ],
    }
    source_report = _doctor._dotenv_source_report(("DATABASE_URL",))
    database_url_source = (source_report.get("sources", {}).get("DATABASE_URL") or {}).get(
        "path", ""
    )
    database_url_unattributed = bool(explicit_database_url) and not database_url_source
    details["database_url_source"] = database_url_source
    details["database_url_source_unattributed"] = database_url_unattributed
    if not database_url:
        return DoctorCheck(
            "database_connectivity",
            "warn",
            "DATABASE_URL could not be resolved; PostgreSQL connectivity smoke was skipped",
            details,
        )
    if parse_error:
        details["error"] = parse_error
        details["failure_category"] = "invalid_dsn"
        return DoctorCheck(
            "database_connectivity",
            "warn",
            "DATABASE_URL is malformed; PostgreSQL connectivity smoke was skipped",
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
        probe = _doctor._run_coro_sync(
            _doctor._probe_postgres_connectivity(database_url, timeout_seconds=timeout_seconds)
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
        if database_url_unattributed and guidance.get("failure_category") == (
            "invalid_ssl_query_param"
        ):
            unset_command = "unset DATABASE_URL SIDAR_CONTAINER_DATABASE_URL"
            message += (
                " The effective DATABASE_URL is inherited from the parent process/shell; the "
                "dotenv repair command cannot change it. Unset it there and rerun Doctor."
            )
            details["parent_environment_remediation"] = unset_command
            details.setdefault("remediation_steps", []).insert(
                0,
                "Run `unset DATABASE_URL SIDAR_CONTAINER_DATABASE_URL` in the parent shell, "
                "then rerun Doctor from that same shell.",
            )
            recommended = details.setdefault("recommended_commands", [])
            recommended.insert(0, unset_command)
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


def check_pgvector_ready(
    database_connectivity: DoctorCheck | None = None,
) -> DoctorCheck:
    """Check pgvector after reusing an optional PostgreSQL connectivity result."""
    vector_backend = os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower()
    details: dict[str, Any] = {
        "vector_backend": vector_backend,
        "required": vector_backend == "pgvector",
    }
    if vector_backend != "pgvector":
        return DoctorCheck(
            "pgvector_ready",
            "pass",
            "RAG_VECTOR_BACKEND is not pgvector; pgvector readiness check skipped",
            details,
        )

    database_url, _, explicit_database_url, _ = _doctor._resolved_database_urls()
    parsed, parse_error = _doctor._parse_url(database_url)
    details.update(
        {
            "database_url_set": bool(database_url),
            "database_url_explicit": explicit_database_url,
            "database_url_derived": bool(database_url) and not explicit_database_url,
            "database_url": _redact_url(database_url),
            "scheme": parsed.scheme if parsed else "",
            "recommended_commands": [
                "docker compose pull postgres && docker compose up -d postgres",
                "uv run python -m scripts.create_missing_databases",
                "uv run python -m core.doctor artifacts/install/doctor.json",
            ],
            "auto_fix": "docker compose pull postgres && docker compose up -d postgres",
        }
    )
    if not database_url:
        return DoctorCheck("pgvector_ready", "warn", "DATABASE_URL could not be resolved", details)
    if parse_error:
        details["error"] = parse_error
        details["failure_category"] = "invalid_dsn"
        return DoctorCheck("pgvector_ready", "warn", "DATABASE_URL is malformed", details)
    if not _is_postgres_url(parsed):
        return DoctorCheck(
            "pgvector_ready",
            "warn",
            "RAG_VECTOR_BACKEND=pgvector but DATABASE_URL is not PostgreSQL",
            details,
        )

    if database_connectivity is not None:
        details["database_connectivity_status"] = database_connectivity.status
        connectivity_details = database_connectivity.details
        if connectivity_details.get("select_1"):
            details.update(
                {
                    key: connectivity_details[key]
                    for key in ("select_1", "pgvector_extension_installed")
                    if key in connectivity_details
                }
            )
        elif database_connectivity.status != "pass":
            details["blocked_by"] = "database_connectivity"
            for key in ("error", "error_type", "failure_category"):
                if key in connectivity_details:
                    details[key] = connectivity_details[key]
            return DoctorCheck(
                "pgvector_ready",
                "warn",
                "pgvector readiness is blocked by the PostgreSQL connectivity check",
                details,
            )

    timeout_seconds = max(0.1, int(os.getenv("HEALTHCHECK_CONNECT_TIMEOUT_MS", "250")) / 1000)
    details["timeout_seconds"] = timeout_seconds
    if "select_1" not in details:
        try:
            probe = _doctor._run_coro_sync(
                _doctor._probe_postgres_connectivity(database_url, timeout_seconds=timeout_seconds)
            )
            details.update(probe)
        except Exception as exc:
            details["error"] = _redact_exception_text(exc, database_url=database_url)
            details["error_type"] = type(exc).__name__
            return DoctorCheck(
                "pgvector_ready",
                "warn",
                (
                    "pgvector readiness could not be verified because PostgreSQL "
                    "connectivity probe failed"
                ),
                details,
            )

    if not details.get("pgvector_extension_installed"):
        return DoctorCheck(
            "pgvector_ready",
            "fail",
            "RAG_VECTOR_BACKEND=pgvector but 'vector' extension is not installed",
            details,
        )
    return DoctorCheck(
        "pgvector_ready",
        "pass",
        (
            "pgvector extension is installed (this check verifies extension presence only; "
            "it does not confirm the application's own pgvector connection pool actually "
            "initializes at runtime - see core.rag.backends.pgvector.pgvector_runtime_status() "
            "for that)"
        ),
        details,
    )


__all__ = ["check_database_connectivity", "check_database_env", "check_pgvector_ready"]
