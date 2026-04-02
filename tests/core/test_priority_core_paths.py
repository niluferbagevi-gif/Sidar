from __future__ import annotations

from types import SimpleNamespace

import importlib.util
import sys
import types

import pytest

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

from core.db import Database
from core.rag import DocumentStore


class _FakeCollection:
    def __init__(self) -> None:
        self.deleted_where: list[dict[str, str]] = []
        self.upserts: list[dict[str, object]] = []

    def delete(self, *, where: dict[str, str]) -> None:
        self.deleted_where.append(where)

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)


def test_rag_add_document_runs_chunking_and_vector_upsert(tmp_path) -> None:
    import asyncio

    store = DocumentStore(tmp_path / "rag", cfg=SimpleNamespace(BASE_DIR=tmp_path, AI_PROVIDER="ollama"))
    fake_collection = _FakeCollection()
    store._chroma_available = True
    store.collection = fake_collection

    content = "A" * 120 + "\n\n" + "B" * 120
    doc_id = asyncio.run(store.add_document("Kritik Doküman", content, source="unit://test", tags=["priority"]))

    assert doc_id in store._index
    assert fake_collection.deleted_where, "Önce parent bazlı delete çağrısı bekleniyor"
    assert fake_collection.upserts, "Chunk'lar vektör katmanına upsert edilmelidir"
    first_upsert = fake_collection.upserts[0]
    assert len(first_upsert["ids"]) == len(first_upsert["documents"]) >= 1


def test_db_schema_migration_and_left_join_quota_flow(tmp_path) -> None:
    import asyncio

    async def _run() -> tuple[list[dict[str, object]], int]:
        cfg = SimpleNamespace(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
            BASE_DIR=tmp_path,
            DB_SCHEMA_VERSION_TABLE="schema_versions",
            DB_SCHEMA_TARGET_VERSION=3,
            JWT_SECRET_KEY="x",
            JWT_ALGORITHM="HS256",
            JWT_TTL_DAYS=7,
        )
        db = Database(cfg)
        await db.connect()
        await db.init_schema()

        alice = await db.create_user("alice", password="secret-123")
        await db.create_user("bob", password="secret-456")
        await db.upsert_user_quota(alice.id, daily_token_limit=100, daily_request_limit=5)
        users = await db.list_users_with_quotas()

        def _max_version() -> int:
            assert db._sqlite_conn is not None
            row = db._sqlite_conn.execute(
                f"SELECT MAX(version) AS v FROM {db._schema_version_table_quoted}"
            ).fetchone()
            return int((row["v"] if row else 0) or 0)

        max_version = await db._run_sqlite_op(_max_version)
        await db.close()
        return users, max_version

    users, max_version = asyncio.run(_run())
    by_name = {row["username"]: row for row in users}
    assert by_name["alice"]["daily_token_limit"] == 100
    assert by_name["bob"]["daily_token_limit"] == 0
    assert max_version == 3


def test_db_run_sqlite_op_rolls_back_on_exception(tmp_path) -> None:
    import asyncio

    async def _run() -> None:
        cfg = SimpleNamespace(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'rollback.sqlite'}",
            BASE_DIR=tmp_path,
            DB_SCHEMA_VERSION_TABLE="schema_versions",
            DB_SCHEMA_TARGET_VERSION=1,
        )
        db = Database(cfg)
        await db.connect()
        await db.init_schema()

        def _failing_txn() -> None:
            assert db._sqlite_conn is not None
            db._sqlite_conn.execute(
                "INSERT INTO users (id, username, role, created_at) VALUES (?, ?, ?, ?)",
                ("u-rollback", "temp-user", "user", "2026-01-01T00:00:00+00:00"),
            )
            raise RuntimeError("forced failure")

        with pytest.raises(RuntimeError, match="forced failure"):
            await db._run_sqlite_op(_failing_txn)

        def _count_user() -> int:
            assert db._sqlite_conn is not None
            row = db._sqlite_conn.execute("SELECT COUNT(*) AS c FROM users WHERE username=?", ("temp-user",)).fetchone()
            return int((row["c"] if row else 0) or 0)

        count = await db._run_sqlite_op(_count_user)
        await db.close()
        assert count == 0

    asyncio.run(_run())
