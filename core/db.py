"""Sidar kalıcı veri katmanı (v3.0 hazırlık): kullanıcı/oturum/mesaj şemaları."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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

        self._backend = "sqlite"
        self._sqlite_path: Optional[Path] = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None

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
            path = self.cfg.BASE_DIR / path
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
            return conn

        self._sqlite_conn = await asyncio.to_thread(_open)

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
            await asyncio.to_thread(conn.close)

        if self._pg_pool is not None:
            pool = self._pg_pool
            self._pg_pool = None
            await pool.close()

    async def init_schema(self) -> None:
        if self._backend == "postgresql":
            await self._init_schema_postgresql()
            return
        await self._init_schema_sqlite()

    async def _init_schema_sqlite(self) -> None:
        assert self._sqlite_conn is not None

        schema_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
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
        """

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.executescript(schema_sql)
            self._sqlite_conn.commit()

        await asyncio.to_thread(_run)

    async def _init_schema_postgresql(self) -> None:
        assert self._pg_pool is not None
        queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMPTZ NOT NULL
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
        ]
        async with self._pg_pool.acquire() as conn:
            for q in queries:
                await conn.execute(q)

    async def create_user(self, username: str, role: str = "user") -> UserRecord:
        user_id = str(uuid.uuid4())
        created_at = _utc_now_iso()

        if self._backend == "postgresql":
            assert self._pg_pool is not None
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, username, role, created_at) VALUES ($1, $2, $3, $4)",
                    user_id,
                    username,
                    role,
                    created_at,
                )
            return UserRecord(id=user_id, username=username, role=role, created_at=created_at)

        assert self._sqlite_conn is not None

        def _run() -> None:
            assert self._sqlite_conn is not None
            self._sqlite_conn.execute(
                "INSERT INTO users (id, username, role, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, role, created_at),
            )
            self._sqlite_conn.commit()

        await asyncio.to_thread(_run)
        return UserRecord(id=user_id, username=username, role=role, created_at=created_at)

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

        await asyncio.to_thread(_run)
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

        msg_id = await asyncio.to_thread(_run)
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

        rows = await asyncio.to_thread(_run)
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
