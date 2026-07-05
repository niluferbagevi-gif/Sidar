"""Nightly memory maintenance workflow for SidarAgent."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from core.entity_memory import get_entity_memory


class _NightlyAgentLike(Protocol):
    cfg: Any
    docs: Any
    memory: Any
    _nightly_maintenance_lock: asyncio.Lock | None
    _last_nightly_maintenance_ts: float

    async def initialize(self) -> None: ...

    def seconds_since_last_activity(self) -> float: ...

    async def _acquire_nightly_distributed_lease(
        self,
    ) -> tuple[Any | None, dict[str, Any] | None]: ...

    async def _release_nightly_distributed_lease(self, lease: Any | None) -> None: ...

    async def _append_autonomy_history(self, record: dict[str, Any]) -> None: ...


async def run_nightly_memory_maintenance(
    agent: _NightlyAgentLike,
    *,
    force: bool = False,
    reason: str = "nightly_idle",
    entity_memory_factory: Any = get_entity_memory,
) -> dict[str, Any]:
    """Compact conversation/RAG memory and purge expired entity records."""
    await agent.initialize()
    if not bool(getattr(agent.cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)):
        return {"status": "disabled", "reason": "config_disabled"}

    idle_seconds = max(60, int(getattr(agent.cfg, "NIGHTLY_MEMORY_IDLE_SECONDS", 1800) or 1800))
    idle_for = agent.seconds_since_last_activity()
    if not force and idle_for < idle_seconds:
        return {
            "status": "skipped",
            "reason": "not_idle",
            "idle_for_seconds": round(idle_for, 2),
            "idle_threshold_seconds": idle_seconds,
        }

    if agent._nightly_maintenance_lock is None:
        agent._nightly_maintenance_lock = asyncio.Lock()
    if agent._nightly_maintenance_lock.locked():
        return {
            "status": "skipped",
            "reason": "already_running",
            "idle_for_seconds": round(idle_for, 2),
        }

    async with agent._nightly_maintenance_lock:
        distributed_lease, distributed_skip = await agent._acquire_nightly_distributed_lease()
        if distributed_skip is not None:
            distributed_skip.setdefault("idle_for_seconds", round(idle_for, 2))
            return distributed_skip

        try:
            entity_report: dict[str, Any] = {"purged": 0, "status": "disabled"}
            try:
                entity_memory = entity_memory_factory(agent.cfg)
                await entity_memory.initialize()
                entity_report = {
                    "status": "completed",
                    "purged": await entity_memory.purge_expired(),
                }
            except Exception as exc:
                entity_report = {"status": "failed", "error": str(exc), "purged": 0}

            memory_report: dict[str, Any] = {"status": "failed"}
            rag_reports: list[dict[str, Any]] = []
            removed_docs = 0
            sessions_compacted = 0
            overall_status = "completed"
            try:
                memory_report = await agent.memory.run_nightly_consolidation(
                    keep_recent_sessions=max(
                        0, int(getattr(agent.cfg, "NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS", 2) or 2)
                    ),
                    min_messages=max(
                        2, int(getattr(agent.cfg, "NIGHTLY_MEMORY_SESSION_MIN_MESSAGES", 12) or 12)
                    ),
                )

                keep_recent_docs = max(
                    1, int(getattr(agent.cfg, "NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS", 2) or 2)
                )
                raw_session_ids = memory_report.get("session_ids", [])
                session_ids = raw_session_ids if isinstance(raw_session_ids, list) else []
                for session_id in session_ids:
                    report = await asyncio.to_thread(
                        agent.docs.consolidate_session_documents,
                        str(session_id),
                        keep_recent_docs=keep_recent_docs,
                    )
                    rag_reports.append(report)

                removed_docs = sum(int(item.get("removed_docs", 0) or 0) for item in rag_reports)
                raw_sessions_compacted = memory_report.get("sessions_compacted", 0)
                sessions_compacted = (
                    raw_sessions_compacted
                    if isinstance(raw_sessions_compacted, int)
                    else int(raw_sessions_compacted)
                    if isinstance(raw_sessions_compacted, str) and raw_sessions_compacted.isdigit()
                    else 0
                )
            except Exception as exc:
                # entity_memory.purge_expired() zaten kendi hatasını yakalayıp
                # devam ediyor (yukarıda); memory/RAG konsolidasyonu da aynı şekilde
                # dereceli bozulmalı — aksi halde bu istisna _append_autonomy_history
                # çağrısına hiç ulaşmadan tüm nightly job'ı sessizce (yalnızca
                # çağıranın log satırıyla) sonlandırırdı ve denetim izi kalmazdı.
                overall_status = "failed"
                memory_report = {"status": "failed", "error": str(exc)}

            result: dict[str, Any] = {
                "status": overall_status,
                "reason": reason,
                "idle_for_seconds": round(idle_for, 2),
                "memory_report": memory_report,
                "entity_report": entity_report,
                "rag_reports": rag_reports,
                "sessions_compacted": sessions_compacted,
                "rag_docs_pruned": removed_docs,
                "distributed_lock": (
                    {"backend": distributed_lease.backend, "key": distributed_lease.key}
                    if distributed_lease is not None
                    else {"backend": "local"}
                ),
            }
            agent._last_nightly_maintenance_ts = time.time()
            summary = (
                f"Nightly maintenance tamamlandı: "
                f"{result['sessions_compacted']} oturum sıkıştırıldı, "
                f"{removed_docs} RAG dokümanı budandı, "
                f"{entity_report.get('purged', 0)} entity kaydı temizlendi."
                if overall_status == "completed"
                else (
                    "Nightly maintenance başarısız oldu: "
                    f"{memory_report.get('error', 'bilinmeyen hata')}"
                )
            )
            await agent._append_autonomy_history(
                {
                    "trigger_id": f"nightly-{int(agent._last_nightly_maintenance_ts)}",
                    "source": "nightly_memory",
                    "event_name": "memory_consolidation",
                    "status": result["status"],
                    "summary": summary,
                    "payload": {
                        "reason": reason,
                        "idle_for_seconds": round(idle_for, 2),
                    },
                    "meta": {
                        "kind": "nightly_memory_maintenance",
                        "force": str(bool(force)).lower(),
                        "distributed_lock_backend": result["distributed_lock"]["backend"],
                    },
                    "created_at": agent._last_nightly_maintenance_ts,
                    "completed_at": agent._last_nightly_maintenance_ts,
                }
            )
            return result
        finally:
            await agent._release_nightly_distributed_lease(distributed_lease)
