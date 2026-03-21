import asyncio
import sys
import time
import types

if "pydantic" not in sys.modules:
    pydantic_stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    pydantic_stub.BaseModel = _BaseModel
    pydantic_stub.Field = lambda *args, **kwargs: None
    pydantic_stub.ValidationError = ValueError
    sys.modules["pydantic"] = pydantic_stub

from agent.sidar_agent import SidarAgent
from core.memory import ConversationMemory
from core.rag import DocumentStore


def test_conversation_memory_nightly_consolidation_compacts_old_sessions(tmp_path):
    async def _run() -> None:
        mem = ConversationMemory(
            base_dir=tmp_path,
            file_path=tmp_path / "memory.json",
            max_turns=20,
            keep_last=2,
        )
        await mem.initialize()
        user = await mem.db.ensure_user("tester", role="user")
        await mem.set_active_user(user.id, user.username)

        old_session_id = await mem.create_session("Eski Oturum")
        for idx in range(4):
            await mem.add("user", f"istek {idx}")
            await mem.add("assistant", f"yanit {idx}")

        recent_session_id = await mem.create_session("Yeni Oturum")
        await mem.add("user", "son mesaj")
        await mem.add("assistant", "son yanit")

        report = await mem.run_nightly_consolidation(
            keep_recent_sessions=1,
            min_messages=4,
        )

        assert report["sessions_compacted"] == 1
        assert old_session_id in report["session_ids"]
        assert recent_session_id not in report["session_ids"]

        messages = await mem.db.get_session_messages(old_session_id)
        contents = [item.content for item in messages]
        assert contents[0] == "[GECE DÖNGÜSÜ] Önceki konuşmalar sıkıştırıldı."
        assert contents[1].startswith("[GECE KONSOLİDASYON ÖZETİ]\nOturum başlığı: Eski Oturum")
        assert len(messages) == 4

    asyncio.run(_run())


def test_document_store_consolidates_session_documents_and_adds_digest(tmp_path):
    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )
    store = DocumentStore(tmp_path / "rag", use_gpu=False, cfg=cfg)

    session_id = "sess-night"
    asyncio.run(store.add_document("Belge A", "alpha içerik", session_id=session_id))
    time.sleep(0.01)
    asyncio.run(store.add_document("Belge B", "beta içerik", session_id=session_id))
    time.sleep(0.01)
    asyncio.run(store.add_document("Belge C", "gamma içerik", session_id=session_id))

    report = store.consolidate_session_documents(session_id, keep_recent_docs=1)

    assert report["status"] == "completed"
    assert report["removed_docs"] == 2
    info = store.get_index_info(session_id=session_id)
    titles = {item["title"] for item in info}
    assert "Nightly Memory Digest (sess-night)" in titles
    assert len(info) == 2


def test_sidar_agent_nightly_maintenance_respects_idle_and_collects_reports(monkeypatch):
    async def _run() -> None:
        agent = SidarAgent.__new__(SidarAgent)
        agent.cfg = types.SimpleNamespace(
            ENABLE_NIGHTLY_MEMORY_PRUNING=True,
            NIGHTLY_MEMORY_IDLE_SECONDS=1800,
            NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
            NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=6,
            NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=2,
        )
        agent.memory = types.SimpleNamespace(
            run_nightly_consolidation=lambda **_kwargs: asyncio.sleep(
                0,
                result={
                    "status": "completed",
                    "sessions_compacted": 1,
                    "session_ids": ["sess-1"],
                    "reports": [],
                },
            )
        )
        agent.docs = types.SimpleNamespace(
            consolidate_session_documents=lambda session_id, keep_recent_docs=2: {
                "status": "completed",
                "session_id": session_id,
                "removed_docs": 2,
                "summary_doc_id": "digest-1",
                "keep_recent_docs": keep_recent_docs,
            }
        )
        agent._initialized = True
        agent.initialize = lambda: asyncio.sleep(0)
        agent._autonomy_history = []
        agent._autonomy_lock = None
        agent._last_activity_ts = time.time()
        agent._nightly_maintenance_lock = None
        agent._last_nightly_maintenance_ts = 0.0

        fake_entity = types.SimpleNamespace(
            initialize=lambda: asyncio.sleep(0),
            purge_expired=lambda: asyncio.sleep(0, result=3),
        )
        monkeypatch.setattr("agent.sidar_agent.get_entity_memory", lambda _cfg: fake_entity)

        skipped = await SidarAgent.run_nightly_memory_maintenance(agent)
        assert skipped["status"] == "skipped"
        assert skipped["reason"] == "not_idle"

        agent._last_activity_ts = time.time() - 4000
        result = await SidarAgent.run_nightly_memory_maintenance(agent)
        assert result["status"] == "completed"
        assert result["sessions_compacted"] == 1
        assert result["rag_docs_pruned"] == 2
        assert result["entity_report"]["purged"] == 3
        assert len(agent._autonomy_history) == 1
        assert agent._autonomy_history[0]["source"] == "nightly_memory"

    asyncio.run(_run())
