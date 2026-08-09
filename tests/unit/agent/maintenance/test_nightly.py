from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.maintenance.nightly import run_nightly_memory_maintenance


class FakeNightlyAgent:
    def __init__(self, *, enabled: bool = True, idle_for: float = 3600.0) -> None:
        self.cfg = SimpleNamespace(
            ENABLE_NIGHTLY_MEMORY_PRUNING=enabled,
            NIGHTLY_MEMORY_IDLE_SECONDS=1800,
            NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
            NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=12,
            NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=2,
        )
        self.docs = SimpleNamespace(
            consolidate_session_documents=lambda *_a, **_k: {"removed_docs": 1}
        )
        self.memory = SimpleNamespace(
            run_nightly_consolidation=AsyncMock(
                return_value={"status": "completed", "session_ids": ["s1"], "sessions_compacted": 1}
            )
        )
        self._nightly_maintenance_lock: asyncio.Lock | None = None
        self._last_nightly_maintenance_ts = 0.0
        self.idle_for = idle_for
        self.initialize = AsyncMock()
        self._append_autonomy_history = AsyncMock()
        self._acquire_nightly_distributed_lease = AsyncMock(return_value=(None, None))
        self._release_nightly_distributed_lease = AsyncMock()

    def seconds_since_last_activity(self) -> float:
        return self.idle_for


class FakeEntityMemory:
    def __init__(self, *, purged: int = 2, exc: Exception | None = None) -> None:
        self.purged = purged
        self.exc = exc
        self.initialize = AsyncMock()

    async def purge_expired(self) -> int:
        if self.exc is not None:
            raise self.exc
        return self.purged


def test_nightly_maintenance_returns_disabled_when_config_is_off() -> None:
    agent = FakeNightlyAgent(enabled=False)

    result = asyncio.run(run_nightly_memory_maintenance(agent))

    assert result == {"status": "disabled", "reason": "config_disabled"}
    agent._acquire_nightly_distributed_lease.assert_not_awaited()


def test_nightly_maintenance_skips_when_agent_is_not_idle() -> None:
    agent = FakeNightlyAgent(idle_for=120.25)

    result = asyncio.run(run_nightly_memory_maintenance(agent))

    assert result == {
        "status": "skipped",
        "reason": "not_idle",
        "idle_for_seconds": 120.25,
        "idle_threshold_seconds": 1800,
    }
    agent._acquire_nightly_distributed_lease.assert_not_awaited()


def test_nightly_maintenance_skips_when_local_lock_is_already_running() -> None:
    agent = FakeNightlyAgent()
    lock = asyncio.Lock()

    async def _run() -> dict[str, object]:
        await lock.acquire()
        try:
            agent._nightly_maintenance_lock = lock
            return await run_nightly_memory_maintenance(agent, force=True)
        finally:
            lock.release()

    result = asyncio.run(_run())

    assert result == {"status": "skipped", "reason": "already_running", "idle_for_seconds": 3600.0}
    agent._acquire_nightly_distributed_lease.assert_not_awaited()


def test_nightly_maintenance_returns_distributed_lease_skip_without_release() -> None:
    agent = FakeNightlyAgent()
    agent._acquire_nightly_distributed_lease = AsyncMock(
        return_value=(None, {"status": "skipped", "reason": "distributed_lock_busy"})
    )

    result = asyncio.run(run_nightly_memory_maintenance(agent, force=True))

    assert result == {
        "status": "skipped",
        "reason": "distributed_lock_busy",
        "idle_for_seconds": 3600.0,
    }
    agent._release_nightly_distributed_lease.assert_not_awaited()
    agent.memory.run_nightly_consolidation.assert_not_awaited()


def test_nightly_maintenance_records_entity_purge_failure_and_continues() -> None:
    agent = FakeNightlyAgent()

    result = asyncio.run(
        run_nightly_memory_maintenance(
            agent,
            force=True,
            entity_memory_factory=lambda _cfg: FakeEntityMemory(exc=RuntimeError("entity-boom")),
        )
    )

    assert result["status"] == "completed"
    assert result["entity_report"] == {"status": "failed", "error": "entity-boom", "purged": 0}
    assert result["sessions_compacted"] == 1
    agent._append_autonomy_history.assert_awaited_once()


def test_nightly_maintenance_records_memory_consolidation_failure() -> None:
    agent = FakeNightlyAgent()
    agent.memory.run_nightly_consolidation = AsyncMock(side_effect=RuntimeError("memory-boom"))

    result = asyncio.run(
        run_nightly_memory_maintenance(
            agent,
            force=True,
            entity_memory_factory=lambda _cfg: FakeEntityMemory(purged=3),
        )
    )

    assert result["status"] == "failed"
    assert result["memory_report"] == {"status": "failed", "error": "memory-boom"}
    assert result["entity_report"] == {"status": "completed", "purged": 3}
    assert result["rag_reports"] == []
    agent._append_autonomy_history.assert_awaited_once()


def test_nightly_maintenance_records_rag_consolidation_failure() -> None:
    agent = FakeNightlyAgent()
    agent.docs.consolidate_session_documents = lambda *_a, **_k: (_ for _ in ()).throw(
        OSError("rag-boom")
    )

    result = asyncio.run(
        run_nightly_memory_maintenance(
            agent,
            force=True,
            entity_memory_factory=lambda _cfg: FakeEntityMemory(purged=1),
        )
    )

    assert result["status"] == "failed"
    assert result["memory_report"] == {"status": "failed", "error": "rag-boom"}
    assert result["rag_reports"] == []
    agent._append_autonomy_history.assert_awaited_once()


def test_nightly_maintenance_releases_distributed_lease_in_finally_on_failure() -> None:
    agent = FakeNightlyAgent()
    lease = SimpleNamespace(backend="redis", key="sidar:nightly")
    agent._acquire_nightly_distributed_lease = AsyncMock(return_value=(lease, None))
    agent.memory.run_nightly_consolidation = AsyncMock(side_effect=RuntimeError("memory-boom"))

    result = asyncio.run(
        run_nightly_memory_maintenance(
            agent,
            force=True,
            entity_memory_factory=lambda _cfg: FakeEntityMemory(purged=0),
        )
    )

    assert result["distributed_lock"] == {"backend": "redis", "key": "sidar:nightly"}
    agent._release_nightly_distributed_lease.assert_awaited_once_with(lease)
