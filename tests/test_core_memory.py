import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _load_memory_module():
    spec = importlib.util.spec_from_file_location("sidar_core_memory", Path("core/memory.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_memory_sliding_window(tmp_path: Path):
    """Kayan pencere stratejisi son 1 turu korur ve özet bloklarını ekler."""
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    memory = ConversationMemory(file_path=tmp_path / "test_session.json", max_turns=50, keep_last=2)
    asyncio.run(memory.initialize())
    user = asyncio.run(memory.db.ensure_user("window_user", role="user"))
    asyncio.run(memory.set_active_user(user.id, user.username))

    for i in range(1, 6):
        asyncio.run(memory.add("user", f"Soru {i}"))
        asyncio.run(memory.add("assistant", f"Cevap {i}"))

    assert len(asyncio.run(memory.get_history())) == 10

    asyncio.run(memory.apply_summary("Bu bir test özetidir."))
    turns = asyncio.run(memory.get_history())

    assert len(turns) == 4
    assert "özeti istendi" in turns[0]["content"]
    assert "Bu bir test özetidir." in turns[1]["content"]
    assert turns[2]["content"] == "Soru 5"
    assert turns[3]["content"] == "Cevap 5"

def test_parse_iso_ts_returns_epoch_seconds_and_invalid_fallback(tmp_path: Path):
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    parsed = ConversationMemory._parse_iso_ts("2026-03-20T12:34:56Z")
    expected = datetime(2026, 3, 20, 12, 34, 56, tzinfo=timezone.utc).timestamp()

    assert parsed == expected
    assert ConversationMemory._parse_iso_ts("not-an-iso-date") == 0.0


def test_build_compaction_summary_collects_points_and_code_refs():
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    messages = [
        SimpleNamespace(role="user", content=" İlk istek /api/chat uç noktasını kontrol et. "),
        SimpleNamespace(role="assistant", content="Yanıt: `main.py` içinde hata var. ```py```"),
        SimpleNamespace(role="user", content="İkinci istek src/app.ts dosyasını gözden geçir."),
        SimpleNamespace(role="assistant", content="Üçüncü yanıtta tools.py dosyasını da güncelledim."),
        SimpleNamespace(role="user", content="   "),
    ]

    summary = ConversationMemory._build_compaction_summary("Kritik Oturum", messages)

    assert "Oturum başlığı: Kritik Oturum" in summary
    assert "Toplam mesaj: 5" in summary
    assert "Kod/araç referansı görülen mesaj sayısı: 4" in summary
    assert "Öne çıkan kullanıcı istekleri:" in summary
    assert "Öne çıkan SİDAR çıktıları:" in summary
    assert "İlk istek /api/chat uç noktasını kontrol et." in summary
    assert "Yanıt: `main.py` içinde hata var. ```py```" in summary


async def _make_initialized_memory(tmp_path: Path):
    mod = _load_memory_module()
    memory = mod.ConversationMemory(file_path=tmp_path / "test_session.json", max_turns=20, keep_last=2)
    await memory.initialize()
    user = await memory.db.ensure_user("core_memory_user", role="user")
    await memory.set_active_user(user.id, user.username)
    return mod, memory, user


def test_compact_session_returns_missing_for_unknown_session(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, user = await _make_initialized_memory(tmp_path)
        memory.db.load_session = AsyncMock(return_value=None)
        memory.db.get_session_messages = AsyncMock()

        report = await memory.compact_session(
            user_id=user.id,
            session_id="00000000-0000-0000-0000-000000000000",
            min_messages=2,
        )

        assert report == {
            "session_id": "00000000-0000-0000-0000-000000000000",
            "status": "missing",
            "messages_before": 0,
        }
        memory.db.get_session_messages.assert_not_called()

    asyncio.run(_run())


def test_compact_session_replaces_active_session_turns(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, user = await _make_initialized_memory(tmp_path)
        session_id = memory.active_session_id
        assert session_id is not None

        for idx in range(3):
            await memory.add("user", f"Soru {idx}")
            await memory.add("assistant", f"Cevap {idx}")

        report = await memory.compact_session(
            user_id=user.id,
            session_id=session_id,
            keep_last=2,
            min_messages=2,
        )

        turns = await memory.get_history()
        assert report["status"] == "compacted"
        assert report["messages_before"] == 6
        assert report["messages_after"] == 4
        assert len(turns) == 4
        assert turns[0]["content"] == "[GECE DÖNGÜSÜ] Önceki konuşmalar sıkıştırıldı."
        assert turns[1]["content"].startswith("[GECE KONSOLİDASYON ÖZETİ]\nOturum başlığı: Yeni Sohbet")
        assert turns[2]["content"] == "Soru 2"
        assert turns[3]["content"] == "Cevap 2"

    asyncio.run(_run())


def test_run_nightly_consolidation_falls_back_to_active_user_when_user_listing_fails(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, _user = await _make_initialized_memory(tmp_path)
        old_session_id = memory.active_session_id
        assert old_session_id is not None

        for idx in range(2):
            await memory.add("user", f"Eski istek {idx}")
            await memory.add("assistant", f"Eski yanıt {idx}")

        recent_session_id = await memory.create_session("Yeni Sohbet")
        await memory.add("user", "Yeni istek")
        await memory.add("assistant", "Yeni yanıt")

        memory.db.list_users_with_quotas = AsyncMock(side_effect=RuntimeError("quota lookup failed"))

        report = await memory.run_nightly_consolidation(
            keep_recent_sessions=1,
            min_messages=2,
        )

        assert report["status"] == "completed"
        assert report["users_scanned"] == 1
        assert report["sessions_compacted"] == 1
        assert report["session_ids"] == [old_session_id]
        assert recent_session_id not in report["session_ids"]
        assert any(item["status"] == "compacted" for item in report["reports"])

    asyncio.run(_run())