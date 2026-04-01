from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("jwt")

from core.entity_memory import EntityMemory
from core.memory import ConversationMemory, MemoryAuthError
from core.rag import DocumentStore


@pytest.mark.asyncio
async def test_rag_chunking_handles_small_and_large_texts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)
    mock_cfg = SimpleNamespace(
        RAG_CHUNK_SIZE=50,
        RAG_CHUNK_OVERLAP=10,
        RAG_VECTOR_BACKEND="chroma",
        ENABLE_GRAPH_RAG=False,
    )
    rag = DocumentStore(store_dir=tmp_path / "rag", chunk_size=50, chunk_overlap=10, cfg=mock_cfg)

    short = "kısa metin"
    assert rag._chunk_text(short) == [short]

    long_text = "A" * 130
    chunks = rag._chunk_text(long_text)
    assert len(chunks) >= 3
    assert all(1 <= len(chunk) <= 50 for chunk in chunks)


@pytest.mark.asyncio
async def test_conversation_memory_evicts_old_turns(tmp_path: Path):
    memory = ConversationMemory(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'memory.db').as_posix()}",
        base_dir=tmp_path,
        max_turns=2,
    )
    await memory.initialize()
    user = await memory.db.ensure_user("alice")
    await memory.set_active_user(user.id, user.username)

    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        await memory.add(role, f"msg-{i}")

    history = await memory.get_history()
    assert len(history) == 4
    assert history[0]["content"] == "msg-2"
    await memory.db.close()


@pytest.mark.asyncio
async def test_conversation_memory_requires_authenticated_user(tmp_path: Path):
    memory = ConversationMemory(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'memory_auth.db').as_posix()}",
        base_dir=tmp_path,
    )
    await memory.initialize()

    with pytest.raises(MemoryAuthError):
        await memory.create_session("Yetkisiz")

    await memory.db.close()


@pytest.mark.asyncio
async def test_entity_memory_eviction_keeps_latest_keys(tmp_path: Path):
    entity = EntityMemory(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'entity.db').as_posix()}",
        config=SimpleNamespace(ENABLE_ENTITY_MEMORY=True, ENTITY_MEMORY_TTL_DAYS=90, ENTITY_MEMORY_MAX_PER_USER=2),
    )
    await entity.initialize()

    assert await entity.upsert("u1", "k1", "v1") is True
    assert await entity.upsert("u1", "k2", "v2") is True
    assert await entity.upsert("u1", "k3", "v3") is True

    profile = await entity.get_profile("u1")
    assert "k1" not in profile
    assert set(profile.keys()) == {"k2", "k3"}
    await entity.close()
