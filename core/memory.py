"""Sidar Project - Konuşma Belleği (DB tabanlı, çoklu kullanıcı hazırlığı)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from config import Config
from core.db import Database

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Thread-safe konuşma belleği; kalıcılık katmanı olarak DB kullanır."""

    DEFAULT_USERNAME = "default_admin"

    def __init__(self, file_path: Path, max_turns: int = 20,
                 encryption_key: str = "", keep_last: int = 4) -> None:
        # Geriye dönük uyumluluk: bazı testler/senaryolar bu dizini bekliyor.
        self.sessions_dir = file_path.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self.max_turns = max_turns
        self.keep_last = keep_last
        self._lock = threading.RLock()

        self.cfg = Config()
        # Bellek katmanı için varsayılan DB yolu, verilen file_path köküne bağlanır.
        if not getattr(self.cfg, "DATABASE_URL", ""):
            self.cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(file_path.parent / 'sidar_memory.db').as_posix()}"
        elif str(getattr(self.cfg, "DATABASE_URL", "")).endswith("data/sidar.db"):
            self.cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(file_path.parent / 'sidar_memory.db').as_posix()}"
        self.cfg.BASE_DIR = file_path.parent

        self.db = Database(cfg=self.cfg)

        self.active_session_id: Optional[str] = None
        self.active_title: str = "Yeni Sohbet"
        self.active_user_id: Optional[str] = None
        self._turns: List[Dict] = []
        self._last_file: Optional[str] = None

        self._dirty = False
        self._init_db_state()

    # ─────────────────────────────────────────────
    #  ASYNC ÇEKİRDEK
    # ─────────────────────────────────────────────

    def _run_coro_sync(self, coro):
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop:
            return asyncio.run(coro)

        box = {"result": None, "error": None}

        def _runner():
            try:
                box["result"] = asyncio.run(coro)
            except Exception as exc:  # pragma: no cover
                box["error"] = exc

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        if box["error"]:
            raise box["error"]
        return box["result"]

    async def _ainit_db(self) -> None:
        await self.db.connect()
        await self.db.init_schema()
        user = await self.db.ensure_user(self.DEFAULT_USERNAME, role="admin")
        self.active_user_id = user.id

        sessions = await self.db.list_sessions(user.id)
        if sessions:
            await self.aload_session(sessions[0].id)
        else:
            await self.acreate_session("İlk Sohbet")

    def _init_db_state(self) -> None:
        self._run_coro_sync(self._ainit_db())

    async def aget_all_sessions(self) -> List[Dict]:
        if not self.active_user_id:
            return []
        rows = await self.db.list_sessions(self.active_user_id)
        return [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at,
                "message_count": len(await self.db.get_session_messages(r.id)),
            }
            for r in rows
        ]

    async def acreate_session(self, title: str = "Yeni Sohbet") -> str:
        if not self.active_user_id:
            user = await self.db.ensure_user(self.DEFAULT_USERNAME, role="admin")
            self.active_user_id = user.id

        row = await self.db.create_session(self.active_user_id, title)
        self.active_session_id = row.id
        self.active_title = row.title
        self._turns = []
        self._last_file = None
        self._dirty = False
        logger.info("Yeni oturum oluşturuldu: %s - %s", row.id, row.title)
        return row.id

    async def aload_session(self, session_id: str) -> bool:
        row = await self.db.load_session(session_id, self.active_user_id)
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

    async def adelete_session(self, session_id: str) -> bool:
        ok = await self.db.delete_session(session_id, self.active_user_id)
        if not ok:
            return False

        if self.active_session_id == session_id:
            sessions = await self.aget_all_sessions()
            if sessions:
                await self.aload_session(sessions[0]["id"])
            else:
                await self.acreate_session("Yeni Sohbet")
        return True

    async def aupdate_title(self, new_title: str) -> None:
        if not self.active_session_id:
            return
        with self._lock:
            self.active_title = new_title
        await self.db.update_session_title(self.active_session_id, new_title)

    async def aadd(self, role: str, content: str) -> None:
        if not self.active_session_id:
            await self.acreate_session("Yeni Sohbet")

        now = time.time()
        with self._lock:
            self._turns.append({"role": role, "content": content, "timestamp": now})
            if len(self._turns) > self.max_turns * 2:
                self._turns = self._turns[-(self.max_turns * 2):]
        await self.db.add_message(self.active_session_id, role, content, tokens_used=0)
        self._dirty = False

    async def aget_history(self, n_last: Optional[int] = None) -> List[Dict]:
        with self._lock:
            turns = list(self._turns)
        return turns if n_last is None else turns[-n_last:]

    # ─────────────────────────────────────────────
    #  SYNC UYUMLULUK KATMANI
    # ─────────────────────────────────────────────

    def get_all_sessions(self) -> List[Dict]:
        return self._run_coro_sync(self.aget_all_sessions())

    def create_session(self, title: str = "Yeni Sohbet") -> str:
        return self._run_coro_sync(self.acreate_session(title))

    def load_session(self, session_id: str) -> bool:
        return self._run_coro_sync(self.aload_session(session_id))

    def delete_session(self, session_id: str) -> bool:
        return self._run_coro_sync(self.adelete_session(session_id))

    def update_title(self, new_title: str) -> None:
        self._run_coro_sync(self.aupdate_title(new_title))

    def add(self, role: str, content: str) -> None:
        self._run_coro_sync(self.aadd(role, content))

    def get_history(self, n_last: Optional[int] = None) -> List[Dict]:
        return self._run_coro_sync(self.aget_history(n_last))

    # ─────────────────────────────────────────────
    #  MEVCUT API (değişmeden)
    # ─────────────────────────────────────────────

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        with self._lock:
            return [{"role": t["role"], "content": t["content"]} for t in self._turns]

    def set_last_file(self, path: str) -> None:
        with self._lock:
            self._last_file = path
            self._dirty = True

    def get_last_file(self) -> Optional[str]:
        with self._lock:
            return self._last_file

    def _estimate_tokens(self) -> int:
        total_text = "".join(t.get("content", "") for t in self._turns)
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(total_text))
        except ImportError:
            return int(len(total_text) / 3.5)

    def needs_summarization(self) -> bool:
        with self._lock:
            threshold = int(self.max_turns * 2 * 0.8)
            token_est = self._estimate_tokens()
            return len(self._turns) >= threshold or token_est > 6000

    def apply_summary(self, summary_text: str) -> None:
        with self._lock:
            kept_turns = self._turns[-self.keep_last:] if self.keep_last > 0 else []
            summary_turns = [
                {"role": "user", "content": "[Önceki konuşmaların özeti istendi]", "timestamp": time.time() - 2},
                {"role": "assistant", "content": f"[KONUŞMA ÖZETİ]\n{summary_text}", "timestamp": time.time() - 1},
            ]
            compact_turns = summary_turns + kept_turns
            self._turns = compact_turns

        # Session'ı temizleyip özetlenmiş mesajları tekrar yaz
        sid = self.active_session_id
        uid = self.active_user_id
        title = self.active_title
        if sid and uid:
            self._run_coro_sync(self.db.delete_session(sid, uid))
            self.create_session(title)
            for turn in compact_turns:
                self.add(turn["role"], turn["content"])

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()
            self._last_file = None
        sid = self.active_session_id
        title = self.active_title
        if sid:
            self._run_coro_sync(self.db.delete_session(sid, self.active_user_id))
            self.create_session(title)

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
        except Exception:
            return time.time()

    def __del__(self) -> None:
        try:
            self.force_save()
        except Exception:
            pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)

    def __repr__(self) -> str:
        return f"<ConversationMemory session={self.active_session_id} turns={len(self._turns)}>"
