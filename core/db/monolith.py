"""Sidar kalıcı veri katmanı (v3.0 hazırlık): kullanıcı/oturum/mesaj şemaları."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar, cast

import jwt

from config import Config
from core.db import audit as db_audit
from core.db import metrics as db_metrics
from core.db import prompt_registry as db_prompt_registry
from core.db import sessions as db_sessions
from core.db.auth import (
    _ARGON2ID_ALGORITHM as _ARGON2ID_ALGORITHM,
)
from core.db.auth import (
    _ARGON2ID_MEMORY_COST_ENV as _ARGON2ID_MEMORY_COST_ENV,
)
from core.db.auth import (
    _ARGON2ID_MEMORY_COST_KIB as _ARGON2ID_MEMORY_COST_KIB,
)
from core.db.auth import (
    _ARGON2ID_PARALLELISM_ENV as _ARGON2ID_PARALLELISM_ENV,
)
from core.db.auth import (
    _ARGON2ID_TIME_COST_ENV as _ARGON2ID_TIME_COST_ENV,
)
from core.db.auth import (
    _AUTH_HASH_SLO_MS_ENV as _AUTH_HASH_SLO_MS_ENV,
)
from core.db.auth import (
    _PASSWORD_HASH_ALGORITHM_ENV as _PASSWORD_HASH_ALGORITHM_ENV,
)
from core.db.auth import (
    _PBKDF2_ALGORITHM as _PBKDF2_ALGORITHM,
)
from core.db.auth import (
    _PBKDF2_ITERATIONS_ENV as _PBKDF2_ITERATIONS_ENV,
)
from core.db.auth import (
    _PBKDF2_LEGACY_ITERATIONS as _PBKDF2_LEGACY_ITERATIONS,
)
from core.db.auth import (
    _PBKDF2_MIN_ITERATIONS as _PBKDF2_MIN_ITERATIONS,
)
from core.db.auth import (
    AuthTokenRecord,
    UserRecord,
    _expires_in,
    _hash_password,
    _verify_password,
)
from core.db.auth import (
    _auth_hash_slo_ms as _auth_hash_slo_ms,
)
from core.db.auth import (
    _current_argon2id_params as _current_argon2id_params,
)
from core.db.auth import (
    _current_password_hash_algorithm as _current_password_hash_algorithm,
)
from core.db.auth import (
    _current_pbkdf2_iterations as _current_pbkdf2_iterations,
)
from core.db.auth import (
    _pbkdf2_sha256 as _pbkdf2_sha256,
)
from core.db.auth import (
    _record_auth_hash_latency as _record_auth_hash_latency,
)
from core.db.coverage import (
    CoverageFindingRecord as CoverageFindingRecord,
)
from core.db.coverage import (
    CoverageTaskRecord as CoverageTaskRecord,
)
from core.db.diagnostics import (
    _doctor_database_env_failure_reason as _doctor_database_env_failure_reason,
)
from core.db.diagnostics import (
    postgres_failure_diagnosis as _postgres_failure_diagnosis_impl,
)
from core.db.diagnostics import (
    postgres_user_action_message as _postgres_user_action_message_impl,
)
from core.db.dialect import (
    ASYNCPG_COMMAND_TAG_COUNT_RE as _DEFAULT_ASYNCPG_COMMAND_TAG_COUNT_RE,
)
from core.db.dialect import (
    parse_asyncpg_affected_rows as _parse_asyncpg_affected_rows_impl,
)
from core.db.dialect import (
    quote_sql_identifier as _quote_sql_identifier_impl,
)
from core.db.helpers import (
    json_dumps as _json_dumps,
)
from core.db.helpers import (
    new_entity_id as _new_entity_id,
)
from core.db.helpers import (
    parse_iso_datetime as _parse_iso_datetime,
)
from core.db.helpers import (
    sqlite_fetchone as _sqlite_fetchone,
)
from core.db.helpers import (
    utc_now_iso as _utc_now_iso,
)
from core.db.helpers import (
    utc_now_pair as _utc_now_pair,
)
from core.db.records import (
    AccessPolicyRecord as AccessPolicyRecord,
)
from core.db.records import (
    AuditLogRecord as AuditLogRecord,
)
from core.db.records import (
    ContentAssetRecord as ContentAssetRecord,
)
from core.db.records import (
    MarketingCampaignRecord as MarketingCampaignRecord,
)
from core.db.records import (
    OperationChecklistRecord as OperationChecklistRecord,
)
from core.db.records import (
    PromptRecord as PromptRecord,
)
from core.db.session import (
    MessageRecord as MessageRecord,
)
from core.db.session import (
    SessionRecord as SessionRecord,
)
from core.db_components.migrations import run_alembic_upgrade_head
from sidar_assets.paths import alembic_ini_path, migrations_path


def postgres_failure_diagnosis(reason: str, exc: BaseException | None = None) -> str:
    """Backwards-compatible wrapper that preserves legacy monkeypatch hooks."""
    original_doctor = _postgres_failure_diagnosis_impl.__globals__.get(
        "_doctor_database_env_failure_reason"
    )
    _postgres_failure_diagnosis_impl.__globals__[
        "_doctor_database_env_failure_reason"
    ] = _doctor_database_env_failure_reason
    try:
        return _postgres_failure_diagnosis_impl(reason, exc)
    finally:
        _postgres_failure_diagnosis_impl.__globals__[
            "_doctor_database_env_failure_reason"
        ] = original_doctor


def _postgres_user_action_message(reason: str, exc: BaseException | None = None) -> str:
    """Backwards-compatible wrapper that preserves legacy diagnosis monkeypatch hooks."""
    diagnosis = postgres_failure_diagnosis(reason, exc)
    if diagnosis == "DATABASE_URL yok/kayboldu":
        return (
            "PostgreSQL bağlantısı başlatılamadı (DATABASE_URL yok/kayboldu). "
            "Doctor/database_env sonucunu ve dotenv reload zincirini kontrol edin. "
            "SQLite degraded mode aktif edildi."
        )
    return _postgres_user_action_message_impl(reason, exc)

logger = logging.getLogger(__name__)
_ASYNCPG_COMMAND_TAG_COUNT_RE = _DEFAULT_ASYNCPG_COMMAND_TAG_COUNT_RE
_T = TypeVar("_T")


def _quote_sql_identifier(identifier: str) -> str:
    """Backwards-compatible facade for the extracted dialect helper."""
    return _quote_sql_identifier_impl(identifier)


def _parse_asyncpg_affected_rows(command_tag: Any) -> int:
    """Backwards-compatible facade for the extracted asyncpg tag parser."""
    return _parse_asyncpg_affected_rows_impl(command_tag)



class Database:
    """Asenkron veritabanı erişim katmanı.

    Not:
    - `DATABASE_URL` yoksa varsayılan PostgreSQL DSN kullanılır:
      `postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/sidar`
    - PostgreSQL URL (postgresql:// / postgresql+asyncpg://) verildiğinde `asyncpg`
      kullanılır; paket yoksa anlaşılır hata döndürür.
    - SQLite hâlâ desteklenir (örn. `sqlite+aiosqlite:///data/sidar.db`).
    """

    def __init__(
        self, cfg: Config | None = None, *, pg_pool_factory: Callable[..., Any] | None = None
    ) -> None:
        self.cfg = cfg or Config()
        self.database_url = (
            getattr(self.cfg, "DATABASE_URL", "") or ""
        ).strip() or "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/sidar"
        self.pool_size = max(1, int(getattr(self.cfg, "DB_POOL_SIZE", 5) or 5))
        self.pool_min_size = max(
            1,
            min(int(getattr(self.cfg, "DB_POOL_MIN_SIZE", 1) or 1), self.pool_size),
        )
        self.statement_cache_size = max(
            0, int(getattr(self.cfg, "DB_STATEMENT_CACHE_SIZE", 256) or 0)
        )
        self.max_cached_statement_lifetime = max(
            0.0, float(getattr(self.cfg, "DB_MAX_CACHED_STATEMENT_LIFETIME", 300.0) or 0.0)
        )
        self.schema_version_table = str(
            getattr(self.cfg, "DB_SCHEMA_VERSION_TABLE", "schema_versions") or "schema_versions"
        )
        self._schema_version_table_quoted = _quote_sql_identifier(self.schema_version_table)
        self.target_schema_version = int(getattr(self.cfg, "DB_SCHEMA_TARGET_VERSION", 1) or 1)
        self.auto_migrate = bool(getattr(self.cfg, "SIDAR_AUTO_MIGRATE", True))

        self._backend = "sqlite"
        self._sqlite_path: Path | None = None
        self._sqlite_conn: sqlite3.Connection | None = None
        self._sqlite_write_lock: asyncio.Lock | None = None

        self._pg_pool = None
        self._pg_pool_factory = pg_pool_factory
        self.degraded_mode = False
        self.degraded_reason = ""
        self.primary_database_url = self.database_url

        self._configure_backend()

    @property
    def _sqlite_lock(self) -> asyncio.Lock | None:
        """Geriye dönük uyumluluk için eski kilit adı."""
        return self._sqlite_write_lock

    @_sqlite_lock.setter
    def _sqlite_lock(self, value: asyncio.Lock | None) -> None:
        self._sqlite_write_lock = value

    def _configure_backend(self) -> None:
        lowered = self.database_url.lower()
        if lowered.startswith("postgresql://") or lowered.startswith("postgresql+asyncpg://"):
            self._backend = "postgresql"
            return

        self._backend = "sqlite"
        prefix = "sqlite+aiosqlite:///"
        raw_path = self.database_url
        if lowered.startswith(prefix):
            raw_path = self.database_url[len(prefix) :]
        elif lowered.startswith("sqlite:///"):
            raw_path = self.database_url[len("sqlite:///") :]

        path = Path(raw_path)
        if not path.is_absolute():
            base_dir = Path(getattr(self.cfg, "BASE_DIR", Path.cwd()))
            path = base_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_path = path

    @staticmethod
    def _message_columns_sql() -> str:
        return "id, session_id, role, content, tokens_used, created_at"

    @staticmethod
    def _sqlite_fetchone(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
        return _sqlite_fetchone(cursor)

    @staticmethod
    def _utc_now_pair() -> tuple[datetime, str]:
        return _utc_now_pair()

    @staticmethod
    def _to_message_record(row: Any) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            session_id=str(row["session_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            tokens_used=int(row["tokens_used"]),
            created_at=str(row["created_at"]),
        )

    async def _fetch_message_rows_by_session_ids(self, session_ids: list[str]) -> list[Any]:
        normalized_ids = [
            str(session_id).strip() for session_id in session_ids if str(session_id).strip()
        ]
        if not normalized_ids:
            return []

        columns = self._message_columns_sql()
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            # session_id sütunu PostgreSQL'de UUID tipindedir; doğrudan text[] ile
            # karşılaştırmak ``operator does not exist: uuid = text`` hatasına yol açar.
            # Bu yüzden hem girdi metinlerini ``uuid[]``'a hem de sütunu ``text``'e
            # çevirerek SQLite şemasıyla uyumlu bir karşılaştırma sağlıyoruz.
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT {columns}
                    FROM messages
                    WHERE session_id::text = ANY($1::text[])
                    ORDER BY session_id ASC, created_at ASC, id ASC
                    """,  # nosec B608  # columns sabit whitelist'ten üretilir.
                    normalized_ids,
                )
            return list(rows)

        assert self._sqlite_conn is not None
        placeholders = ",".join(["?"] * len(normalized_ids))

        def _run() -> list[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                f"""
                SELECT {columns}
                FROM messages
                WHERE session_id IN ({placeholders})
                ORDER BY session_id ASC, created_at ASC, id ASC
                """,  # nosec B608  # columns/placeholders iç kaynaklıdır.
                normalized_ids,
            )
            return cur.fetchall()

        return await self._run_sqlite_op(_run, write=False)

    async def connect(self) -> None:
        if self._backend == "postgresql":
            await self._connect_postgresql()
            return
        await self._connect_sqlite()

    async def _connect_sqlite(self) -> None:
        if self._sqlite_conn is not None:
            return

        assert self._sqlite_path is not None

        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(str(self._sqlite_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 10000;")
            return conn

        self._sqlite_conn = await asyncio.to_thread(_open)

    async def _run_sqlite_op(self, operation: Callable[[], _T], *, write: bool = True) -> _T:
        """SQLite işlemini çalıştırır.

        Varsayılan davranış yazma işlemlerini tek bir kilit ile sıralamaktır.
        Sadece-okuma çağrılarında `write=False` verilerek gereksiz lock contention
        azaltılabilir.
        """
        if self._sqlite_conn is None:
            raise RuntimeError("SQLite bağlantısı başlatılmadı.")
        running_loop = asyncio.get_running_loop()
        if self._sqlite_write_lock is None:
            self._sqlite_write_lock = asyncio.Lock()
        else:
            lock_loop = getattr(self._sqlite_write_lock, "_loop", None)
            if lock_loop is not None and lock_loop is not running_loop:
                logger.warning(
                    "SQLite kilidi farklı event loop'a bağlı bulundu; kilit yeniden oluşturuluyor."
                )
                self._sqlite_write_lock = asyncio.Lock()
        if not write:
            return await asyncio.to_thread(operation)

        async with self._sqlite_write_lock:
            for attempt in range(1, 4):
                try:
                    return await asyncio.to_thread(operation)
                except sqlite3.OperationalError as exc:
                    if "database is locked" not in str(exc).lower() or attempt == 3:
                        raise
                    await asyncio.sleep(
                        0.015 * (2 ** (attempt - 1)) + random.uniform(0.0, 0.01)  # nosec B311  # güvenlik değil jitter/backoff amaçlıdır.
                    )
                except Exception:
                    # Hata durumunda açık transaction'ı geri al; rollback başarısız olursa
                    # hatayı yutmak yerine üst katmana açıkça bildir.
                    try:
                        await asyncio.to_thread(self._sqlite_conn.rollback)
                    except Exception as rollback_exc:
                        logger.exception(
                            "SQLite rollback başarısız oldu; veri bütünlüğü riske girebilir."
                        )
                        raise RuntimeError(
                            "SQLite işlemi ve rollback başarısız oldu."
                        ) from rollback_exc
                    raise
        raise sqlite3.OperationalError("SQLite işlemi deneme sınırına ulaştı ve tamamlanamadı.")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Backend bağımsız transaction context manager.

        Kullanım:
            async with db.transaction() as conn:
                ...
        """
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                tx_ctx = conn.transaction()
                if inspect.isawaitable(tx_ctx):
                    tx_ctx = await tx_ctx
                async with tx_ctx:
                    yield conn
            return

        if self._sqlite_conn is None:
            raise RuntimeError("SQLite bağlantısı başlatılmadı.")
        running_loop = asyncio.get_running_loop()
        if self._sqlite_write_lock is None:
            self._sqlite_write_lock = asyncio.Lock()
        else:
            lock_loop = getattr(self._sqlite_write_lock, "_loop", None)
            if lock_loop is not None and lock_loop is not running_loop:
                self._sqlite_write_lock = asyncio.Lock()

        async with self._sqlite_write_lock:
            await asyncio.to_thread(self._sqlite_conn.execute, "BEGIN")
            try:
                yield self._sqlite_conn
            except Exception:
                await asyncio.to_thread(self._sqlite_conn.rollback)
                raise
            else:
                await asyncio.to_thread(self._sqlite_conn.commit)

    @staticmethod
    def _redact_database_url(database_url: str) -> str:
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

    def _postgres_degraded_sqlite_url(self) -> str:
        configured = str(getattr(self.cfg, "DB_DEGRADED_SQLITE_URL", "") or "").strip()
        if configured:
            return configured
        base_dir = Path(getattr(self.cfg, "BASE_DIR", Path.cwd()))
        return f"sqlite+aiosqlite:///{(base_dir / 'data' / 'sidar_degraded.db').as_posix()}"

    async def _enter_degraded_mode(self, reason: str, exc: BaseException) -> None:
        if not bool(getattr(self.cfg, "DB_DEGRADED_MODE_ON_POSTGRES_FAILURE", True)):
            raise exc

        fallback_url = self._postgres_degraded_sqlite_url()
        action_message = _postgres_user_action_message(reason, exc)
        logger.warning(
            "%s primary=%s fallback=%s",
            action_message,
            self._redact_database_url(self.primary_database_url),
            self._redact_database_url(fallback_url),
        )
        self.degraded_mode = True
        self.degraded_reason = action_message
        self._pg_pool = None
        self.database_url = fallback_url
        self.cfg.DATABASE_URL = fallback_url
        self._backend = "sqlite"
        self._sqlite_conn = None
        self._sqlite_write_lock = None
        self._configure_backend()
        await self._connect_sqlite()

    async def _connect_postgresql(self) -> None:
        if self._pg_pool is not None:
            return
        test_mode_short_circuit = bool(getattr(self.cfg, "DB_TEST_MODE_SHORT_CIRCUIT", False))
        lowered_url = self.database_url.lower()
        looks_like_local_postgres = any(
            marker in lowered_url for marker in ("@localhost", "@127.0.0.1", ":5432/")
        )
        if test_mode_short_circuit and self._pg_pool_factory is None and looks_like_local_postgres:
            await self._enter_degraded_mode(
                "Test mode PostgreSQL short-circuit (localhost bağlantısı atlandı)",
                RuntimeError("test mode postgres short-circuit"),
            )
            return
        try:
            if self._pg_pool_factory is None:
                import asyncpg

                pool_factory = asyncpg.create_pool
            else:
                pool_factory = self._pg_pool_factory
        except Exception as exc:  # pragma: no cover - paket opsiyonel
            await self._enter_degraded_mode("asyncpg bağımlılığı kullanılamıyor", exc)
            return

        dsn = self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        try:
            self._pg_pool = await pool_factory(
                dsn=dsn,
                min_size=self.pool_min_size,
                max_size=self.pool_size,
                statement_cache_size=self.statement_cache_size,
                max_cached_statement_lifetime=self.max_cached_statement_lifetime,
            )
        except Exception as exc:
            pool_error_type = None
            if self._pg_pool_factory is None:
                try:
                    import asyncpg as _asyncpg_mod

                    pool_error_type = getattr(_asyncpg_mod, "PoolError", None)
                except Exception:
                    pool_error_type = None
            is_pool_error = bool(pool_error_type and isinstance(exc, pool_error_type))
            error_text = str(exc).lower()
            if isinstance(exc, TimeoutError) or isinstance(exc, asyncio.TimeoutError):
                reason = "PostgreSQL bağlantı havuzu zaman aşımına uğradı"
            elif is_pool_error or "pool" in error_text:
                reason = "PostgreSQL bağlantı havuzu kullanılamıyor"
            else:
                reason = "PostgreSQL bağlantı havuzu oluşturulamadı"
            await self._enter_degraded_mode(reason, exc)

    async def close(self) -> None:
        if self._sqlite_conn is not None:
            conn = self._sqlite_conn
            self._sqlite_conn = None
            self._sqlite_write_lock = None
            if callable(getattr(conn, "close", None)):
                await asyncio.to_thread(conn.close)

        if self._pg_pool is not None:
            pool = self._pg_pool
            self._pg_pool = None
            await pool.close()

    async def init_schema(self) -> None:
        if self._backend == "postgresql":
            # PostgreSQL schema is managed by Alembic as the single source of truth.
            # Keep SQLite bootstrap below because degraded/local fallback does not run
            # Alembic and must remain dependency-light.
            await self._init_schema_postgresql()
            await self.ensure_default_prompt_registry()
            return
        await self._init_schema_sqlite()
        await self._ensure_access_control_schema_sqlite()
        await self._ensure_audit_log_schema_sqlite()
        await self._ensure_schema_version_sqlite()
        await self.ensure_default_prompt_registry()

    async def _ensure_access_control_schema_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            cols = self._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()
            col_names = {str(c[1]) for c in cols}
            if "tenant_id" not in col_names:
                self._sqlite_conn.execute(
                    "ALTER TABLE users ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                )
            self._sqlite_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL DEFAULT '*',
                    action TEXT NOT NULL,
                    effect TEXT NOT NULL DEFAULT 'allow',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, tenant_id, resource_type, resource_id, action),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            self._sqlite_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON access_policies(user_id, tenant_id, resource_type, action)"
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def _ensure_access_control_schema_postgresql(self) -> None:
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_policies (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL DEFAULT '*',
                    action TEXT NOT NULL,
                    effect TEXT NOT NULL DEFAULT 'allow',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(user_id, tenant_id, resource_type, resource_id, action)
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON access_policies(user_id, tenant_id, resource_type, action)"
            )

    async def _ensure_audit_log_schema_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '',
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    allowed INTEGER NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self._sqlite_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp)"
            )
            self._sqlite_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)"
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def _ensure_audit_log_schema_postgresql(self) -> None:
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    allowed BOOLEAN NOT NULL DEFAULT FALSE,
                    timestamp TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)"
            )

    async def _init_schema_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        schema_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            tenant_id TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_quotas (
            user_id TEXT PRIMARY KEY,
            daily_token_limit INTEGER NOT NULL DEFAULT 0,
            daily_request_limit INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS provider_usage_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            requests_used INTEGER NOT NULL DEFAULT 0,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, provider, usage_date),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_provider_usage_daily_user_id ON provider_usage_daily(user_id);
        CREATE TABLE IF NOT EXISTS access_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL DEFAULT '*',
            action TEXT NOT NULL,
            effect TEXT NOT NULL DEFAULT 'allow',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, tenant_id, resource_type, resource_id, action),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant
            ON access_policies(user_id, tenant_id, resource_type, action);

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'default',
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 0,
            timestamp TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);

        CREATE TABLE IF NOT EXISTS prompt_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_registry_role_version ON prompt_registry(role_name, version);
        CREATE INDEX IF NOT EXISTS idx_prompt_registry_role_active ON prompt_registry(role_name, is_active);

        CREATE TABLE IF NOT EXISTS marketing_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            objective TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            owner_user_id TEXT NOT NULL DEFAULT '',
            budget REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_tenant_status
            ON marketing_campaigns(tenant_id, status, updated_at);

        CREATE TABLE IF NOT EXISTS content_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            asset_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_content_assets_campaign_tenant
            ON content_assets(campaign_id, tenant_id, asset_type);

        CREATE TABLE IF NOT EXISTS operation_checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            title TEXT NOT NULL,
            items_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            owner_user_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_operation_checklists_campaign_tenant
            ON operation_checklists(campaign_id, tenant_id, status);

        CREATE TABLE IF NOT EXISTS coverage_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            requester_role TEXT NOT NULL DEFAULT 'coverage',
            command TEXT NOT NULL,
            pytest_output TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending_review',
            target_path TEXT NOT NULL DEFAULT '',
            suggested_test_path TEXT NOT NULL DEFAULT '',
            review_payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_coverage_tasks_tenant_status
            ON coverage_tasks(tenant_id, status, updated_at);

        CREATE TABLE IF NOT EXISTS coverage_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            finding_type TEXT NOT NULL,
            target_path TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES coverage_tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_coverage_findings_task
            ON coverage_findings(task_id, finding_type, severity);
        """

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.executescript(schema_sql)
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    def _run_alembic_upgrade_head(self) -> None:
        """Run the extracted Alembic migration helper for this database facade."""
        run_alembic_upgrade_head(
            database_url=self.database_url,
            alembic_ini=alembic_ini_path(),
            migrations_dir=migrations_path(),
        )

    async def _init_schema_postgresql(self) -> None:
        """Initialize PostgreSQL schema through Alembic when auto-migrate is enabled.

        In production, auto-migrate may be disabled by policy. We still run a one-time
        bootstrap migration when this looks like a fresh database (no alembic_version table).
        """
        assert self._pg_pool is not None
        should_run_migration = self.auto_migrate
        if not should_run_migration:
            if hasattr(self._pg_pool, "fetchval"):
                has_alembic_version = await self._pg_pool.fetchval(
                    "SELECT to_regclass('public.alembic_version')"
                )
            elif hasattr(self._pg_pool, "fetch_value"):
                has_alembic_version = await self._pg_pool.fetch_value(
                    "SELECT to_regclass('public.alembic_version')"
                )
            else:
                async with self._pg_pool.acquire() as conn:
                    has_alembic_version = await conn.fetchval(
                        "SELECT to_regclass('public.alembic_version')"
                    )
            if has_alembic_version:
                logger.info("SIDAR_AUTO_MIGRATE devre dışı; runtime Alembic upgrade atlandı.")
                return
            logger.warning(
                "SIDAR_AUTO_MIGRATE devre dışı ancak fresh DB tespit edildi (alembic_version yok). "
                "İlk açılış bootstrap migrasyonu çalıştırılıyor."
            )
            should_run_migration = True

        # Reaching this point always means migration is required: auto-migrate was
        # enabled initially or the disabled-policy fresh DB bootstrap promoted it.
        await asyncio.to_thread(self._run_alembic_upgrade_head)

    async def ensure_default_prompt_registry(self) -> None:
        await db_prompt_registry.ensure_default_prompt_registry(
            self, prompt_record_cls=PromptRecord
        )

    async def list_prompts(self, role_name: str | None = None) -> list[PromptRecord]:
        return cast(
            list[PromptRecord],
            await db_prompt_registry.list_prompts(self, role_name, prompt_record_cls=PromptRecord),
        )

    async def get_active_prompt(self, role_name: str) -> PromptRecord | None:
        return cast(
            PromptRecord | None,
            await db_prompt_registry.get_active_prompt(
                self, role_name, prompt_record_cls=PromptRecord
            ),
        )

    async def upsert_prompt(
        self, role_name: str, prompt_text: str, *, activate: bool = True
    ) -> PromptRecord:
        return cast(
            PromptRecord,
            await db_prompt_registry.upsert_prompt(
                self,
                role_name,
                prompt_text,
                activate=activate,
                prompt_record_cls=PromptRecord,
            ),
        )

    async def activate_prompt(self, prompt_id: int) -> PromptRecord | None:
        return cast(
            PromptRecord | None,
            await db_prompt_registry.activate_prompt(
                self, prompt_id, prompt_record_cls=PromptRecord
            ),
        )

    async def _ensure_schema_version_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            tbl = self._schema_version_table_quoted
            self._sqlite_conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)"
            )
            cur = self._sqlite_conn.execute(
                f"SELECT MAX(version) AS v FROM {tbl}"  # nosec B608  # tablo adı sistem içi sabittir.
            )
            row = _sqlite_fetchone(cur)
            current = int((row["v"] if row else 0) or 0)
            if current >= self.target_schema_version:
                return
            for v in range(current + 1, self.target_schema_version + 1):
                self._sqlite_conn.execute(
                    f"INSERT INTO {tbl} (version, applied_at, description) VALUES (?, ?, ?)",  # nosec B608
                    (v, _utc_now_iso(), f"baseline migration v{v}"),
                )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def _ensure_schema_version_postgresql(self) -> None:
        assert self._pg_pool is not None
        tbl = self._schema_version_table_quoted
        async with self._pg_pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL, description TEXT NOT NULL)"
            )
            current = await conn.fetchval(
                f"SELECT COALESCE(MAX(version), 0) FROM {tbl}"  # nosec B608  # tablo adı sistem içi sabittir.
            )
            current = int(current or 0)
            if current >= self.target_schema_version:
                return
            for v in range(current + 1, self.target_schema_version + 1):
                await conn.execute(
                    f"INSERT INTO {tbl} (version, applied_at, description) VALUES ($1, $2, $3)",  # nosec B608
                    v,
                    datetime.now(UTC),
                    f"baseline migration v{v}",
                )

    async def ensure_user(self, username: str, role: str = "user") -> UserRecord:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, role, created_at, tenant_id FROM users WHERE username=$1",
                    username,
                )
                if row:
                    return UserRecord(
                        id=str(row["id"]),
                        username=str(row["username"]),
                        role=str(row["role"]),
                        created_at=str(row["created_at"]),
                        tenant_id=str(
                            row.get("tenant_id", "default")
                            if hasattr(row, "get")
                            else row["tenant_id"]
                        ),
                    )
            return await self.create_user(username=username, role=role)

        assert self._sqlite_conn is not None

        def _fetch() -> sqlite3.Row | None:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE username=?",
                (username,),
            )
            return _sqlite_fetchone(cur)

        row = await self._run_sqlite_op(_fetch)
        if row:
            return UserRecord(
                id=str(row["id"]),
                username=str(row["username"]),
                role=str(row["role"]),
                created_at=str(row["created_at"]),
            )
        return await self.create_user(username=username, role=role)

    async def list_sessions(self, user_id: str) -> list[SessionRecord]:
        return await db_sessions.list_sessions(self, SessionRecord, user_id)

    async def count_sessions_total(self) -> int:
        return await db_sessions.count_sessions_total(self)

    async def load_session(
        self, session_id: str, user_id: str | None = None
    ) -> SessionRecord | None:
        return await db_sessions.load_session(
            self, SessionRecord, _sqlite_fetchone, session_id, user_id
        )

    async def update_session_title(self, session_id: str, title: str) -> bool:
        return await db_sessions.update_session_title(self, session_id, title)

    async def delete_session(self, session_id: str, user_id: str | None = None) -> bool:
        return await db_sessions.delete_session(self, session_id, user_id)

    async def create_user(
        self,
        username: str,
        role: str = "user",
        password: str | None = None,
        tenant_id: str = "default",
    ) -> UserRecord:
        user_id = _new_entity_id()
        created_at_dt, created_at = _utc_now_pair()
        password_hash = _hash_password(password) if password else None

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at) VALUES ($1, $2, $3, $4, $5, $6)",
                    user_id,
                    username,
                    password_hash,
                    role,
                    tenant_id,
                    created_at_dt,
                )
            return UserRecord(
                id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id
            )

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, password_hash, role, tenant_id, created_at),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)
        return UserRecord(
            id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id
        )

    async def register_user(
        self, username: str, password: str, role: str = "user", tenant_id: str = "default"
    ) -> UserRecord:
        return await self.create_user(
            username=username, role=role, password=password, tenant_id=tenant_id
        )

    async def authenticate_user(self, username: str, password: str) -> UserRecord | None:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, password_hash, role, created_at, tenant_id FROM users WHERE username=$1",
                    username,
                )
            if not row or not row["password_hash"]:
                return None
            if not _verify_password(password, str(row["password_hash"])):
                return None
            return UserRecord(
                id=str(row["id"]),
                username=str(row["username"]),
                role=str(row["role"]),
                created_at=str(row["created_at"]),
                tenant_id=str(
                    row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
                ),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row | None:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, password_hash, role, created_at, tenant_id FROM users WHERE username=?",
                (username,),
            )
            return _sqlite_fetchone(cur)

        row = await self._run_sqlite_op(_run)
        if not row or not row["password_hash"]:
            return None
        if not _verify_password(password, str(row["password_hash"])):
            return None
        return UserRecord(
            id=str(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
            tenant_id=str(
                row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
            ),
        )

    async def _get_user_by_id(self, user_id: str) -> UserRecord | None:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=$1",
                    user_id,
                )
            if not row:
                return None
            return UserRecord(
                id=str(row["id"]),
                username=str(row["username"]),
                role=str(row["role"]),
                created_at=str(row["created_at"]),
                tenant_id=str(
                    row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
                ),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row | None:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=?",
                (user_id,),
            )
            return _sqlite_fetchone(cur)

        row = await self._run_sqlite_op(_run)
        if not row:
            return None
        return UserRecord(
            id=str(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
            tenant_id=str(
                row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
            ),
        )

    async def ensure_user_id(
        self,
        user_id: str,
        username: str | None = None,
        role: str = "user",
        tenant_id: str = "default",
    ) -> UserRecord:
        """Belirli `user_id` için kullanıcı kaydının varlığını garanti eder."""
        existing = await self._get_user_by_id(user_id)
        if existing:
            return existing

        created_at_dt = datetime.now(UTC)
        created_at = created_at_dt.isoformat()
        normalized_username = str(username or user_id).strip() or str(user_id)
        normalized_role = str(role or "user").strip() or "user"
        normalized_tenant_id = str(tenant_id or "default").strip() or "default"

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at) VALUES ($1, $2, $3, $4, $5, $6)",
                    user_id,
                    normalized_username,
                    None,
                    normalized_role,
                    normalized_tenant_id,
                    created_at_dt,
                )
            return UserRecord(
                id=user_id,
                username=normalized_username,
                role=normalized_role,
                created_at=created_at,
                tenant_id=normalized_tenant_id,
            )

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    normalized_username,
                    None,
                    normalized_role,
                    normalized_tenant_id,
                    created_at,
                ),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)
        return UserRecord(
            id=user_id,
            username=normalized_username,
            role=normalized_role,
            created_at=created_at,
            tenant_id=normalized_tenant_id,
        )

    async def create_auth_token(
        self,
        user_id: str,
        ttl_days: int | None = None,
        role: str | None = None,
        username: str | None = None,
        tenant_id: str | None = None,
    ) -> AuthTokenRecord:
        created_at = _utc_now_iso()
        effective_ttl_days = (
            ttl_days if ttl_days is not None else int(getattr(self.cfg, "JWT_TTL_DAYS", 7) or 7)
        )
        ttl = max(1, int(effective_ttl_days or 1))
        expires_at = _expires_in(ttl)

        resolved_role = (role or "").strip() or "user"
        resolved_username = (username or "").strip()
        resolved_tenant_id = (tenant_id or "default").strip() or "default"

        payload = {
            "sub": user_id,
            "role": resolved_role,
            "username": resolved_username,
            "tenant_id": resolved_tenant_id,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(days=ttl)).timestamp()),
        }
        secret_key = str(getattr(self.cfg, "JWT_SECRET_KEY", "") or "sidar-dev-secret")
        algorithm = str(getattr(self.cfg, "JWT_ALGORITHM", "HS256") or "HS256")
        token = jwt.encode(payload, secret_key, algorithm=algorithm)
        return AuthTokenRecord(
            token=token, user_id=user_id, expires_at=expires_at, created_at=created_at
        )

    def verify_auth_token(self, token: str) -> UserRecord | None:
        try:
            secret_key = str(getattr(self.cfg, "JWT_SECRET_KEY", "") or "sidar-dev-secret")
            algorithm = str(getattr(self.cfg, "JWT_ALGORITHM", "HS256") or "HS256")
            payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        except jwt.PyJWTError:
            return None

        user_id = str(payload.get("sub", "") or "").strip()
        role = str(payload.get("role", "") or "").strip()
        username = str(payload.get("username", "") or "").strip()
        tenant_id = str(payload.get("tenant_id", "default") or "default").strip() or "default"
        if not user_id or not role:
            return None

        return UserRecord(
            id=user_id,
            username=username,
            role=role,
            created_at="",
            tenant_id=tenant_id,
        )

    async def get_user_by_token(self, token: str) -> UserRecord | None:
        """Geriye dönük uyumluluk: JWT doğrular, mümkünse kullanıcı kaydını da yükler."""
        jwt_user = self.verify_auth_token(token)
        if not jwt_user:
            return None

        db_user = await self._get_user_by_id(jwt_user.id)
        return db_user or jwt_user

    async def list_access_policies(
        self, user_id: str, tenant_id: str | None = None
    ) -> list[AccessPolicyRecord]:
        effective_tenant = (tenant_id or "").strip()
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at "
                "FROM access_policies WHERE user_id=$1"
            )
            args: list[Any] = [user_id]
            if effective_tenant:
                query += " AND tenant_id=$2"
                args.append(effective_tenant)
            query += " ORDER BY resource_type, action, resource_id"
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [
                AccessPolicyRecord(
                    id=int(r["id"]),
                    user_id=str(r["user_id"]),
                    tenant_id=str(r["tenant_id"]),
                    resource_type=str(r["resource_type"]),
                    resource_id=str(r["resource_id"]),
                    action=str(r["action"]),
                    effect=str(r["effect"]),
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                for r in rows
            ]

        assert self._sqlite_conn is not None

        def _run() -> list[sqlite3.Row]:
            assert self._sqlite_conn is not None
            if effective_tenant:
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at
                    FROM access_policies
                    WHERE user_id=? AND tenant_id=?
                    ORDER BY resource_type, action, resource_id
                    """,
                    (user_id, effective_tenant),
                )
            else:
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at
                    FROM access_policies
                    WHERE user_id=?
                    ORDER BY resource_type, action, resource_id
                    """,
                    (user_id,),
                )
            return cur.fetchall()

        rows = await self._run_sqlite_op(_run, write=False)
        return [
            AccessPolicyRecord(
                id=int(r["id"]),
                user_id=str(r["user_id"]),
                tenant_id=str(r["tenant_id"]),
                resource_type=str(r["resource_type"]),
                resource_id=str(r["resource_id"]),
                action=str(r["action"]),
                effect=str(r["effect"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    async def upsert_access_policy(
        self,
        *,
        user_id: str,
        tenant_id: str = "default",
        resource_type: str,
        resource_id: str = "*",
        action: str,
        effect: str = "allow",
    ) -> None:
        now_dt, now = _utc_now_pair()
        tenant = (tenant_id or "default").strip() or "default"
        r_type = (resource_type or "").strip().lower()
        r_id = (resource_id or "*").strip() or "*"
        act = (action or "").strip().lower()
        eff = (effect or "allow").strip().lower()
        if eff not in {"allow", "deny"}:
            raise ValueError("effect must be allow or deny")
        if not r_type or not act:
            raise ValueError("resource_type and action are required")

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO access_policies (user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                    ON CONFLICT (user_id, tenant_id, resource_type, resource_id, action)
                    DO UPDATE SET effect=EXCLUDED.effect, updated_at=EXCLUDED.updated_at
                    """,
                    user_id,
                    tenant,
                    r_type,
                    r_id,
                    act,
                    eff,
                    now_dt,
                )
            return

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                """
                INSERT INTO access_policies (user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id, resource_type, resource_id, action)
                DO UPDATE SET effect=excluded.effect, updated_at=excluded.updated_at
                """,
                (user_id, tenant, r_type, r_id, act, eff, now, now),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def check_access_policy(
        self,
        *,
        user_id: str,
        tenant_id: str = "default",
        resource_type: str,
        action: str,
        resource_id: str = "*",
    ) -> bool:
        tenant = (tenant_id or "default").strip() or "default"
        r_type = (resource_type or "").strip().lower()
        act = (action or "").strip().lower()
        r_id = (resource_id or "*").strip() or "*"
        if not user_id or not r_type or not act:
            return False

        policies = await self.list_access_policies(user_id=user_id, tenant_id=tenant)
        if not policies and tenant != "default":
            policies = await self.list_access_policies(user_id=user_id, tenant_id="default")

        def _match(spec: AccessPolicyRecord) -> bool:
            return (
                spec.resource_type == r_type
                and spec.action == act
                and (spec.resource_id == "*" or spec.resource_id == r_id)
            )

        matched = [p for p in policies if _match(p)]
        matched.sort(key=lambda p: 0 if p.resource_id == r_id else 1)
        if not matched:
            return False
        if any(p.effect == "deny" for p in matched):
            return False
        return any(p.effect == "allow" for p in matched)

    async def record_audit_log(
        self,
        *,
        user_id: str = "",
        tenant_id: str = "default",
        action: str,
        resource: str,
        ip_address: str,
        allowed: bool,
        timestamp: str | None = None,
    ) -> None:
        await db_audit.record_audit_log(
            self,
            record_cls=AuditLogRecord,
            parse_iso_datetime=_parse_iso_datetime,
            utc_now_iso=_utc_now_iso,
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            resource=resource,
            ip_address=ip_address,
            allowed=allowed,
            timestamp=timestamp,
        )

    async def list_audit_logs(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        return await db_audit.list_audit_logs(
            self,
            record_cls=AuditLogRecord,
            user_id=user_id,
            tenant_id=tenant_id,
            limit=limit,
        )

    async def upsert_marketing_campaign(
        self,
        *,
        tenant_id: str = "default",
        name: str,
        channel: str = "",
        objective: str = "",
        status: str = "draft",
        owner_user_id: str = "",
        budget: float = 0.0,
        metadata: dict[str, Any] | None = None,
        campaign_id: int | None = None,
    ) -> MarketingCampaignRecord:
        tenant = (tenant_id or "default").strip() or "default"
        campaign_name = (name or "").strip()
        if not campaign_name:
            raise ValueError("campaign name is required")
        now_dt, now = _utc_now_pair()
        normalized_status = (status or "draft").strip().lower() or "draft"
        metadata_json = _json_dumps(metadata or {})
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                if campaign_id:
                    row = await conn.fetchrow(
                        """
                        UPDATE marketing_campaigns
                        SET tenant_id=$2, name=$3, channel=$4, objective=$5, status=$6,
                            owner_user_id=$7, budget=$8, metadata_json=$9::jsonb, updated_at=$10
                        WHERE id=$1
                        RETURNING id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                        """,
                        int(campaign_id),
                        tenant,
                        campaign_name,
                        (channel or "").strip(),
                        (objective or "").strip(),
                        normalized_status,
                        (owner_user_id or "").strip(),
                        float(budget or 0.0),
                        metadata_json,
                        now_dt,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO marketing_campaigns (tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $9)
                        RETURNING id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                        """,
                        tenant,
                        campaign_name,
                        (channel or "").strip(),
                        (objective or "").strip(),
                        normalized_status,
                        (owner_user_id or "").strip(),
                        float(budget or 0.0),
                        metadata_json,
                        now_dt,
                    )
            if row is None:
                raise ValueError("campaign not found")
            return MarketingCampaignRecord(
                id=int(row["id"]),
                tenant_id=str(row["tenant_id"]),
                name=str(row["name"]),
                channel=str(row["channel"]),
                objective=str(row["objective"]),
                status=str(row["status"]),
                owner_user_id=str(row["owner_user_id"]),
                budget=float(row["budget"] or 0.0),
                metadata_json=str(row["metadata_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            if campaign_id:
                self._sqlite_conn.execute(
                    """
                    UPDATE marketing_campaigns
                    SET tenant_id=?, name=?, channel=?, objective=?, status=?, owner_user_id=?, budget=?, metadata_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        tenant,
                        campaign_name,
                        (channel or "").strip(),
                        (objective or "").strip(),
                        normalized_status,
                        (owner_user_id or "").strip(),
                        float(budget or 0.0),
                        metadata_json,
                        now,
                        int(campaign_id),
                    ),
                )
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                    FROM marketing_campaigns WHERE id=?
                    """,
                    (int(campaign_id),),
                )
            else:
                cur = self._sqlite_conn.execute(
                    """
                    INSERT INTO marketing_campaigns (tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant,
                        campaign_name,
                        (channel or "").strip(),
                        (objective or "").strip(),
                        normalized_status,
                        (owner_user_id or "").strip(),
                        float(budget or 0.0),
                        metadata_json,
                        now,
                        now,
                    ),
                )
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                    FROM marketing_campaigns WHERE id=?
                    """,
                    (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
                )
            row = _sqlite_fetchone(cur)
            self._sqlite_conn.commit()
            if row is None:
                raise ValueError("campaign not found")
            return row

        row = await self._run_sqlite_op(_run)
        return MarketingCampaignRecord(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            name=str(row["name"]),
            channel=str(row["channel"]),
            objective=str(row["objective"]),
            status=str(row["status"]),
            owner_user_id=str(row["owner_user_id"]),
            budget=float(row["budget"] or 0.0),
            metadata_json=str(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def list_marketing_campaigns(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[MarketingCampaignRecord]:
        tenant = (tenant_id or "default").strip() or "default"
        normalized_status = (status or "").strip().lower() or None
        max_items = max(1, min(int(limit or 100), 500))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at "
                "FROM marketing_campaigns WHERE tenant_id=$1"
            )
            args: list[Any] = [tenant]
            if normalized_status:
                query += " AND status=$2"
                args.append(normalized_status)
            query += f" ORDER BY updated_at DESC LIMIT ${len(args) + 1}"
            args.append(max_items)
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
        else:
            assert self._sqlite_conn is not None

            def _run() -> list[sqlite3.Row]:
                assert self._sqlite_conn is not None
                if normalized_status:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                        FROM marketing_campaigns
                        WHERE tenant_id=? AND status=?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (tenant, normalized_status, max_items),
                    )
                else:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                        FROM marketing_campaigns
                        WHERE tenant_id=?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (tenant, max_items),
                    )
                return cur.fetchall()

            rows = await self._run_sqlite_op(_run, write=False)
        return [
            MarketingCampaignRecord(
                id=int(row["id"]),
                tenant_id=str(row["tenant_id"]),
                name=str(row["name"]),
                channel=str(row["channel"]),
                objective=str(row["objective"]),
                status=str(row["status"]),
                owner_user_id=str(row["owner_user_id"]),
                budget=float(row["budget"] or 0.0),
                metadata_json=str(row["metadata_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    async def add_content_asset(
        self,
        *,
        campaign_id: int,
        tenant_id: str = "default",
        asset_type: str,
        title: str,
        content: str,
        channel: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ContentAssetRecord:
        now_dt, now = _utc_now_pair()
        tenant = (tenant_id or "default").strip() or "default"
        asset_kind = (asset_type or "").strip().lower()
        asset_title = (title or "").strip()
        asset_content = str(content or "").strip()
        if not asset_kind or not asset_title or not asset_content:
            raise ValueError("asset_type, title and content are required")
        metadata_json = _json_dumps(metadata or {})
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO content_assets (campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $8)
                    RETURNING id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                    """,
                    int(campaign_id),
                    tenant,
                    asset_kind,
                    asset_title,
                    asset_content,
                    (channel or "").strip(),
                    metadata_json,
                    now_dt,
                )
            return ContentAssetRecord(
                id=int(row["id"]),
                campaign_id=int(row["campaign_id"]),
                tenant_id=str(row["tenant_id"]),
                asset_type=str(row["asset_type"]),
                title=str(row["title"]),
                content=str(row["content"]),
                channel=str(row["channel"]),
                metadata_json=str(row["metadata_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                """
                INSERT INTO content_assets (campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(campaign_id),
                    tenant,
                    asset_kind,
                    asset_title,
                    asset_content,
                    (channel or "").strip(),
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = _sqlite_fetchone(
                self._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                    FROM content_assets WHERE id=?
                    """,
                    (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
                )
            )
            self._sqlite_conn.commit()
            assert row is not None
            return row

        row = await self._run_sqlite_op(_run)
        return ContentAssetRecord(
            id=int(row["id"]),
            campaign_id=int(row["campaign_id"]),
            tenant_id=str(row["tenant_id"]),
            asset_type=str(row["asset_type"]),
            title=str(row["title"]),
            content=str(row["content"]),
            channel=str(row["channel"]),
            metadata_json=str(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def list_content_assets(
        self,
        *,
        tenant_id: str,
        campaign_id: int | None = None,
        limit: int = 100,
    ) -> list[ContentAssetRecord]:
        tenant = (tenant_id or "default").strip() or "default"
        max_items = max(1, min(int(limit or 100), 500))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at "
                "FROM content_assets WHERE tenant_id=$1"
            )
            args: list[Any] = [tenant]
            if campaign_id is not None:
                query += " AND campaign_id=$2"
                args.append(int(campaign_id))
            query += f" ORDER BY created_at DESC LIMIT ${len(args) + 1}"
            args.append(max_items)
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
        else:
            assert self._sqlite_conn is not None

            def _run() -> list[sqlite3.Row]:
                assert self._sqlite_conn is not None
                if campaign_id is not None:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                        FROM content_assets
                        WHERE tenant_id=? AND campaign_id=?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (tenant, int(campaign_id), max_items),
                    )
                else:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                        FROM content_assets
                        WHERE tenant_id=?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (tenant, max_items),
                    )
                return cur.fetchall()

            rows = await self._run_sqlite_op(_run, write=False)
        return [
            ContentAssetRecord(
                id=int(row["id"]),
                campaign_id=int(row["campaign_id"]),
                tenant_id=str(row["tenant_id"]),
                asset_type=str(row["asset_type"]),
                title=str(row["title"]),
                content=str(row["content"]),
                channel=str(row["channel"]),
                metadata_json=str(row["metadata_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    async def add_operation_checklist(
        self,
        *,
        tenant_id: str = "default",
        title: str,
        items: list[Any],
        status: str = "pending",
        owner_user_id: str = "",
        campaign_id: int | None = None,
    ) -> OperationChecklistRecord:
        tenant = (tenant_id or "default").strip() or "default"
        checklist_title = (title or "").strip()
        if not checklist_title:
            raise ValueError("title is required")
        normalized_items: list[Any] = []
        for item in list(items or []):
            if isinstance(item, dict):
                normalized_dict = {
                    str(key).strip(): value for key, value in item.items() if str(key).strip()
                }
                if normalized_dict:
                    normalized_items.append(normalized_dict)
                continue
            text = str(item).strip()
            if text:
                normalized_items.append(text)
        now_dt, now = _utc_now_pair()
        items_json = _json_dumps(normalized_items)
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO operation_checklists (campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $7)
                    RETURNING id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                    """,
                    int(campaign_id) if campaign_id is not None else None,
                    tenant,
                    checklist_title,
                    items_json,
                    (status or "pending").strip().lower() or "pending",
                    (owner_user_id or "").strip(),
                    now_dt,
                )
            return OperationChecklistRecord(
                id=int(row["id"]),
                campaign_id=None if row["campaign_id"] is None else int(row["campaign_id"]),
                tenant_id=str(row["tenant_id"]),
                title=str(row["title"]),
                items_json=str(row["items_json"]),
                status=str(row["status"]),
                owner_user_id=str(row["owner_user_id"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                """
                INSERT INTO operation_checklists (campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(campaign_id) if campaign_id is not None else None,
                    tenant,
                    checklist_title,
                    items_json,
                    (status or "pending").strip().lower() or "pending",
                    (owner_user_id or "").strip(),
                    now,
                    now,
                ),
            )
            row = _sqlite_fetchone(
                self._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                    FROM operation_checklists WHERE id=?
                    """,
                    (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
                )
            )
            self._sqlite_conn.commit()
            assert row is not None
            return row

        row = await self._run_sqlite_op(_run)
        return OperationChecklistRecord(
            id=int(row["id"]),
            campaign_id=None if row["campaign_id"] is None else int(row["campaign_id"]),
            tenant_id=str(row["tenant_id"]),
            title=str(row["title"]),
            items_json=str(row["items_json"]),
            status=str(row["status"]),
            owner_user_id=str(row["owner_user_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def list_operation_checklists(
        self,
        *,
        tenant_id: str,
        campaign_id: int | None = None,
        limit: int = 100,
    ) -> list[OperationChecklistRecord]:
        tenant = (tenant_id or "default").strip() or "default"
        max_items = max(1, min(int(limit or 100), 500))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at "
                "FROM operation_checklists WHERE tenant_id=$1"
            )
            args: list[Any] = [tenant]
            if campaign_id is not None:
                query += " AND campaign_id=$2"
                args.append(int(campaign_id))
            query += f" ORDER BY created_at DESC LIMIT ${len(args) + 1}"
            args.append(max_items)
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
        else:
            assert self._sqlite_conn is not None

            def _run() -> list[sqlite3.Row]:
                assert self._sqlite_conn is not None
                if campaign_id is not None:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                        FROM operation_checklists
                        WHERE tenant_id=? AND campaign_id=?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (tenant, int(campaign_id), max_items),
                    )
                else:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                        FROM operation_checklists
                        WHERE tenant_id=?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (tenant, max_items),
                    )
                return cur.fetchall()

            rows = await self._run_sqlite_op(_run, write=False)
        return [
            OperationChecklistRecord(
                id=int(row["id"]),
                campaign_id=None if row["campaign_id"] is None else int(row["campaign_id"]),
                tenant_id=str(row["tenant_id"]),
                title=str(row["title"]),
                items_json=str(row["items_json"]),
                status=str(row["status"]),
                owner_user_id=str(row["owner_user_id"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    async def create_coverage_task(
        self,
        *,
        tenant_id: str = "default",
        requester_role: str = "coverage",
        command: str,
        pytest_output: str,
        status: str = "pending_review",
        target_path: str = "",
        suggested_test_path: str = "",
        review_payload_json: str = "{}",
    ) -> CoverageTaskRecord:
        tenant = (tenant_id or "default").strip() or "default"
        now_dt, now = _utc_now_pair()
        if not str(command or "").strip():
            raise ValueError("command is required")
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO coverage_tasks (
                        tenant_id, requester_role, command, pytest_output, status,
                        target_path, suggested_test_path, review_payload_json, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $9)
                    RETURNING id, tenant_id, requester_role, command, pytest_output, status,
                              target_path, suggested_test_path, review_payload_json, created_at, updated_at
                    """,
                    tenant,
                    str(requester_role or "coverage"),
                    str(command),
                    str(pytest_output or ""),
                    str(status or "pending_review"),
                    str(target_path or ""),
                    str(suggested_test_path or ""),
                    str(review_payload_json or "{}"),
                    now_dt,
                )
            return CoverageTaskRecord(
                id=int(row["id"]),
                tenant_id=str(row["tenant_id"]),
                requester_role=str(row["requester_role"]),
                command=str(row["command"]),
                pytest_output=str(row["pytest_output"]),
                status=str(row["status"]),
                target_path=str(row["target_path"]),
                suggested_test_path=str(row["suggested_test_path"]),
                review_payload_json=str(row["review_payload_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                """
                INSERT INTO coverage_tasks (
                    tenant_id, requester_role, command, pytest_output, status,
                    target_path, suggested_test_path, review_payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    str(requester_role or "coverage"),
                    str(command),
                    str(pytest_output or ""),
                    str(status or "pending_review"),
                    str(target_path or ""),
                    str(suggested_test_path or ""),
                    str(review_payload_json or "{}"),
                    now,
                    now,
                ),
            )
            row = _sqlite_fetchone(
                self._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, requester_role, command, pytest_output, status,
                           target_path, suggested_test_path, review_payload_json, created_at, updated_at
                    FROM coverage_tasks WHERE id=?
                    """,
                    (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
                )
            )
            self._sqlite_conn.commit()
            assert row is not None
            return row

        row = await self._run_sqlite_op(_run)
        return CoverageTaskRecord(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            requester_role=str(row["requester_role"]),
            command=str(row["command"]),
            pytest_output=str(row["pytest_output"]),
            status=str(row["status"]),
            target_path=str(row["target_path"]),
            suggested_test_path=str(row["suggested_test_path"]),
            review_payload_json=str(row["review_payload_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def add_coverage_finding(
        self,
        *,
        task_id: int,
        finding_type: str,
        target_path: str,
        summary: str,
        severity: str = "medium",
        details: dict[str, Any] | None = None,
    ) -> CoverageFindingRecord:
        now_dt, now = _utc_now_pair()
        if not str(finding_type or "").strip() or not str(summary or "").strip():
            raise ValueError("finding_type and summary are required")
        details_json = _json_dumps(details or {})
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO coverage_findings (task_id, finding_type, target_path, summary, severity, details_json, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    RETURNING id, task_id, finding_type, target_path, summary, severity, details_json, created_at
                    """,
                    int(task_id),
                    str(finding_type),
                    str(target_path or ""),
                    str(summary),
                    str(severity or "medium"),
                    details_json,
                    now_dt,
                )
            return CoverageFindingRecord(
                id=int(row["id"]),
                task_id=int(row["task_id"]),
                finding_type=str(row["finding_type"]),
                target_path=str(row["target_path"]),
                summary=str(row["summary"]),
                severity=str(row["severity"]),
                details_json=str(row["details_json"]),
                created_at=str(row["created_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                """
                INSERT INTO coverage_findings (task_id, finding_type, target_path, summary, severity, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    str(finding_type),
                    str(target_path or ""),
                    str(summary),
                    str(severity or "medium"),
                    details_json,
                    now,
                ),
            )
            row = _sqlite_fetchone(
                self._sqlite_conn.execute(
                    """
                    SELECT id, task_id, finding_type, target_path, summary, severity, details_json, created_at
                    FROM coverage_findings WHERE id=?
                    """,
                    (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
                )
            )
            self._sqlite_conn.commit()
            assert row is not None
            return row

        row = await self._run_sqlite_op(_run)
        return CoverageFindingRecord(
            id=int(row["id"]),
            task_id=int(row["task_id"]),
            finding_type=str(row["finding_type"]),
            target_path=str(row["target_path"]),
            summary=str(row["summary"]),
            severity=str(row["severity"]),
            details_json=str(row["details_json"]),
            created_at=str(row["created_at"]),
        )

    async def list_coverage_tasks(
        self,
        *,
        tenant_id: str = "default",
        status: str | None = None,
        limit: int = 100,
    ) -> list[CoverageTaskRecord]:
        tenant = (tenant_id or "default").strip() or "default"
        normalized_status = (status or "").strip() or None
        max_items = max(1, min(int(limit or 100), 500))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, tenant_id, requester_role, command, pytest_output, status, "
                "target_path, suggested_test_path, review_payload_json, created_at, updated_at "
                "FROM coverage_tasks WHERE tenant_id=$1"
            )
            args: list[Any] = [tenant]
            if normalized_status:
                query += " AND status=$2"
                args.append(normalized_status)
            query += f" ORDER BY updated_at DESC LIMIT ${len(args) + 1}"
            args.append(max_items)
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
        else:
            assert self._sqlite_conn is not None

            def _run() -> list[sqlite3.Row]:
                assert self._sqlite_conn is not None
                if normalized_status:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, tenant_id, requester_role, command, pytest_output, status,
                               target_path, suggested_test_path, review_payload_json, created_at, updated_at
                        FROM coverage_tasks
                        WHERE tenant_id=? AND status=?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (tenant, normalized_status, max_items),
                    )
                else:
                    cur = self._sqlite_conn.execute(
                        """
                        SELECT id, tenant_id, requester_role, command, pytest_output, status,
                               target_path, suggested_test_path, review_payload_json, created_at, updated_at
                        FROM coverage_tasks
                        WHERE tenant_id=?
                        ORDER BY updated_at DESC
                        LIMIT ?
                        """,
                        (tenant, max_items),
                    )
                return cur.fetchall()

            rows = await self._run_sqlite_op(_run, write=False)
        return [
            CoverageTaskRecord(
                id=int(row["id"]),
                tenant_id=str(row["tenant_id"]),
                requester_role=str(row["requester_role"]),
                command=str(row["command"]),
                pytest_output=str(row["pytest_output"]),
                status=str(row["status"]),
                target_path=str(row["target_path"]),
                suggested_test_path=str(row["suggested_test_path"]),
                review_payload_json=str(row["review_payload_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    async def upsert_user_quota(
        self, user_id: str, daily_token_limit: int = 0, daily_request_limit: int = 0
    ) -> None:
        tokens = max(0, int(daily_token_limit or 0))
        requests = max(0, int(daily_request_limit or 0))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_quotas (user_id, daily_token_limit, daily_request_limit)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id)
                    DO UPDATE SET daily_token_limit=EXCLUDED.daily_token_limit,
                                  daily_request_limit=EXCLUDED.daily_request_limit
                    """,
                    user_id,
                    tokens,
                    requests,
                )
            return

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                """
                INSERT INTO user_quotas (user_id, daily_token_limit, daily_request_limit)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    daily_token_limit=excluded.daily_token_limit,
                    daily_request_limit=excluded.daily_request_limit
                """,
                (user_id, tokens, requests),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def record_provider_usage_daily(
        self, user_id: str, provider: str, tokens_used: int, requests_inc: int = 1
    ) -> None:
        await db_metrics.record_provider_usage_daily(
            self, user_id, provider, tokens_used, requests_inc
        )

    async def get_user_quota_status(self, user_id: str, provider: str) -> dict[str, int | bool]:
        return await db_metrics.get_user_quota_status(self, user_id, provider, _sqlite_fetchone)

    async def list_users_with_quotas(self) -> list[dict[str, Any]]:
        """Tüm kullanıcıları kota bilgileriyle birlikte döndürür."""
        return await db_metrics.list_users_with_quotas(self)

    async def get_admin_stats(self) -> dict[str, Any]:
        return await db_metrics.get_admin_stats(self, _sqlite_fetchone)

    async def create_session(self, user_id: str, title: str) -> SessionRecord:
        return await db_sessions.create_session(self, SessionRecord, _new_entity_id, user_id, title)

    async def add_message(
        self, session_id: str, role: str, content: str, tokens_used: int = 0
    ) -> MessageRecord:
        return await db_sessions.add_message(
            self, MessageRecord, session_id, role, content, tokens_used
        )

    async def add_messages_bulk(self, items: list[dict[str, object]]) -> int:
        """Birden çok mesajı tek transaction içinde yazar ve eklenen satır sayısını döndürür."""
        return await db_sessions.add_messages_bulk(self, items)

    async def get_session_messages(self, session_id: str) -> list[MessageRecord]:
        return await db_sessions.get_session_messages(self, session_id)

    async def get_messages_for_sessions(
        self, session_ids: list[str]
    ) -> dict[str, list[MessageRecord]]:
        """Birden çok oturumun mesajlarını tek sorguda getirir."""
        return await db_sessions.get_messages_for_sessions(self, session_ids)

    async def replace_session_messages(
        self, session_id: str, messages: list[dict[str, object]]
    ) -> int:
        """Bir oturumun mesajlarını atomik olarak yenileriyle değiştirir."""
        return await db_sessions.replace_session_messages(self, session_id, messages)
