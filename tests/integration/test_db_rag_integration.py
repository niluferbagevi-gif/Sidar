"""Database + RAG entegrasyon senaryoları."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("jwt")

from core.db import Database
from core.rag import DocumentStore


def _build_cfg(tmp_path: Path):
    return SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'integration.db'}",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=3,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET="integration-secret",
        JWT_ALGORITHM="HS256",
        RAG_DIR=str(tmp_path / "rag"),
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=256,
        RAG_CHUNK_OVERLAP=24,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
    )


def test_database_messages_can_be_indexed_and_searched_in_rag(tmp_path):
    cfg = _build_cfg(tmp_path)

    async def _run_case() -> None:
        db = Database(cfg)
        docs = DocumentStore(
            Path(cfg.RAG_DIR),
            top_k=cfg.RAG_TOP_K,
            chunk_size=cfg.RAG_CHUNK_SIZE,
            chunk_overlap=cfg.RAG_CHUNK_OVERLAP,
            use_gpu=cfg.USE_GPU,
            gpu_device=cfg.GPU_DEVICE,
            mixed_precision=cfg.GPU_MIXED_PRECISION,
            cfg=cfg,
        )
        try:
            await db.connect()
            await db.init_schema()

            user = await db.create_user("integration_user", password="integration-pass")
            session = await db.create_session(user.id, "RAG senaryosu")
            await db.add_message(session.id, "user", "AWS alarm eşiğini 80 olarak ayarla")
            await db.add_message(session.id, "assistant", "Alarm eşiği 80 olarak güncellendi")

            history = await db.get_session_messages(session.id)
            history_text = "\n".join(message.content for message in history)
            doc_id = await docs.add_document(
                title=f"session-{session.id}",
                content=history_text,
                source="db://messages",
                tags=["integration", "db", "rag"],
                session_id=session.id,
            )
            assert doc_id

            ok, result = await docs.search("alarm eşiği kaç", session_id=session.id)
            assert ok is True
            assert "80" in result
        finally:
            await db.close()

    asyncio.run(_run_case())
