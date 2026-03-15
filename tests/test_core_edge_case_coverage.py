import asyncio
import types
from pathlib import Path

from core.db import Database
from core.memory import ConversationMemory
from core.rag import DocumentStore


def test_rag_init_skips_chroma_when_dependency_missing(tmp_path: Path):
    original = DocumentStore._check_import
    try:
        DocumentStore._check_import = lambda self, name: False
        cfg = types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=100, RAG_CHUNK_OVERLAP=20, HF_TOKEN="", HF_HUB_OFFLINE=False)
        store = DocumentStore(tmp_path / "rag", cfg=cfg)
    finally:
        DocumentStore._check_import = original

    assert store._chroma_available is False
    assert store.chroma_client is None
    assert store.collection is None


def test_db_run_sqlite_op_recreates_lock_when_missing(tmp_path: Path):
    cfg = types.SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        BASE_DIR=tmp_path,
    )
    db = Database(cfg=cfg)

    async def _run():
        await db.connect()
        db._sqlite_lock = None
        out = await db._run_sqlite_op(lambda: 7)
        await db.close()
        return out

    assert asyncio.run(_run()) == 7


def test_memory_ensure_initialized_creates_lock_and_initializes_once(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=5)
    calls = {"n": 0}

    async def _fake_init():
        calls["n"] += 1
        mem._initialized = True

    mem._initialized = False
    mem._init_lock = None
    mem.initialize = _fake_init

    async def _run():
        await asyncio.gather(mem._ensure_initialized(), mem._ensure_initialized())

    asyncio.run(_run())
    assert mem._init_lock is not None
    assert calls["n"] == 1

def test_db_run_sqlite_op_raises_when_connection_uninitialized(tmp_path: Path):
    cfg = types.SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        BASE_DIR=tmp_path,
    )
    db = Database(cfg=cfg)

    async def _run():
        try:
            await db._run_sqlite_op(lambda: 1)
        except RuntimeError as exc:
            return str(exc)
        return ""

    assert "başlatılmadı" in asyncio.run(_run())