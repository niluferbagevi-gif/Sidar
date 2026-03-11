import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.db import Database


def test_database_sqlite_fallback_and_schema_crud(tmp_path):
    db_path = tmp_path / "sidar_test.db"
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
        DB_POOL_SIZE=3,
        BASE_DIR=tmp_path,
    )

    async def _run():
        db = Database(cfg=cfg)
        await db.connect()
        await db.init_schema()

        user = await db.create_user("alice", role="admin")
        session = await db.create_session(user.id, "İlk Oturum")
        msg = await db.add_message(session.id, "user", "Merhaba", tokens_used=12)
        rows = await db.get_session_messages(session.id)

        await db.close()

        return user, session, msg, rows

    user, session, msg, rows = asyncio.run(_run())

    assert user.username == "alice"
    assert session.user_id == user.id
    assert msg.tokens_used == 12
    assert len(rows) == 1
    assert rows[0].content == "Merhaba"
    assert db_path.exists()


def test_database_defaults_to_project_sqlite_when_url_missing(tmp_path):
    cfg = SimpleNamespace(
        DATABASE_URL="",
        DB_POOL_SIZE=2,
        BASE_DIR=tmp_path,
    )
    db = Database(cfg=cfg)
    assert db._backend == "sqlite"
    assert str(db._sqlite_path).endswith("data/sidar.db")

def test_database_auth_register_and_token(tmp_path):
    db_path = tmp_path / "sidar_auth.db"
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
        DB_POOL_SIZE=2,
        BASE_DIR=tmp_path,
    )

    async def _run():
        db = Database(cfg=cfg)
        await db.connect()
        await db.init_schema()

        user = await db.register_user("bob", "strong-pass")
        auth_ok = await db.authenticate_user("bob", "strong-pass")
        auth_fail = await db.authenticate_user("bob", "wrong")
        token = await db.create_auth_token(user.id)
        token_user = await db.get_user_by_token(token.token)

        await db.close()
        return user, auth_ok, auth_fail, token_user

    user, auth_ok, auth_fail, token_user = asyncio.run(_run())

    assert user.username == "bob"
    assert auth_ok is not None
    assert auth_fail is None
    assert token_user is not None
    assert token_user.id == user.id