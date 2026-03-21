"""Sidar kalıcı veri katmanı (v3.0 hazırlık): kullanıcı/oturum/mesaj şemaları."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import uuid
import secrets
import jwt
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from config import Config


@dataclass
class UserRecord:
    id: str
    username: str
    role: str
    created_at: str
    tenant_id: str = "default"


@dataclass
class AuthTokenRecord:
    token: str
    user_id: str
    expires_at: str
    created_at: str


@dataclass
class SessionRecord:
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    tokens_used: int
    created_at: str


@dataclass
class AccessPolicyRecord:
    id: int
    user_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str
    effect: str
    created_at: str
    updated_at: str


@dataclass
class PromptRecord:
    id: int
    role_name: str
    prompt_text: str
    version: int
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class AuditLogRecord:
    id: int
    user_id: str
    tenant_id: str
    action: str
    resource: str
    ip_address: str
    allowed: bool
    timestamp: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    real_salt = salt or secrets.token_hex(16)
    # OWASP güncel rehberleriyle uyumlu iş faktörü (kurumsal dağıtım varsayılanı).
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), real_salt.encode("utf-8"), 600000)
    return f"pbkdf2_sha256${real_salt}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected_hex = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = _hash_password(password, salt=salt)
    return secrets.compare_digest(actual, encoded)


def _expires_in(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _quote_sql_identifier(identifier: str) -> str:
    value = (identifier or "").strip()
    if not value:
        raise ValueError("SQL identifier cannot be empty")
    if not value.replace("_", "").isalnum() or not (value[0].isalpha() or value[0] == "_"):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return f'"{value}"'


class Database:
    """Asenkron veritabanı erişim katmanı.

    Not:
    - `DATABASE_URL` yoksa otomatik SQLite fallback: `sqlite+aiosqlite:///data/sidar.db`
    - PostgreSQL URL (postgresql:// / postgresql+asyncpg://) verildiğinde `asyncpg`
      kullanılır; paket yoksa anlaşılır hata döndürür.
    """

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.cfg = cfg or Config()
        self.database_url = (getattr(self.cfg, "DATABASE_URL", "") or "").strip() or "sqlite+aiosqlite:///data/sidar.db"
        self.pool_size = int(getattr(self.cfg, "DB_POOL_SIZE", 5) or 5)
        self.schema_version_table = str(getattr(self.cfg, "DB_SCHEMA_VERSION_TABLE", "schema_versions") or "schema_versions")
        self._schema_version_table_quoted = _quote_sql_identifier(self.schema_version_table)
        self.target_schema_version = int(getattr(self.cfg, "DB_SCHEMA_TARGET_VERSION", 1) or 1)

        self._backend = "sqlite"
        self._sqlite_path: Optional[Path] = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._sqlite_lock: Optional[asyncio.Lock] = None

        self._pg_pool = None

        self._configure_backend()

    def _configure_backend(self) -> None:
        lowered = self.database_url.lower()
        if lowered.startswith("postgresql://") or lowered.startswith("postgresql+asyncpg://"):
            self._backend = "postgresql"
            return

        self._backend = "sqlite"
        prefix = "sqlite+aiosqlite:///"
        raw_path = self.database_url
        if lowered.startswith(prefix):
            raw_path = self.database_url[len(prefix):]
        elif lowered.startswith("sqlite:///"):
            raw_path = self.database_url[len("sqlite:///"):]

        path = Path(raw_path)
        if not path.is_absolute():
            base_dir = Path(getattr(self.cfg, "BASE_DIR", Path.cwd()))
            path = base_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_path = path

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
            conn.execute("PRAGMA busy_timeout = 10000;")
            return conn

        self._sqlite_conn = await asyncio.to_thread(_open)
        self._sqlite_lock = asyncio.Lock()

    async def _run_sqlite_op(self, operation):
        """SQLite işlemlerini tek bağlantı üzerinde sıralı çalıştır (thread-safe).
        initialize() çağrılmadan bu metot kullanılmamalıdır."""
        if self._sqlite_conn is None:
            raise RuntimeError("SQLite bağlantısı başlatılmadı.")
        if self._sqlite_lock is None:
            self._sqlite_lock = asyncio.Lock()
        async with self._sqlite_lock:
            return await asyncio.to_thread(operation)

    async def _connect_postgresql(self) -> None:
        if self._pg_pool is not None:
            return
        try:
            import asyncpg
        except Exception as exc:  # pragma: no cover - paket opsiyonel
            raise RuntimeError("PostgreSQL için asyncpg bağımlılığı gerekli.") from exc

        dsn = self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pg_pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=max(1, self.pool_size))

    async def close(self) -> None:
        if self._sqlite_conn is not None:
            conn = self._sqlite_conn
            self._sqlite_conn = None
            self._sqlite_lock = None
            await asyncio.to_thread(conn.close)

        if self._pg_pool is not None:
            pool = self._pg_pool
            self._pg_pool = None
            await pool.close()

    async def init_schema(self) -> None:
        if self._backend == "postgresql":
            await self._init_schema_postgresql()
            await self._ensure_access_control_schema_postgresql()
            await self._ensure_audit_log_schema_postgresql()
            await self._ensure_schema_version_postgresql()
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
                self._sqlite_conn.execute("ALTER TABLE users ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
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
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_policies (
                    id BIGSERIAL PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON access_policies(user_id, tenant_id, resource_type, action)")

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
        """

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.executescript(schema_sql)
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def _init_schema_postgresql(self) -> None:
        assert self._pg_pool is not None
        queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TIMESTAMPTZ NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                daily_token_limit INTEGER NOT NULL DEFAULT 0,
                daily_request_limit INTEGER NOT NULL DEFAULT 0
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS provider_usage_daily (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                usage_date DATE NOT NULL,
                requests_used INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, provider, usage_date)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);",
            "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_provider_usage_daily_user_id ON provider_usage_daily(user_id);",
            """
            CREATE TABLE IF NOT EXISTS access_policies (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '*',
                action TEXT NOT NULL,
                effect TEXT NOT NULL DEFAULT 'allow',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(user_id, tenant_id, resource_type, resource_id, action)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON access_policies(user_id, tenant_id, resource_type, action);",
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
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);",

            """
            CREATE TABLE IF NOT EXISTS prompt_registry (
                id BIGSERIAL PRIMARY KEY,
                role_name TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(role_name, version)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_prompt_registry_role_active ON prompt_registry(role_name, is_active);",
        ]
        async with self._pg_pool.acquire() as conn:
            for q in queries:
                await conn.execute(q)


    async def ensure_default_prompt_registry(self) -> None:
        import importlib.util as _importlib_util
        import logging as _log

        definitions_path = Path(__file__).resolve().parents[1] / "agent" / "definitions.py"
        spec = _importlib_util.spec_from_file_location("sidar_agent_definitions", definitions_path)
        default_prompt = ""
        if spec and spec.loader:
            module = _importlib_util.module_from_spec(spec)
            spec.loader.exec_module(module)
            default_prompt = str(getattr(module, "SIDAR_SYSTEM_PROMPT", "") or "")

        existing = await self.get_active_prompt("system")
        if existing or not default_prompt:
            return
        try:
            await self.upsert_prompt(role_name="system", prompt_text=default_prompt, activate=True)
        except Exception as exc:  # noqa: BLE001
            _log.getLogger(__name__).warning("Varsayılan prompt kaydı oluşturulamadı: %s", exc)

    async def list_prompts(self, role_name: Optional[str] = None) -> list[PromptRecord]:
        role = (role_name or "").strip() or None
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at "
                "FROM prompt_registry"
            )
            args: tuple[Any, ...] = ()
            if role:
                query += " WHERE role_name=$1"
                args = (role,)
            query += " ORDER BY role_name ASC, version DESC"
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [
                PromptRecord(
                    id=int(r["id"]),
                    role_name=str(r["role_name"]),
                    prompt_text=str(r["prompt_text"]),
                    version=int(r["version"]),
                    is_active=bool(r["is_active"]),
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                for r in rows
            ]

        assert self._sqlite_conn is not None

        def _run() -> list[sqlite3.Row]:
            assert self._sqlite_conn is not None
            if role:
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at
                    FROM prompt_registry
                    WHERE role_name=?
                    ORDER BY role_name ASC, version DESC
                    """,
                    (role,),
                )
                return cur.fetchall()
            cur = self._sqlite_conn.execute(
                """
                SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at
                FROM prompt_registry
                ORDER BY role_name ASC, version DESC
                """
            )
            return cur.fetchall()

        rows = await self._run_sqlite_op(_run)
        return [
            PromptRecord(
                id=int(r["id"]),
                role_name=str(r["role_name"]),
                prompt_text=str(r["prompt_text"]),
                version=int(r["version"]),
                is_active=bool(int(r["is_active"])),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    async def get_active_prompt(self, role_name: str) -> Optional[PromptRecord]:
        role = (role_name or "").strip().lower()
        if not role:
            return None
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at
                    FROM prompt_registry
                    WHERE role_name=$1 AND is_active=TRUE
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    role,
                )
            if not row:
                return None
            return PromptRecord(
                id=int(row["id"]),
                role_name=str(row["role_name"]),
                prompt_text=str(row["prompt_text"]),
                version=int(row["version"]),
                is_active=bool(row["is_active"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                """
                SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at
                FROM prompt_registry
                WHERE role_name=? AND is_active=1
                ORDER BY version DESC
                LIMIT 1
                """,
                (role,),
            )
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row:
            return None
        return PromptRecord(
            id=int(row["id"]),
            role_name=str(row["role_name"]),
            prompt_text=str(row["prompt_text"]),
            version=int(row["version"]),
            is_active=bool(int(row["is_active"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def upsert_prompt(self, role_name: str, prompt_text: str, *, activate: bool = True) -> PromptRecord:
        role = (role_name or "").strip().lower()
        text = (prompt_text or "").strip()
        if not role or not text:
            raise ValueError("role_name ve prompt_text boş olamaz")

        now = _utc_now_iso()
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                current_version = await conn.fetchval(
                    "SELECT COALESCE(MAX(version), 0) FROM prompt_registry WHERE role_name=$1",
                    role,
                )
                new_version = int(current_version or 0) + 1
                if activate:
                    await conn.execute("UPDATE prompt_registry SET is_active=FALSE, updated_at=$2 WHERE role_name=$1", role, now)
                row = await conn.fetchrow(
                    """
                    INSERT INTO prompt_registry (role_name, prompt_text, version, is_active, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, role_name, prompt_text, version, is_active, created_at, updated_at
                    """,
                    role,
                    text,
                    new_version,
                    activate,
                    now,
                    now,
                )
            return PromptRecord(
                id=int(row["id"]),
                role_name=str(row["role_name"]),
                prompt_text=str(row["prompt_text"]),
                version=int(row["version"]),
                is_active=bool(row["is_active"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> sqlite3.Row:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM prompt_registry WHERE role_name=?",
                (role,),
            )
            row = cur.fetchone()
            new_version = int((row["v"] if row else 0) or 0) + 1
            if activate:
                self._sqlite_conn.execute(
                    "UPDATE prompt_registry SET is_active=0, updated_at=? WHERE role_name=?",
                    (now, role),
                )
            self._sqlite_conn.execute(
                """
                INSERT INTO prompt_registry (role_name, prompt_text, version, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (role, text, new_version, 1 if activate else 0, now, now),
            )
            self._sqlite_conn.commit()
            out = self._sqlite_conn.execute(
                """
                SELECT id, role_name, prompt_text, version, is_active, created_at, updated_at
                FROM prompt_registry WHERE role_name=? AND version=?
                """,
                (role, new_version),
            )
            fetched = out.fetchone()
            assert fetched is not None
            return fetched

        inserted = await self._run_sqlite_op(_run)
        return PromptRecord(
            id=int(inserted["id"]),
            role_name=str(inserted["role_name"]),
            prompt_text=str(inserted["prompt_text"]),
            version=int(inserted["version"]),
            is_active=bool(int(inserted["is_active"])),
            created_at=str(inserted["created_at"]),
            updated_at=str(inserted["updated_at"]),
        )

    async def activate_prompt(self, prompt_id: int) -> Optional[PromptRecord]:
        target_id = int(prompt_id)
        if target_id <= 0:
            return None

        now = _utc_now_iso()
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, role_name FROM prompt_registry WHERE id=$1",
                    target_id,
                )
                if not row:
                    return None
                role = str(row["role_name"])
                await conn.execute("UPDATE prompt_registry SET is_active=FALSE, updated_at=$2 WHERE role_name=$1", role, now)
                await conn.execute("UPDATE prompt_registry SET is_active=TRUE, updated_at=$2 WHERE id=$1", target_id, now)
            return await self.get_active_prompt(role)

        assert self._sqlite_conn is not None

        def _run() -> Optional[str]:
            assert self._sqlite_conn is not None
            row = self._sqlite_conn.execute(
                "SELECT role_name FROM prompt_registry WHERE id=?",
                (target_id,),
            ).fetchone()
            if not row:
                return None
            role = str(row["role_name"])
            self._sqlite_conn.execute(
                "UPDATE prompt_registry SET is_active=0, updated_at=? WHERE role_name=?",
                (now, role),
            )
            self._sqlite_conn.execute(
                "UPDATE prompt_registry SET is_active=1, updated_at=? WHERE id=?",
                (now, target_id),
            )
            self._sqlite_conn.commit()
            return role

        role_name = await self._run_sqlite_op(_run)
        if not role_name:
            return None
        return await self.get_active_prompt(role_name)

    async def _ensure_schema_version_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            tbl = self._schema_version_table_quoted
            self._sqlite_conn.execute(
                f"CREATE TABLE IF NOT EXISTS {tbl} (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)"
            )
            cur = self._sqlite_conn.execute(f"SELECT MAX(version) AS v FROM {tbl}")
            row = cur.fetchone()
            current = int((row["v"] if row else 0) or 0)
            if current >= self.target_schema_version:
                return
            for v in range(current + 1, self.target_schema_version + 1):
                self._sqlite_conn.execute(
                    f"INSERT INTO {tbl} (version, applied_at, description) VALUES (?, ?, ?)",
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
            current = await conn.fetchval(f"SELECT COALESCE(MAX(version), 0) FROM {tbl}")
            current = int(current or 0)
            if current >= self.target_schema_version:
                return
            for v in range(current + 1, self.target_schema_version + 1):
                await conn.execute(
                    f"INSERT INTO {tbl} (version, applied_at, description) VALUES ($1, $2, $3)",
                    v,
                    datetime.now(timezone.utc),
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
                        tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]),
                    )
            return await self.create_user(username=username, role=role)

        assert self._sqlite_conn is not None

        def _fetch() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE username=?",
                (username,),
            )
            return cur.fetchone()

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
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, title, created_at, updated_at
                    FROM sessions
                    WHERE user_id=$1
                    ORDER BY updated_at DESC
                    """,
                    user_id,
                )
            return [
                SessionRecord(
                    id=str(r["id"]),
                    user_id=str(r["user_id"]),
                    title=str(r["title"]),
                    created_at=str(r["created_at"]),
                    updated_at=str(r["updated_at"]),
                )
                for r in rows
            ]

        assert self._sqlite_conn is not None

        def _run() -> list[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            )
            return cur.fetchall()

        rows = await self._run_sqlite_op(_run)
        return [
            SessionRecord(
                id=str(r["id"]),
                user_id=str(r["user_id"]),
                title=str(r["title"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    async def load_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[SessionRecord]:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                if user_id:
                    row = await conn.fetchrow(
                        "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=$1 AND user_id=$2",
                        session_id,
                        user_id,
                    )
                else:
                    row = await conn.fetchrow(
                        "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=$1",
                        session_id,
                    )
            if not row:
                return None
            return SessionRecord(
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            if user_id:
                cur = self._sqlite_conn.execute(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=? AND user_id=?",
                    (session_id, user_id),
                )
            else:
                cur = self._sqlite_conn.execute(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=?",
                    (session_id,),
                )
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row:
            return None
        return SessionRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            title=str(row["title"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def update_session_title(self, session_id: str, title: str) -> bool:
        now = _utc_now_iso()
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE sessions SET title=$1, updated_at=$2 WHERE id=$3",
                    title,
                    now,
                    session_id,
                )
            # asyncpg "UPDATE N" veya "UPDATE 0" formatında string döndürür;
            # endswith("1") 10+ satır güncellemelerinde hatalı False verebilir.
            try:
                return int(str(result).split()[-1]) > 0
            except (ValueError, IndexError, AttributeError):
                return False

        assert self._sqlite_conn is not None

        def _run() -> bool:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                (title, now, session_id),
            )
            self._sqlite_conn.commit()
            return cur.rowcount > 0

        return await self._run_sqlite_op(_run)

    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                if user_id:
                    result = await conn.execute("DELETE FROM sessions WHERE id=$1 AND user_id=$2", session_id, user_id)
                else:
                    result = await conn.execute("DELETE FROM sessions WHERE id=$1", session_id)
            # asyncpg "DELETE N" formatında string döndürür; sayısal parse ile > 0 kontrolü.
            try:
                return int(str(result).split()[-1]) > 0
            except (ValueError, IndexError, AttributeError):
                return False

        assert self._sqlite_conn is not None

        def _run() -> bool:
            assert self._sqlite_conn is not None
            if user_id:
                cur = self._sqlite_conn.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id))
            else:
                cur = self._sqlite_conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._sqlite_conn.commit()
            return cur.rowcount > 0

        return await self._run_sqlite_op(_run)
    async def create_user(self, username: str, role: str = "user", password: Optional[str] = None, tenant_id: str = "default") -> UserRecord:
        user_id = str(uuid.uuid4())
        created_at = _utc_now_iso()
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
                    created_at,
                )
            return UserRecord(id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id)

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, password_hash, role, tenant_id, created_at),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)
        return UserRecord(id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id)

    async def register_user(self, username: str, password: str, role: str = "user", tenant_id: str = "default") -> UserRecord:
        return await self.create_user(username=username, role=role, password=password, tenant_id=tenant_id)

    async def authenticate_user(self, username: str, password: str) -> Optional[UserRecord]:
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
            return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]), tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]))

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, password_hash, role, created_at, tenant_id FROM users WHERE username=?",
                (username,),
            )
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row or not row["password_hash"]:
            return None
        if not _verify_password(password, str(row["password_hash"])):
            return None
        return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]), tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]))

    async def _get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=$1",
                    user_id,
                )
            if not row:
                return None
            return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]), tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]))

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=?",
                (user_id,),
            )
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row:
            return None
        return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]), tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]))

    async def create_auth_token(
        self,
        user_id: str,
        ttl_days: Optional[int] = None,
        role: Optional[str] = None,
        username: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> AuthTokenRecord:
        created_at = _utc_now_iso()
        effective_ttl_days = ttl_days if ttl_days is not None else int(getattr(self.cfg, "JWT_TTL_DAYS", 7) or 7)
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
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(days=ttl)).timestamp()),
        }
        secret_key = str(getattr(self.cfg, "JWT_SECRET_KEY", "") or "sidar-dev-secret")
        algorithm = str(getattr(self.cfg, "JWT_ALGORITHM", "HS256") or "HS256")
        token = jwt.encode(payload, secret_key, algorithm=algorithm)
        return AuthTokenRecord(token=token, user_id=user_id, expires_at=expires_at, created_at=created_at)

    def verify_auth_token(self, token: str) -> Optional[UserRecord]:
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

    async def get_user_by_token(self, token: str) -> Optional[UserRecord]:
        """Geriye dönük uyumluluk: JWT doğrular, mümkünse kullanıcı kaydını da yükler."""
        jwt_user = self.verify_auth_token(token)
        if not jwt_user:
            return None

        db_user = await self._get_user_by_id(jwt_user.id)
        return db_user or jwt_user


    async def list_access_policies(self, user_id: str, tenant_id: Optional[str] = None) -> list[AccessPolicyRecord]:
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
        rows = await self._run_sqlite_op(_run)
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
        now = _utc_now_iso()
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
                    now,
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
            return spec.resource_type == r_type and spec.action == act and (spec.resource_id == "*" or spec.resource_id == r_id)

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
        timestamp: Optional[str] = None,
    ) -> None:
        event_time = (timestamp or _utc_now_iso()).strip() or _utc_now_iso()
        tenant = (tenant_id or "default").strip() or "default"
        user = (user_id or "").strip()
        act = (action or "").strip().lower()
        res = (resource or "").strip()
        ip = (ip_address or "unknown").strip() or "unknown"
        if not act or not res:
            raise ValueError("action and resource are required")

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_logs (user_id, tenant_id, action, resource, ip_address, allowed, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    user,
                    tenant,
                    act,
                    res,
                    ip,
                    bool(allowed),
                    event_time,
                )
            return

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                """
                INSERT INTO audit_logs (user_id, tenant_id, action, resource, ip_address, allowed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user, tenant, act, res, ip, int(bool(allowed)), event_time),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)

    async def list_audit_logs(
        self,
        *,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        max_items = max(1, min(int(limit or 100), 1000))
        normalized_user = (user_id or "").strip() or None
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            query = (
                "SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp "
                "FROM audit_logs"
            )
            args: tuple[Any, ...]
            if normalized_user is not None:
                query += " WHERE user_id=$1 ORDER BY timestamp DESC LIMIT $2"
                args = (normalized_user, max_items)
            else:
                query += " ORDER BY timestamp DESC LIMIT $1"
                args = (max_items,)
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [
                AuditLogRecord(
                    id=int(r["id"]),
                    user_id=str(r["user_id"]),
                    tenant_id=str(r["tenant_id"]),
                    action=str(r["action"]),
                    resource=str(r["resource"]),
                    ip_address=str(r["ip_address"]),
                    allowed=bool(r["allowed"]),
                    timestamp=str(r["timestamp"]),
                )
                for r in rows
            ]

        assert self._sqlite_conn is not None

        def _run():
            assert self._sqlite_conn is not None
            if normalized_user is not None:
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp
                    FROM audit_logs
                    WHERE user_id=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (normalized_user, max_items),
                )
            else:
                cur = self._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp
                    FROM audit_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (max_items,),
                )
            return cur.fetchall()

        rows = await self._run_sqlite_op(_run)
        return [
            AuditLogRecord(
                id=int(r["id"]),
                user_id=str(r["user_id"]),
                tenant_id=str(r["tenant_id"]),
                action=str(r["action"]),
                resource=str(r["resource"]),
                ip_address=str(r["ip_address"]),
                allowed=bool(r["allowed"]),
                timestamp=str(r["timestamp"]),
            )
            for r in rows
        ]

    async def upsert_user_quota(self, user_id: str, daily_token_limit: int = 0, daily_request_limit: int = 0) -> None:
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

    async def record_provider_usage_daily(self, user_id: str, provider: str, tokens_used: int, requests_inc: int = 1) -> None:
        provider_name = (provider or "unknown").lower().strip() or "unknown"
        today = datetime.now(timezone.utc).date().isoformat()
        req = max(0, int(requests_inc or 0))
        toks = max(0, int(tokens_used or 0))

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO provider_usage_daily (user_id, provider, usage_date, requests_used, tokens_used)
                    VALUES ($1, $2, $3::date, $4, $5)
                    ON CONFLICT (user_id, provider, usage_date)
                    DO UPDATE SET requests_used=provider_usage_daily.requests_used + EXCLUDED.requests_used,
                                  tokens_used=provider_usage_daily.tokens_used + EXCLUDED.tokens_used
                    """,
                    user_id,
                    provider_name,
                    today,
                    req,
                    toks,
                )
            return

        assert self._sqlite_conn is not None
        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                """
                INSERT INTO provider_usage_daily (user_id, provider, usage_date, requests_used, tokens_used)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider, usage_date)
                DO UPDATE SET requests_used=requests_used + excluded.requests_used,
                              tokens_used=tokens_used + excluded.tokens_used
                """,
                (user_id, provider_name, today, req, toks),
            )
            self._sqlite_conn.commit()
        await self._run_sqlite_op(_run)

    async def get_user_quota_status(self, user_id: str, provider: str) -> dict[str, int | bool]:
        provider_name = (provider or "unknown").lower().strip() or "unknown"
        today = datetime.now(timezone.utc).date().isoformat()

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                quota = await conn.fetchrow(
                    "SELECT daily_token_limit, daily_request_limit FROM user_quotas WHERE user_id=$1",
                    user_id,
                )
                usage = await conn.fetchrow(
                    """
                    SELECT requests_used, tokens_used
                    FROM provider_usage_daily
                    WHERE user_id=$1 AND provider=$2 AND usage_date=$3::date
                    """,
                    user_id,
                    provider_name,
                    today,
                )
            q_tokens = int((quota["daily_token_limit"] if quota else 0) or 0)
            q_reqs = int((quota["daily_request_limit"] if quota else 0) or 0)
            u_tokens = int((usage["tokens_used"] if usage else 0) or 0)
            u_reqs = int((usage["requests_used"] if usage else 0) or 0)
        else:
            assert self._sqlite_conn is not None
            def _run() -> tuple[Optional[sqlite3.Row], Optional[sqlite3.Row]]:
                assert self._sqlite_conn is not None
                q = self._sqlite_conn.execute(
                    "SELECT daily_token_limit, daily_request_limit FROM user_quotas WHERE user_id=?",
                    (user_id,),
                ).fetchone()
                u = self._sqlite_conn.execute(
                    "SELECT requests_used, tokens_used FROM provider_usage_daily WHERE user_id=? AND provider=? AND usage_date=?",
                    (user_id, provider_name, today),
                ).fetchone()
                return q, u
            quota, usage = await self._run_sqlite_op(_run)
            q_tokens = int((quota["daily_token_limit"] if quota else 0) or 0)
            q_reqs = int((quota["daily_request_limit"] if quota else 0) or 0)
            u_tokens = int((usage["tokens_used"] if usage else 0) or 0)
            u_reqs = int((usage["requests_used"] if usage else 0) or 0)

        return {
            "daily_token_limit": q_tokens,
            "daily_request_limit": q_reqs,
            "tokens_used": u_tokens,
            "requests_used": u_reqs,
            "token_limit_exceeded": q_tokens > 0 and u_tokens >= q_tokens,
            "request_limit_exceeded": q_reqs > 0 and u_reqs >= q_reqs,
        }

    async def list_users_with_quotas(self) -> list[dict[str, Any]]:
        """Tüm kullanıcıları kota bilgileriyle birlikte döndürür."""
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT u.id, u.username, u.role, u.created_at,
                           COALESCE(q.daily_token_limit, 0) AS daily_token_limit,
                           COALESCE(q.daily_request_limit, 0) AS daily_request_limit
                    FROM users u
                    LEFT JOIN user_quotas q ON q.user_id = u.id
                    ORDER BY u.created_at ASC
                    """
                )
                return [
                    {
                        "id": str(row["id"]),
                        "username": str(row["username"]),
                        "role": str(row["role"]),
                        "created_at": str(row["created_at"]),
                        "daily_token_limit": int(row["daily_token_limit"] or 0),
                        "daily_request_limit": int(row["daily_request_limit"] or 0),
                    }
                    for row in rows
                ]

        assert self._sqlite_conn is not None

        def _run() -> list[dict[str, Any]]:
            assert self._sqlite_conn is not None
            rows = self._sqlite_conn.execute(
                """
                SELECT u.id, u.username, u.role, u.created_at,
                       COALESCE(q.daily_token_limit, 0) AS daily_token_limit,
                       COALESCE(q.daily_request_limit, 0) AS daily_request_limit
                FROM users u
                LEFT JOIN user_quotas q ON q.user_id = u.id
                ORDER BY u.created_at ASC
                """
            ).fetchall()
            return [
                {
                    "id": str(row["id"]),
                    "username": str(row["username"]),
                    "role": str(row["role"]),
                    "created_at": str(row["created_at"]),
                    "daily_token_limit": int(row["daily_token_limit"] or 0),
                    "daily_request_limit": int(row["daily_request_limit"] or 0),
                }
                for row in rows
            ]

        return await self._run_sqlite_op(_run)

    async def get_admin_stats(self) -> dict[str, Any]:
        users = await self.list_users_with_quotas()

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                totals = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(SUM(tokens_used), 0) AS total_tokens_used,
                        COALESCE(SUM(requests_used), 0) AS total_api_requests
                    FROM provider_usage_daily
                    """
                )
        else:
            assert self._sqlite_conn is not None

            def _run_totals() -> sqlite3.Row:
                assert self._sqlite_conn is not None
                row = self._sqlite_conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(tokens_used), 0) AS total_tokens_used,
                        COALESCE(SUM(requests_used), 0) AS total_api_requests
                    FROM provider_usage_daily
                    """
                ).fetchone()
                assert row is not None
                return row

            totals = await self._run_sqlite_op(_run_totals)

        return {
            "total_users": len(users),
            "total_tokens_used": int(totals["total_tokens_used"] or 0),
            "total_api_requests": int(totals["total_api_requests"] or 0),
            "users": users,
        }

    async def create_session(self, user_id: str, title: str) -> SessionRecord:
        session_id = str(uuid.uuid4())
        now = _utc_now_iso()

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES ($1, $2, $3, $4, $5)",
                    session_id,
                    user_id,
                    title,
                    now,
                    now,
                )
            return SessionRecord(id=session_id, user_id=user_id, title=title, created_at=now, updated_at=now)

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, title, now, now),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)
        return SessionRecord(id=session_id, user_id=user_id, title=title, created_at=now, updated_at=now)

    async def add_message(self, session_id: str, role: str, content: str, tokens_used: int = 0) -> MessageRecord:
        now = _utc_now_iso()
        tokens = max(0, int(tokens_used or 0))

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO messages (session_id, role, content, tokens_used, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    session_id,
                    role,
                    content,
                    tokens,
                    now,
                )
                msg_id = int(row["id"])
            return MessageRecord(id=msg_id, session_id=session_id, role=role, content=content, tokens_used=tokens, created_at=now)

        assert self._sqlite_conn is not None

        def _run() -> int:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "INSERT INTO messages (session_id, role, content, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, tokens, now),
            )
            self._sqlite_conn.commit()
            return int(cur.lastrowid)

        msg_id = await self._run_sqlite_op(_run)
        return MessageRecord(id=msg_id, session_id=session_id, role=role, content=content, tokens_used=tokens, created_at=now)

    async def get_session_messages(self, session_id: str) -> list[MessageRecord]:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, session_id, role, content, tokens_used, created_at FROM messages WHERE session_id=$1 ORDER BY id ASC",
                    session_id,
                )
            return [
                MessageRecord(
                    id=int(r["id"]),
                    session_id=str(r["session_id"]),
                    role=str(r["role"]),
                    content=str(r["content"]),
                    tokens_used=int(r["tokens_used"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

        assert self._sqlite_conn is not None

        def _run() -> list[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, session_id, role, content, tokens_used, created_at FROM messages WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            )
            return cur.fetchall()

        rows = await self._run_sqlite_op(_run)
        return [
            MessageRecord(
                id=int(r["id"]),
                session_id=str(r["session_id"]),
                role=str(r["role"]),
                content=str(r["content"]),
                tokens_used=int(r["tokens_used"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    async def replace_session_messages(self, session_id: str, messages: list[dict[str, object]]) -> int:
        """Bir oturumun mesajlarını atomik olarak yenileriyle değiştirir."""
        normalized_messages = [
            {
                "role": str(item.get("role", "") or "").strip() or "assistant",
                "content": str(item.get("content", "") or "").strip(),
            }
            for item in list(messages or [])
            if str(item.get("content", "") or "").strip()
        ]
        now = _utc_now_iso()

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM messages WHERE session_id=$1", session_id)
                    for item in normalized_messages:
                        await conn.execute(
                            """
                            INSERT INTO messages (session_id, role, content, tokens_used, created_at)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            session_id,
                            item["role"],
                            item["content"],
                            0,
                            now,
                        )
                    await conn.execute(
                        "UPDATE sessions SET updated_at=$2 WHERE id=$1",
                        session_id,
                        now,
                    )
            return len(normalized_messages)

        assert self._sqlite_conn is not None

        def _run() -> int:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            for item in normalized_messages:
                self._sqlite_conn.execute(
                    "INSERT INTO messages (session_id, role, content, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, item["role"], item["content"], 0, now),
                )
            self._sqlite_conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (now, session_id),
            )
            self._sqlite_conn.commit()
            return len(normalized_messages)

        return await self._run_sqlite_op(_run)