import asyncio
from pathlib import Path

from core.db import Database
from core.memory import ConversationMemory


def test_memory_requires_authenticated_user_context(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    assert mem.active_user_id is None
    assert mem.active_session_id is None

    asyncio.run(mem.initialize())
    user = asyncio.run(mem.db.ensure_user("alice", role="user"))
    asyncio.run(mem.set_active_user(user.id, user.username))
    assert mem.active_user_id == user.id
    assert mem.active_session_id

    asyncio.run(mem.add("user", "merhaba"))
    asyncio.run(mem.add("assistant", "selam"))

    history = asyncio.run(mem.get_history())
    assert len(history) >= 2
    assert history[-1]["content"] == "selam"


def test_memory_async_session_methods_work(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        await mem.initialize()
        user = await mem.db.ensure_user("bob", role="user")
        await mem.set_active_user(user.id, user.username)
        sid = await mem.create_session("DB Session")
        await mem.add("user", "u1")
        await mem.add("assistant", "a1")
        ok = await mem.load_session(sid)
        sessions = await mem.get_all_sessions()
        return ok, sessions, await mem.get_history()

    ok, sessions, hist = asyncio.run(_run())
    assert ok is True
    assert any(s["id"] for s in sessions)
    assert len(hist) == 2


def test_db_schema_version_table_initialized(tmp_path: Path):
    class _Cfg:
        DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
        DB_POOL_SIZE = 2
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 2
        BASE_DIR = tmp_path

    db = Database(cfg=_Cfg())

    async def _run():
        await db.connect()
        await db.init_schema()
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute("SELECT MAX(version) AS v FROM schema_versions")
        row = cur.fetchone()
        await db.close()
        return int((row["v"] if row else 0) or 0)

    max_v = asyncio.run(_run())
    assert max_v == 2


def test_run_sqlite_op_raises_if_not_connected(tmp_path: Path):
    class _Cfg:
        DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
        DB_POOL_SIZE = 2
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = tmp_path

    db = Database(cfg=_Cfg())

    async def _run():
        return await db._run_sqlite_op(lambda: 1)

    try:
        asyncio.run(_run())
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "SQLite bağlantısı başlatılmadı" in str(exc)
    assert raised is True


def test_ensure_default_prompt_registry_swallows_upsert_errors(tmp_path: Path, monkeypatch):
    class _Cfg:
        DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
        DB_POOL_SIZE = 2
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = tmp_path

    db = Database(cfg=_Cfg())

    async def _run():
        await db.connect()
        await db.init_schema()

        async def _no_prompt(_role):
            return None

        async def _boom(**_kwargs):
            raise RuntimeError("upsert failed")

        monkeypatch.setattr(db, "get_active_prompt", _no_prompt)
        monkeypatch.setattr(db, "upsert_prompt", _boom)

        # should not raise due to internal exception swallow
        await db.ensure_default_prompt_registry()
        await db.close()

    asyncio.run(_run())


def test_ensure_default_prompt_registry_returns_early_when_loader_missing(tmp_path: Path, monkeypatch):
    class _Cfg:
        DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
        DB_POOL_SIZE = 2
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = tmp_path

    db = Database(cfg=_Cfg())

    class _Spec:
        loader = None

    async def _no_prompt(_role):
        return None

    async def _unexpected_upsert(**_kwargs):
        raise AssertionError("upsert should not run when default prompt cannot be loaded")

    monkeypatch.setattr("importlib.util.spec_from_file_location", lambda *_a, **_k: _Spec())
    monkeypatch.setattr(db, "get_active_prompt", _no_prompt)
    monkeypatch.setattr(db, "upsert_prompt", _unexpected_upsert)

    asyncio.run(db.ensure_default_prompt_registry())