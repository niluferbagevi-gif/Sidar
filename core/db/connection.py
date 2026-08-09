"""Database connection, pooling, and transaction helpers for Sidar."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
import re
import sqlite3
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class DatabaseConnectionMixin:
    """Connection lifecycle facade shared by the legacy ``Database`` class."""

    cfg: Any
    database_url: str
    primary_database_url: str
    pool_size: int
    pool_min_size: int
    statement_cache_size: int
    max_cached_statement_lifetime: float
    _backend: str
    _sqlite_path: Path | None
    _sqlite_conn: sqlite3.Connection | None
    _sqlite_write_lock: asyncio.Lock | None
    _sqlite_executor: ThreadPoolExecutor | None
    _sqlite_closed: bool
    _pg_pool: Any
    _pg_pool_factory: Callable[..., Any] | None
    degraded_mode: bool
    degraded_reason: str

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

        self._sqlite_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sidar-sqlite")
        self._sqlite_closed = False
        loop = asyncio.get_running_loop()
        self._sqlite_conn = await loop.run_in_executor(self._sqlite_executor, _open)

    async def _run_sqlite_op(self, operation: Callable[[], _T], *, write: bool = True) -> _T:
        """SQLite işlemini tek instance'a ait dedicated worker lane içinde çalıştırır.

        SQLite bağlantısı tek nesne olarak paylaşıldığı için okuma ve yazma ayrımı
        yapılmadan aynı ``ThreadPoolExecutor(max_workers=1)`` kuyruğuna alınır.
        ``check_same_thread=False`` yalnızca Python thread kontrolünü gevşetir; aynı
        connection'ın farklı threadpool thread'lerinde eşzamanlı kullanılması güvenli
        kabul edilmez ve xdist/coverage altında native çökmelere yol açabilir.
        """
        if self._sqlite_conn is None or self._sqlite_closed:
            raise RuntimeError("SQLite bağlantısı başlatılmadı.")
        if self._sqlite_executor is None:
            self._sqlite_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="sidar-sqlite"
            )
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

        async with self._sqlite_write_lock:
            for attempt in self._sqlite_retry_range(1, 4):
                try:
                    return await running_loop.run_in_executor(self._sqlite_executor, operation)
                except sqlite3.OperationalError as exc:
                    if write:
                        await running_loop.run_in_executor(
                            self._sqlite_executor, self._sqlite_conn.rollback
                        )
                    if "database is locked" not in str(exc).lower() or attempt == 3:
                        raise
                    await asyncio.sleep(
                        0.015 * (2 ** (attempt - 1)) + random.uniform(0.0, 0.01)  # nosec B311  # güvenlik değil jitter/backoff amaçlıdır.
                    )
                except Exception:
                    if write:
                        try:
                            await running_loop.run_in_executor(
                                self._sqlite_executor, self._sqlite_conn.rollback
                            )
                        except Exception as rollback_exc:
                            logger.exception(
                                "SQLite rollback başarısız oldu; veri bütünlüğü riske girebilir."
                            )
                            raise RuntimeError(
                                "SQLite işlemi ve rollback başarısız oldu."
                            ) from rollback_exc
                    raise
        raise sqlite3.OperationalError("SQLite işlemi deneme sınırına ulaştı ve tamamlanamadı.")

    @staticmethod
    def _sqlite_retry_range(start: int, stop: int) -> Any:
        """Resolve the legacy-monkeypatchable retry range helper."""
        from core import db as core_db

        return getattr(core_db, "range", range)(start, stop)

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

        if self._sqlite_executor is None:
            self._sqlite_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="sidar-sqlite"
            )
        loop = asyncio.get_running_loop()
        async with self._sqlite_write_lock:
            await loop.run_in_executor(self._sqlite_executor, self._sqlite_conn.execute, "BEGIN")
            try:
                yield self._sqlite_conn
            except Exception:
                await loop.run_in_executor(self._sqlite_executor, self._sqlite_conn.rollback)
                raise
            else:
                await loop.run_in_executor(self._sqlite_executor, self._sqlite_conn.commit)

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
        worker = os.getenv("PYTEST_XDIST_WORKER", "").strip()
        # A PostgreSQL failure may send every xdist worker into degraded mode at
        # once.  Keep their WAL/SHM files separate instead of racing on one DB.
        worker_suffix = re.sub(r"[^A-Za-z0-9_.-]", "_", worker) if worker else ""
        filename = f"sidar_degraded.{worker_suffix}.db" if worker_suffix else "sidar_degraded.db"
        return f"sqlite+aiosqlite:///{(base_dir / 'data' / filename).as_posix()}"

    @staticmethod
    def _postgres_user_action_message(reason: str, exc: BaseException | None = None) -> str:
        """Resolve the legacy-monkeypatchable PostgreSQL action message facade."""
        from core import db as core_db

        return cast(str, cast(Any, core_db)._postgres_user_action_message(reason, exc))

    async def _enter_degraded_mode(self, reason: str, exc: BaseException) -> None:
        if not bool(getattr(self.cfg, "DB_DEGRADED_MODE_ON_POSTGRES_FAILURE", True)):
            raise exc

        fallback_url = self._postgres_degraded_sqlite_url()
        action_message = self._postgres_user_action_message(reason, exc)
        logger.warning(
            "%s primary=%s fallback=%s",
            action_message,
            self._redact_database_url(self.primary_database_url),
            self._redact_database_url(fallback_url),
        )
        self.degraded_mode = True
        self.degraded_reason = action_message
        self._pg_pool = None
        self._sqlite_executor = None
        self._sqlite_closed = False
        self.database_url = fallback_url
        self.cfg.DATABASE_URL = fallback_url
        self._backend = "sqlite"
        self._sqlite_conn = None
        self._sqlite_write_lock = None
        self._sqlite_executor = None
        self._sqlite_closed = False
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
            executor = self._sqlite_executor
            self._sqlite_closed = True
            self._sqlite_conn = None
            self._sqlite_write_lock = None
            self._sqlite_executor = None
            if callable(getattr(conn, "close", None)):
                if executor is not None:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(executor, conn.close)
                    executor.shutdown(wait=True)
                else:
                    await asyncio.to_thread(conn.close)

        if self._pg_pool is not None:
            pool = self._pg_pool
            self._pg_pool = None
            await pool.close()
