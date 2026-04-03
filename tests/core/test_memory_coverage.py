from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

from core.memory import ConversationMemory, MemoryAuthError


def test_init_resolves_paths_and_requires_active_user(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace = tmp_path / "workspace"
        memory = ConversationMemory(
            database_url="",
            file_path=workspace / "legacy_history.json",
            keep_last=2,
        )

        try:
            assert memory.sessions_dir == workspace / "sessions"
            assert memory.cfg.BASE_DIR == workspace
            assert memory.cfg.DATABASE_URL.startswith("sqlite+aiosqlite:///")

            with pytest.raises(MemoryAuthError, match="Authenticated user context"):
                memory._require_active_user()
        finally:
            await memory.db.close()

    asyncio.run(_run())


def test_async_session_crud_and_history_flow(tmp_path: Path) -> None:
    async def _run() -> None:
        memory = ConversationMemory(
            database_url="sqlite+aiosqlite:///:memory:",
            base_dir=tmp_path,
            max_turns=2,
        )

        try:
            await memory.initialize()
            user = await memory.db.create_user("memory-user", password="secret")
            await memory.set_active_user(user.id, username=user.username)

            assert memory.active_session_id
            assert memory.active_title == "Yeni Sohbet"

            await memory.add("user", "merhaba")
            await memory.add("assistant", "selam")
            await memory.add("user", "kod bloğu ```python\nprint(1)\n```")

            history = await memory.get_history()
            assert len(history) == 3
            assert history[-1]["role"] == "user"

            sessions = await memory.get_all_sessions()
            assert len(sessions) == 1
            assert sessions[0]["message_count"] == 3

            loaded = await memory.load_session(memory.active_session_id)
            assert loaded is True
            llm_messages = memory.get_messages_for_llm()
            assert llm_messages[-1]["content"].startswith("kod bloğu")

            missing = await memory.load_session("missing-session")
            assert missing is False

            deleted = await memory.delete_session(memory.active_session_id)
            assert deleted is True
            assert memory.active_session_id is not None
        finally:
            await memory.db.close()

    asyncio.run(_run())


def test_apply_summary_keeps_recent_turns(tmp_path: Path) -> None:
    async def _run() -> None:
        memory = ConversationMemory(
            database_url="sqlite+aiosqlite:///:memory:",
            base_dir=tmp_path,
            keep_last=2,
        )

        try:
            await memory.initialize()
            user = await memory.db.create_user("summary-user", password="secret")
            await memory.set_active_user(user.id)

            await memory.add("user", "istek 1")
            await memory.add("assistant", "yanit 1")
            await memory.add("user", "istek 2")
            await memory.add("assistant", "yanit 2")

            await memory.apply_summary("Özet metni")

            history = await memory.get_history()
            assert len(history) == 4
            assert history[0]["content"].startswith("[Önceki konuşmaların özeti")
            assert "[KONUŞMA ÖZETİ]" in history[1]["content"]
            assert history[-2]["content"] == "istek 2"
            assert history[-1]["content"] == "yanit 2"

            db_messages = await memory.db.get_session_messages(memory.active_session_id)
            assert len(db_messages) == 4
        finally:
            await memory.db.close()

    asyncio.run(_run())


def test_compact_session_builds_code_reference_summary(tmp_path: Path) -> None:
    async def _run() -> None:
        memory = ConversationMemory(
            database_url="sqlite+aiosqlite:///:memory:",
            base_dir=tmp_path,
            keep_last=1,
        )

        try:
            await memory.initialize()
            user = await memory.db.create_user("compact-user", password="secret")
            await memory.set_active_user(user.id)

            await memory.add("user", "Acil: core/memory.py dosyasını incele")
            await memory.add("assistant", "```python\nprint('fix')\n```")
            await memory.add("user", "/api/messages endpointini de kontrol et")
            await memory.add("assistant", "Tamam, değişiklikleri uyguladım")

            result = await memory.compact_session(
                user_id=user.id,
                session_id=memory.active_session_id,
                keep_last=1,
                min_messages=3,
            )

            assert result["status"] == "compacted"
            assert result["messages_before"] == 4
            assert result["messages_after"] == 3
            assert "Kod/araç referansı" in result["summary_preview"]

            compacted_messages = await memory.db.get_session_messages(memory.active_session_id)
            assert compacted_messages[0].content.startswith("[GECE DÖNGÜSÜ]")
            assert "[GECE KONSOLİDASYON ÖZETİ]" in compacted_messages[1].content
            assert "core/memory.py" in compacted_messages[1].content
            assert compacted_messages[-1].content == "Tamam, değişiklikleri uyguladım"
        finally:
            await memory.db.close()

    asyncio.run(_run())


def test_run_nightly_consolidation_reports_compacted_sessions(tmp_path: Path) -> None:
    async def _run() -> None:
        memory = ConversationMemory(
            database_url="sqlite+aiosqlite:///:memory:",
            base_dir=tmp_path,
        )

        try:
            await memory.initialize()
            user = await memory.db.create_user("night-user", password="secret")
            await memory.set_active_user(user.id)

            first_session = memory.active_session_id
            for i in range(3):
                await memory.add("user", f"ilk oturum mesajı {i}")

            second_session = await memory.create_session("İkinci")
            for i in range(3):
                await memory.add("assistant", f"ikinci oturum mesajı {i}")

            report = await memory.run_nightly_consolidation(
                keep_recent_sessions=1,
                min_messages=3,
            )

            assert report["status"] == "completed"
            assert report["users_scanned"] == 1
            assert report["sessions_compacted"] == 1
            assert first_session in report["session_ids"]
            assert second_session not in report["session_ids"]
        finally:
            await memory.db.close()

    asyncio.run(_run())
