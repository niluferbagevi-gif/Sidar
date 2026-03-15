"""Sidar kalıcı veri katmanı (v3.0 hazırlık): kullanıcı/oturum/mesaj şemaları."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import uuid
import secrets
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
        """SQLite işlemlerini tek bağlantı üzerinde sıralı çalıştır (thread-safe)."""
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
            await self._ensure_schema_version_postgresql()
            return
        await self._init_schema_sqlite()
        await self._ensure_schema_version_sqlite()

    async def _init_schema_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        schema_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'user',
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
        ]
        async with self._pg_pool.acquire() as conn:
            for q in queries:
                await conn.execute(q)


    async def _ensure_schema_version_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            tbl = self.schema_version_table
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
        tbl = self.schema_version_table
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
                    "SELECT id, username, role, created_at FROM users WHERE username=$1",
                    username,
                )
                if row:
                    return UserRecord(
                        id=str(row["id"]),
                        username=str(row["username"]),
                        role=str(row["role"]),
                        created_at=str(row["created_at"]),
                    )
            return await self.create_user(username=username, role=role)

        assert self._sqlite_conn is not None

        def _fetch() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, role, created_at FROM users WHERE username=?",
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
            return result.endswith("1")

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
            return result.endswith("1")

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
    async def create_user(self, username: str, role: str = "user", password: Optional[str] = None) -> UserRecord:
        user_id = str(uuid.uuid4())
        created_at = _utc_now_iso()
        password_hash = _hash_password(password) if password else None

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, password_hash, role, created_at) VALUES ($1, $2, $3, $4, $5)",
                    user_id,
                    username,
                    password_hash,
                    role,
                    created_at,
                )
            return UserRecord(id=user_id, username=username, role=role, created_at=created_at)

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, password_hash, role, created_at),
            )
            self._sqlite_conn.commit()

        await self._run_sqlite_op(_run)
        return UserRecord(id=user_id, username=username, role=role, created_at=created_at)

    async def register_user(self, username: str, password: str, role: str = "user") -> UserRecord:
        return await self.create_user(username=username, role=role, password=password)

    async def authenticate_user(self, username: str, password: str) -> Optional[UserRecord]:
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, password_hash, role, created_at FROM users WHERE username=$1",
                    username,
                )
            if not row or not row["password_hash"]:
                return None
            if not _verify_password(password, str(row["password_hash"])):
                return None
            return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]))

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(
                "SELECT id, username, password_hash, role, created_at FROM users WHERE username=?",
                (username,),
            )
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row or not row["password_hash"]:
            return None
        if not _verify_password(password, str(row["password_hash"])):
            return None
        return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]))

    async def create_auth_token(self, user_id: str, ttl_days: int = 7) -> AuthTokenRecord:
        token = secrets.token_urlsafe(48)
        created_at = _utc_now_iso()
        expires_at = _expires_in(max(1, ttl_days))
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO auth_tokens (token, user_id, expires_at, created_at) VALUES ($1, $2, $3, $4)",
                    token, user_id, expires_at, created_at,
                )
        else:
            assert self._sqlite_conn is not None

            def _run() -> None:
                assert self._sqlite_conn is not None
                self._sqlite_conn.execute(
                    "INSERT INTO auth_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                    (token, user_id, expires_at, created_at),
                )
                self._sqlite_conn.commit()

            await self._run_sqlite_op(_run)
        return AuthTokenRecord(token=token, user_id=user_id, expires_at=expires_at, created_at=created_at)

    async def get_user_by_token(self, token: str) -> Optional[UserRecord]:
        now_iso = _utc_now_iso()
        query = (
            "SELECT u.id, u.username, u.role, u.created_at "
            "FROM auth_tokens t JOIN users u ON u.id=t.user_id "
            "WHERE t.token=? AND t.expires_at>?"
        )
        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    query.replace("?", "$1", 1).replace("?", "$2", 1),
                    token,
                    now_iso,
                )
            if not row:
                return None
            return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]))

        assert self._sqlite_conn is not None

        def _run() -> Optional[sqlite3.Row]:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.execute(query, (token, now_iso))
            return cur.fetchone()

        row = await self._run_sqlite_op(_run)
        if not row:
            return None
        return UserRecord(id=str(row["id"]), username=str(row["username"]), role=str(row["role"]), created_at=str(row["created_at"]))


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