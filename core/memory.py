"""Sidar Project - Konuşma Belleği (DB tabanlı, çoklu kullanıcı hazırlığı)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Config
from core.db import Database, MessageRecord

_config_get_config: Callable[[], Config] | None
try:
    from config import get_config as _config_get_config
except ImportError:  # pragma: no cover - test doubles may only expose Config
    _config_get_config = None

logger = logging.getLogger(__name__)


def get_config() -> Config:
    """Bellek modülü için geriye dönük uyumlu config erişimi sağlar."""
    return _config_get_config() if callable(_config_get_config) else Config()


class MemoryAuthError(PermissionError):
    """Bellek işlemi için doğrulanmış kullanıcı bağlamı zorunlu."""


class ConversationMemory:
    """Thread-safe konuşma belleği; kalıcılık katmanı olarak DB kullanır."""

    def __init__(
        self,
        database_url: str | None = None,
        base_dir: Path | None = None,
        *,
        file_path: Path | None = None,
        max_turns: int = 20,
        encryption_key: str = "",
        keep_last: int = 4,
    ) -> None:
        # Geriye dönük uyumluluk: file_path hâlâ desteklenir, ancak yeni API base_dir/database_url'dur.
        resolved_base_dir = Path(base_dir) if base_dir is not None else None
        if resolved_base_dir is None and file_path is not None:
            resolved_base_dir = Path(file_path).parent
        if resolved_base_dir is None:
            resolved_base_dir = Path.cwd() / "data"

        self.sessions_dir = resolved_base_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.max_turns = max_turns
        self.keep_last = keep_last
        self._lock = threading.RLock()

        # Bulgu D: Config() her seferinde yeni nesne oluşturuyordu; varsa singleton kullanılıyor.
        self.cfg = get_config()
        resolved_database_url = database_url
        if not resolved_database_url:
            resolved_database_url = getattr(self.cfg, "DATABASE_URL", "")

        normalized_database_url = str(resolved_database_url or "").strip()
        placeholder_sqlite_urls = {
            "sqlite:///x",
            "sqlite+aiosqlite:///x",
            "sqlite:///x.db",
            "sqlite+aiosqlite:///x.db",
        }
        should_use_memory_default = (
            # Çağıran açık bir DB URL vermediyse ve base_dir ile yerel çalışma dizini
            # istediyse bellek katmanı için izole sqlite dosyası kullan.
            (database_url is None and base_dir is not None)
            or not normalized_database_url
            or normalized_database_url in placeholder_sqlite_urls
            or normalized_database_url.endswith("data/sidar.db")
            or (database_url is None and normalized_database_url.startswith("postgresql"))
        )
        if should_use_memory_default:
            resolved_database_url = (
                f"sqlite+aiosqlite:///{(resolved_base_dir / 'sidar_memory.db').as_posix()}"
            )

        self.cfg.DATABASE_URL = resolved_database_url
        self.cfg.BASE_DIR = resolved_base_dir

        self.db = Database(cfg=self.cfg)

        self.active_session_id: str | None = None
        self.active_title: str = "Yeni Sohbet"
        self.active_user_id: str | None = None
        self.active_username: str | None = None
        self._turns: list[dict[str, Any]] = []
        self._last_file: str | None = None

        self._dirty = False
        self._initialized = False
        self._init_lock: asyncio.Lock | None = None

    def _require_active_user(self) -> str:
        if not self.active_user_id:
            raise MemoryAuthError("Authenticated user context is required for memory operations.")
        return self.active_user_id

    # ─────────────────────────────────────────────
    #  ASYNC ÇEKİRDEK
    # ─────────────────────────────────────────────

    async def initialize(self) -> None:
        await self.db.connect()
        await self.db.init_schema()
        self.active_user_id = None
        self.active_username = None
        self._initialized = True

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if not self._initialized:
                await self.initialize()

    async def get_all_sessions(self) -> list[dict[str, Any]]:
        await self._ensure_initialized()
        user_id = self._require_active_user()
        rows = await self.db.list_sessions(user_id)
        return [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at,
                "message_count": len(await self.db.get_session_messages(r.id)),
            }
            for r in rows
        ]

    async def create_session(self, title: str = "Yeni Sohbet") -> str:
        await self._ensure_initialized()
        user_id = self._require_active_user()
        row = await self.db.create_session(user_id, title)
        self.active_session_id = row.id
        self.active_title = row.title
        self._turns = []
        self._last_file = None
        self._dirty = False
        logger.info("Yeni oturum oluşturuldu: %s - %s", row.id, row.title)
        return row.id

    async def load_session(self, session_id: str) -> bool:
        await self._ensure_initialized()
        user_id = self._require_active_user()
        row = await self.db.load_session(session_id, user_id)
        if not row:
            logger.warning("Oturum bulunamadı: %s", session_id)
            return False

        messages = await self.db.get_session_messages(session_id)
        with self._lock:
            self.active_session_id = row.id
            self.active_title = row.title
            self._turns = [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": self._safe_ts(m.created_at),
                    "tokens_used": m.tokens_used,
                }
                for m in messages
            ]
        logger.info("Oturum yüklendi: %s (%d mesaj)", session_id, len(self._turns))
        return True

    async def delete_session(self, session_id: str) -> bool:
        await self._ensure_initialized()
        user_id = self._require_active_user()
        ok = await self.db.delete_session(session_id, user_id)
        if not ok:
            return False

        if self.active_session_id == session_id:
            sessions = await self.get_all_sessions()
            if sessions:
                await self.load_session(sessions[0]["id"])
            else:
                await self.create_session("Yeni Sohbet")
        return True

    async def update_title(self, new_title: str) -> None:
        await self._ensure_initialized()
        if not self.active_session_id:
            return
        with self._lock:
            self.active_title = new_title
        await self.db.update_session_title(self.active_session_id, new_title)

    async def add(self, role: str, content: str | None) -> None:
        await self._ensure_initialized()
        self._require_active_user()
        if not self.active_session_id:
            await self.create_session("Yeni Sohbet")

        resolved_content = content if content is not None else ""
        now = time.time()
        with self._lock:
            self._turns.append({"role": role, "content": resolved_content, "timestamp": now})
            if len(self._turns) > self.max_turns * 2:
                self._turns = self._turns[-(self.max_turns * 2) :]
        session_id = self.active_session_id
        if not session_id:
            return
        await self.db.add_message(session_id, role, resolved_content, tokens_used=0)
        self._dirty = False

    async def get_history(self, n_last: int | None = None) -> list[dict[str, Any]]:
        await self._ensure_initialized()
        with self._lock:
            turns = list(self._turns)
        return turns if n_last is None else turns[-n_last:]

    async def set_active_user(self, user_id: str, username: str | None = None) -> None:
        await self._ensure_initialized()
        ensure_user_with_id = getattr(self.db, "ensure_user_id", None)
        if callable(ensure_user_with_id):
            await ensure_user_with_id(user_id=user_id, username=username or user_id)
        self.active_user_id = user_id
        self.active_username = username
        sessions = await self.db.list_sessions(user_id)
        if sessions:
            await self.load_session(sessions[0].id)
        else:
            await self.create_session("Yeni Sohbet")

    # ─────────────────────────────────────────────
    #  MEVCUT API (değişmeden)
    # ─────────────────────────────────────────────

    def get_messages_for_llm(self) -> list[dict[str, str]]:
        with self._lock:
            return [{"role": t["role"], "content": t["content"]} for t in self._turns]

    def set_last_file(self, path: str) -> None:
        with self._lock:
            self._last_file = path
            self._dirty = True

    def get_last_file(self) -> str | None:
        with self._lock:
            return self._last_file

    def _estimate_tokens(self) -> int:
        total_text = "".join(t.get("content", "") for t in self._turns)
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(total_text))
        except Exception:
            return int(len(total_text) / 3.5)

    def needs_summarization(self) -> bool:
        with self._lock:
            threshold = int(self.max_turns * 2 * 0.8)
            token_est = self._estimate_tokens()
            return len(self._turns) >= threshold or token_est > 6000

    async def apply_summary(self, summary_text: str) -> None:
        await self._ensure_initialized()
        with self._lock:
            kept_turns = self._turns[-self.keep_last :] if self.keep_last > 0 else []
            summary_turns = [
                {
                    "role": "user",
                    "content": "[Önceki konuşmaların özeti istendi]",
                    "timestamp": time.time() - 2,
                },
                {
                    "role": "assistant",
                    "content": f"[KONUŞMA ÖZETİ]\n{summary_text}",
                    "timestamp": time.time() - 1,
                },
            ]
            compact_turns = summary_turns + kept_turns
            self._turns = compact_turns

        # Session'ı temizleyip özetlenmiş mesajları tekrar yaz
        sid = self.active_session_id
        uid = self.active_user_id
        title = self.active_title
        if sid and uid:
            await self.db.delete_session(sid, uid)
            await self.create_session(title)
            for turn in compact_turns:
                await self.add(turn["role"], turn["content"])

    async def clear(self) -> None:
        await self._ensure_initialized()
        with self._lock:
            self._turns.clear()
            self._last_file = None
        sid = self.active_session_id
        title = self.active_title
        if sid:
            await self.db.delete_session(sid, self.active_user_id)
            await self.create_session(title)

    @staticmethod
    def _parse_iso_ts(value: str) -> float:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    @staticmethod
    def _build_compaction_summary(title: str, messages: Sequence[MessageRecord]) -> str:
        user_points: list[str] = []
        assistant_points: list[str] = []
        code_refs = 0
        for item in messages:
            role = str(getattr(item, "role", "") or "")
            content = str(getattr(item, "content", "") or "").strip()
            if not content:
                continue
            if "```" in content or ".py" in content or ".ts" in content or "/api/" in content:
                code_refs += 1
            cleaned = " ".join(content.split())
            if role == "user" and len(user_points) < 3:
                user_points.append(cleaned[:180])
            elif role == "assistant" and len(assistant_points) < 3:
                assistant_points.append(cleaned[:180])

        lines = [
            f"Oturum başlığı: {title}",
            f"Toplam mesaj: {len(messages)}",
            f"Kod/araç referansı görülen mesaj sayısı: {code_refs}",
        ]
        if user_points:
            lines.append("Öne çıkan kullanıcı istekleri:")
            lines.extend(f"- {item}" for item in user_points)
        if assistant_points:
            lines.append("Öne çıkan SİDAR çıktıları:")
            lines.extend(f"- {item}" for item in assistant_points)
        return "\n".join(lines)

    async def compact_session(
        self,
        *,
        user_id: str,
        session_id: str,
        keep_last: int | None = None,
        min_messages: int = 12,
    ) -> dict[str, object]:
        """Belirli bir oturumu özetleyip son birkaç mesajı koruyarak sıkıştırır."""
        await self._ensure_initialized()
        session = await self.db.load_session(session_id, user_id)
        if not session:
            return {"session_id": session_id, "status": "missing", "messages_before": 0}

        messages = await self.db.get_session_messages(session_id)
        if len(messages) < max(1, int(min_messages or 1)):
            return {
                "session_id": session_id,
                "status": "skipped",
                "messages_before": len(messages),
                "reason": "message_threshold",
            }

        keep_count = self.keep_last if keep_last is None else max(0, int(keep_last))
        kept_messages = messages[-keep_count:] if keep_count > 0 else []
        summary_text = self._build_compaction_summary(session.title, messages)
        compact_turns: list[dict[str, object]] = [
            {"role": "user", "content": "[GECE DÖNGÜSÜ] Önceki konuşmalar sıkıştırıldı."},
            {"role": "assistant", "content": f"[GECE KONSOLİDASYON ÖZETİ]\n{summary_text}"},
        ]
        compact_turns.extend(
            {"role": str(item.role), "content": str(item.content)} for item in kept_messages
        )
        written = await self.db.replace_session_messages(session_id, compact_turns)

        if self.active_user_id == user_id and self.active_session_id == session_id:
            with self._lock:
                self._turns = [
                    {"role": item["role"], "content": item["content"], "timestamp": time.time()}
                    for item in compact_turns
                ]

        return {
            "session_id": session_id,
            "status": "compacted",
            "messages_before": len(messages),
            "messages_after": written,
            "summary_preview": summary_text[:240],
        }

    async def run_nightly_consolidation(
        self,
        *,
        keep_recent_sessions: int = 2,
        min_messages: int = 12,
    ) -> dict[str, object]:
        """Tüm kullanıcı oturumlarında eski konuşmaları özetleyip sıkıştırır."""
        await self._ensure_initialized()
        try:
            users = await self.db.list_users_with_quotas()
            user_ids = [
                str(item.get("id", "") or "").strip()
                for item in users
                if str(item.get("id", "") or "").strip()
            ]
        except Exception:
            user_ids = []
        if self.active_user_id and self.active_user_id not in user_ids:
            user_ids.append(self.active_user_id)

        reports: list[dict[str, object]] = []
        compacted_session_ids: list[str] = []
        normalized_keep = max(0, int(keep_recent_sessions or 0))
        for user_id in user_ids:
            sessions = await self.db.list_sessions(user_id)
            for index, session in enumerate(sessions):
                if index < normalized_keep:
                    continue
                report = await self.compact_session(
                    user_id=user_id,
                    session_id=session.id,
                    min_messages=min_messages,
                )
                reports.append(report)
                if report.get("status") == "compacted":
                    compacted_session_ids.append(str(report.get("session_id", "")))

        compacted = [item for item in reports if item.get("status") == "compacted"]
        return {
            "status": "completed",
            "users_scanned": len(user_ids),
            "sessions_compacted": len(compacted),
            "session_ids": compacted_session_ids,
            "reports": reports,
        }

    def force_save(self) -> None:
        # DB yazımı add/update sırasında anlık yapılıyor.
        self._dirty = False

    def _save(self, force: bool = False) -> None:
        # Geriye dönük çağrılar için no-op.
        if force:
            self.force_save()

    def _cleanup_broken_files(self, max_age_days: int = 7, max_files: int = 50) -> None:
        # DB modunda legacy dosya karantinası kullanılmıyor.
        return

    @staticmethod
    def _safe_ts(iso_text: str) -> float:
        try:
            from datetime import datetime

            return datetime.fromisoformat(str(iso_text).replace("Z", "+00:00")).timestamp()
        except Exception as exc:
            logger.debug("ISO zaman parse edilemedi, current time kullanılacak: %s", exc)
            return time.time()

    def __del__(self) -> None:
        try:
            self.force_save()
        except Exception as exc:
            logger.debug("Memory force_save çağrısı __del__ içinde başarısız: %s", exc)

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)

    def __repr__(self) -> str:
        return f"<ConversationMemory session={self.active_session_id} turns={len(self._turns)}>"
