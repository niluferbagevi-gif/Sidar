"""Entity/Persona Memory (v5.0)

Kullanıcının uzun vadeli kodlama stilini, dil tercihlerini ve etkileşim
örüntülerini Mem0/Zep benzeri bir yapıda SQLite veritabanında saklar.

Kullanım:
    em = EntityMemory(database_url="sqlite+aiosqlite:///data/sidar.db", config=cfg)
    await em.initialize()
    await em.upsert(user_id="u1", key="coding_style", value="functional, type-hinted")
    style = await em.get(user_id="u1", key="coding_style")
    profile = await em.get_profile(user_id="u1")
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# SQLAlchemy async import (opsiyonel; yoksa noop stub kullanılır)
try:
    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import create_async_engine

    _SA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SA_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Sabitleri
# ──────────────────────────────────────────────────────────────────────────────

# Desteklenen yerleşik persona alanları (önerilir ama zorunlu değil)
WELL_KNOWN_KEYS = frozenset(
    [
        "coding_style",  # "functional", "OOP", "procedural" …
        "preferred_language",  # "Python", "TypeScript", "Rust" …
        "verbosity",  # "concise", "detailed", "medium"
        "framework_pref",  # "FastAPI", "Django", "React" …
        "test_style",  # "pytest", "unittest", "jest" …
        "comment_language",  # "tr", "en"
        "preferred_model",  # Tercih edilen LLM modeli
        "timezone",  # "Europe/Istanbul"
        "topics",  # JSON listesi: ["backend", "ml", "devops"]
    ]
)

_DDL = """
CREATE TABLE IF NOT EXISTS entity_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL DEFAULT '',
    metadata    TEXT    NOT NULL DEFAULT '{}',
    created_at  REAL    NOT NULL,
    updated_at  REAL    NOT NULL,
    UNIQUE (user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_entity_memory_user ON entity_memory(user_id);
"""


# ──────────────────────────────────────────────────────────────────────────────
# EntityMemory
# ──────────────────────────────────────────────────────────────────────────────


class EntityMemory:
    """
    Kullanıcı başına anahtar/değer persona deposu.

    Parametreler:
        database_url: SQLAlchemy async URL (sqlite+aiosqlite:/// veya postgresql+asyncpg://)
        config: Config nesnesi (ENABLE_ENTITY_MEMORY, ENTITY_MEMORY_TTL_DAYS okunur)
        ttl_days: Kaç günden eski kayıtlar temizlensin (0 = hiç temizleme)
        max_per_user: Kullanıcı başına max anahtar sayısı (LRU eviction)
    """

    def __init__(
        self,
        database_url: str = "sqlite+aiosqlite:///data/sidar.db",
        config: Any | None = None,
        ttl_days: int | None = None,
        max_per_user: int | None = None,
    ) -> None:
        self._db_url = database_url
        self._engine: Any | None = None

        cfg_ttl = int(getattr(config, "ENTITY_MEMORY_TTL_DAYS", 90) or 90)
        cfg_max = int(getattr(config, "ENTITY_MEMORY_MAX_PER_USER", 100) or 100)
        self.ttl_days: int = ttl_days if ttl_days is not None else cfg_ttl
        self.max_per_user: int = max_per_user if max_per_user is not None else cfg_max
        self.enabled: bool = bool(getattr(config, "ENABLE_ENTITY_MEMORY", True))

    # ─────────────────────────────────────────────
    #  BAŞLATMA
    # ─────────────────────────────────────────────

    async def initialize(self) -> None:
        """Tabloyu oluştur / güncelle."""
        if not self.enabled:
            return
        if not _SA_AVAILABLE:
            logger.warning("EntityMemory: sqlalchemy+aiosqlite kurulu değil, bellek devre dışı.")
            return
        self._engine = create_async_engine(self._db_url, echo=False, future=True)
        async with self._engine.begin() as conn:
            for stmt in _DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(sql_text(stmt))
        logger.debug("EntityMemory başlatıldı: %s", self._db_url)

    # ─────────────────────────────────────────────
    #  YAZMA
    # ─────────────────────────────────────────────

    async def upsert(
        self,
        user_id: str,
        key: str,
        value: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Belirtilen user_id + key için değeri ekle veya güncelle."""
        if not self.enabled or not self._engine:
            return False
        user_id = (user_id or "").strip()
        key = (key or "").strip()
        if not user_id or not key:
            return False

        now = time.time()
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)

        async with self._engine.begin() as conn:
            # Mevcut kayıt sayısını kontrol et (max_per_user eviction)
            count_res = await conn.execute(
                sql_text("SELECT COUNT(*) FROM entity_memory WHERE user_id = :uid"),
                {"uid": user_id},
            )
            count = count_res.scalar() or 0
            if count >= self.max_per_user:
                # En eski kaydı sil (LRU benzeri)
                await conn.execute(
                    sql_text(
                        "DELETE FROM entity_memory WHERE id = ("
                        "  SELECT id FROM entity_memory WHERE user_id = :uid"
                        "  ORDER BY updated_at ASC LIMIT 1)"
                    ),
                    {"uid": user_id},
                )

            await conn.execute(
                sql_text(
                    "INSERT INTO entity_memory (user_id, key, value, metadata, created_at, updated_at)"
                    " VALUES (:uid, :key, :val, :meta, :now, :now)"
                    " ON CONFLICT (user_id, key) DO UPDATE SET"
                    "  value = excluded.value,"
                    "  metadata = excluded.metadata,"
                    "  updated_at = excluded.updated_at"
                ),
                {"uid": user_id, "key": key, "val": value, "meta": meta_str, "now": now},
            )
        logger.debug("EntityMemory.upsert: user=%s key=%s", user_id, key)
        return True

    # ─────────────────────────────────────────────
    #  OKUMA
    # ─────────────────────────────────────────────

    async def get(self, user_id: str, key: str) -> str | None:
        """Belirtilen user_id + key için değeri döner; bulunamazsa None."""
        if not self.enabled or not self._engine:
            return None
        async with self._engine.connect() as conn:
            row = await conn.execute(
                sql_text(
                    "SELECT value FROM entity_memory"
                    " WHERE user_id = :uid AND key = :key"
                    " LIMIT 1"
                ),
                {"uid": user_id, "key": key},
            )
            result = row.fetchone()
        return result[0] if result else None

    async def get_profile(self, user_id: str) -> dict[str, str]:
        """Kullanıcının tüm persona anahtarlarını {key: value} sözlüğü olarak döner."""
        if not self.enabled or not self._engine:
            return {}
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                sql_text(
                    "SELECT key, value FROM entity_memory"
                    " WHERE user_id = :uid"
                    " ORDER BY updated_at DESC"
                ),
                {"uid": user_id},
            )
            return {r[0]: r[1] for r in rows.fetchall()}

    async def list_users(self) -> list[str]:
        """Entity kaydı olan tüm user_id'leri döner."""
        if not self.enabled or not self._engine:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                sql_text("SELECT DISTINCT user_id FROM entity_memory ORDER BY user_id")
            )
            return [r[0] for r in rows.fetchall()]

    # ─────────────────────────────────────────────
    #  SİLME
    # ─────────────────────────────────────────────

    async def delete(self, user_id: str, key: str) -> bool:
        """Belirli bir user_id + key kaydını siler."""
        if not self.enabled or not self._engine:
            return False
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sql_text("DELETE FROM entity_memory WHERE user_id = :uid AND key = :key"),
                {"uid": user_id, "key": key},
            )
        return (result.rowcount or 0) > 0

    async def delete_user(self, user_id: str) -> int:
        """Kullanıcıya ait tüm kayıtları siler; silinen satır sayısını döner."""
        if not self.enabled or not self._engine:
            return 0
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sql_text("DELETE FROM entity_memory WHERE user_id = :uid"),
                {"uid": user_id},
            )
        return result.rowcount or 0

    # ─────────────────────────────────────────────
    #  BAKIM
    # ─────────────────────────────────────────────

    async def purge_expired(self) -> int:
        """TTL süresi dolmuş kayıtları siler; silinen satır sayısını döner."""
        if not self.enabled or not self._engine or self.ttl_days <= 0:
            return 0
        cutoff = time.time() - (self.ttl_days * 86400)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sql_text("DELETE FROM entity_memory WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            )
        removed = result.rowcount or 0
        if removed:
            logger.info("EntityMemory.purge_expired: %d kayıt silindi.", removed)
        return removed

    async def close(self) -> None:
        """Veritabanı bağlantısını kapat."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None


# ──────────────────────────────────────────────────────────────────────────────
# Modül düzeyinde singleton yardımcıları
# ──────────────────────────────────────────────────────────────────────────────

_instance: EntityMemory | None = None


def get_entity_memory(config: Any | None = None) -> EntityMemory:
    """Process-içi tekil EntityMemory örneğini döner; ilk çağrıda oluşturur."""
    global _instance
    if _instance is None or not isinstance(_instance, EntityMemory):
        from config import Config

        cfg = config or Config()
        db_url = str(getattr(cfg, "DATABASE_URL", "sqlite+aiosqlite:///data/sidar.db") or "")
        _instance = EntityMemory(database_url=db_url, config=cfg)
    return _instance
