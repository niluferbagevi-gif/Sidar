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


def test_build_compaction_summary_skips_user_section_when_only_assistant_messages_exist():
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    messages = [
        SimpleNamespace(role="assistant", content="İlk çıktı tools.py üzerinde güncelleme yaptı."),
        SimpleNamespace(role="assistant", content="İkinci çıktı /api/tasks sonucunu özetledi."),
    ]

    summary = ConversationMemory._build_compaction_summary("Asistan Oturumu", messages)

    assert "Öne çıkan kullanıcı istekleri:" not in summary
    assert "Öne çıkan SİDAR çıktıları:" in summary


def test_build_compaction_summary_skips_assistant_section_when_only_user_messages_exist():
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    messages = [
        SimpleNamespace(role="user", content="README.md ve src/app.ts dosyalarını incele."),
        SimpleNamespace(role="user", content="Lütfen /api/health cevabını da doğrula."),
    ]

    summary = ConversationMemory._build_compaction_summary("Kullanıcı Oturumu", messages)

    assert "Öne çıkan kullanıcı istekleri:" in summary
    assert "Öne çıkan SİDAR çıktıları:" not in summary


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


def test_ensure_initialized_creates_lock_and_calls_initialize(tmp_path: Path):
    async def _run() -> None:
        mod = _load_memory_module()
        memory = mod.ConversationMemory(file_path=tmp_path / "ensure_init.json", max_turns=5)
        memory.initialize = AsyncMock(side_effect=lambda: setattr(memory, "_initialized", True))

        assert memory._init_lock is None
        await memory._ensure_initialized()

        assert memory._init_lock is not None
        memory.initialize.assert_awaited_once()

    asyncio.run(_run())


def test_ensure_initialized_skips_initialize_when_lock_already_marks_memory_ready(tmp_path: Path):
    async def _run() -> None:
        mod = _load_memory_module()
        memory = mod.ConversationMemory(file_path=tmp_path / "ensure_ready.json", max_turns=5)
        memory.initialize = AsyncMock()

        class _Lock:
            async def __aenter__(self):
                memory._initialized = True

            async def __aexit__(self, exc_type, exc, tb):
                return False

        memory._initialized = False
        memory._init_lock = _Lock()

        await memory._ensure_initialized()

        memory.initialize.assert_not_awaited()

    asyncio.run(_run())


def test_compact_session_skips_when_message_count_is_below_threshold(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, user = await _make_initialized_memory(tmp_path)
        session_id = memory.active_session_id
        assert session_id is not None

        memory.db.load_session = AsyncMock(return_value=SimpleNamespace(title="Sess"))
        memory.db.get_session_messages = AsyncMock(
            return_value=[SimpleNamespace(role="user", content="yalnızca bir mesaj")]
        )
        memory.db.replace_session_messages = AsyncMock()

        report = await memory.compact_session(
            user_id=user.id,
            session_id=session_id,
            min_messages=3,
        )

        assert report == {
            "session_id": session_id,
            "status": "skipped",
            "messages_before": 1,
            "reason": "message_threshold",
        }
        memory.db.replace_session_messages.assert_not_called()

    asyncio.run(_run())


def test_delete_session_returns_true_without_switching_when_deleted_session_is_not_active(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, user = await _make_initialized_memory(tmp_path)
        memory.active_session_id = "active-session"
        memory.db.delete_session = AsyncMock(return_value=True)
        memory.get_all_sessions = AsyncMock()
        memory.load_session = AsyncMock()
        memory.create_session = AsyncMock()

        result = await memory.delete_session("other-session")

        assert result is True
        memory.db.delete_session.assert_awaited_once_with("other-session", user.id)
        memory.get_all_sessions.assert_not_awaited()
        memory.load_session.assert_not_awaited()
        memory.create_session.assert_not_awaited()

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


def test_apply_summary_skips_db_rewrite_when_session_or_user_is_missing(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, _user = await _make_initialized_memory(tmp_path)
        memory._turns = [
            {"role": "user", "content": "ilk", "timestamp": 1.0},
            {"role": "assistant", "content": "yanıt", "timestamp": 2.0},
        ]
        memory.active_session_id = None
        memory.active_user_id = None
        memory.db.delete_session = AsyncMock()
        memory.create_session = AsyncMock()
        memory.add = AsyncMock()

        await memory.apply_summary("özet")

        assert [turn["content"] for turn in memory._turns[:2]] == [
            "[Önceki konuşmaların özeti istendi]",
            "[KONUŞMA ÖZETİ]\nözet",
        ]
        memory.db.delete_session.assert_not_awaited()
        memory.create_session.assert_not_awaited()
        memory.add.assert_not_awaited()

    asyncio.run(_run())


def test_clear_skips_db_recreation_when_no_active_session_exists(tmp_path: Path):
    async def _run() -> None:
        _mod, memory, _user = await _make_initialized_memory(tmp_path)
        memory._turns = [{"role": "user", "content": "geçici", "timestamp": 1.0}]
        memory._last_file = "demo.py"
        memory.active_session_id = None
        memory.db.delete_session = AsyncMock()
        memory.create_session = AsyncMock()

        await memory.clear()

        assert memory._turns == []
        assert memory._last_file is None
        memory.db.delete_session.assert_not_awaited()
        memory.create_session.assert_not_awaited()

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
