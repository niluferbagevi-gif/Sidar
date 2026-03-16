"""
Sidar Swarm Orchestrator — Dinamik Çoklu Ajan Koordinasyonu.

Karmaşık görevleri alt görevlere böler, uygun uzman ajanlara yönlendirir
ve sonuçları birleştirir. Agent Registry ile entegre çalışır.

Kullanım:
    orchestrator = SwarmOrchestrator(cfg)

    # Tek görev, otomatik ajan seçimi
    result = await orchestrator.run("Bu kodu incele ve güvenlik açıklarını bul")

    # Paralel swarm — birden fazla ajan eş zamanlı çalışır
    results = await orchestrator.run_parallel([
        SwarmTask(goal="Kodu incele", intent="code_review"),
        SwarmTask(goal="Güvenlik denetle", intent="security_audit"),
    ])
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agent.registry import AgentRegistry, AgentSpec
from agent.core.contracts import TaskEnvelope, TaskResult

logger = logging.getLogger(__name__)


# ── Görev intent → yetenek eşlemesi ──────────────────────────────────────

_INTENT_CAPABILITY_MAP: Dict[str, str] = {
    "code_generation":  "code_generation",
    "code_review":      "code_review",
    "file_io":          "file_io",
    "shell_execution":  "shell_execution",
    "web_search":       "web_search",
    "rag_search":       "rag_search",
    "summarization":    "summarization",
    "security_audit":   "security_audit",
    "quality_check":    "quality_check",
    # Üst düzey intent'ler → spesifik yetenek
    "code":             "code_generation",
    "research":         "web_search",
    "review":           "code_review",
    "security":         "security_audit",
    "mixed":            "code_generation",  # varsayılan
}


@dataclass
class SwarmTask:
    """Swarm'a gönderilen tekil görev birimi."""

    goal: str
    intent: str = "mixed"
    context: Dict[str, str] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: f"swarm-{uuid.uuid4().hex[:8]}")
    preferred_agent: Optional[str] = None  # None → otomatik seçim


@dataclass
class SwarmResult:
    """Swarm görevinin tamamlanma raporu."""

    task_id: str
    agent_role: str
    status: str          # "success" | "failed" | "skipped"
    summary: str
    elapsed_ms: int
    evidence: List[str] = field(default_factory=list)


class TaskRouter:
    """
    Görev intent'ine göre uygun ajan rolünü seçer.
    AgentRegistry üzerinden çalışır — yeni kayıtlı ajanlar otomatik görünür.
    """

    def route(self, intent: str) -> Optional[AgentSpec]:
        """
        Intent → yetenek → ajan spec zinciriyle yönlendirme yapar.
        Birden fazla eşleşme varsa ilk bulunanı döndürür.
        """
        capability = _INTENT_CAPABILITY_MAP.get(intent, intent)
        candidates = AgentRegistry.find_by_capability(capability)
        if not candidates:
            # Fallback: herhangi bir kayıtlı ajan
            all_agents = AgentRegistry.list_all()
            return all_agents[0] if all_agents else None
        return candidates[0]

    def route_by_role(self, role_name: str) -> Optional[AgentSpec]:
        """Doğrudan rol adıyla ajan seç."""
        return AgentRegistry.get(role_name)


class SwarmOrchestrator:
    """
    Dinamik çoklu ajan orkestrasyon motoru.

    Görevleri ajanlar arasında dağıtır, paralel yürütmeyi yönetir
    ve sonuçları birleştirir.
    """

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg
        self.router = TaskRouter()
        self._active_agents: Dict[str, object] = {}  # task_id → agent instance

    # ── Tek görev ────────────────────────────────────────────────────────

    async def run(self, goal: str, *, intent: str = "mixed", session_id: str = "") -> SwarmResult:
        """Tek bir görevi uygun ajana yönlendir ve sonucu döndür."""
        task = SwarmTask(goal=goal, intent=intent)
        return await self._execute_task(task, session_id=session_id)

    # ── Paralel swarm ─────────────────────────────────────────────────────

    async def run_parallel(
        self,
        tasks: List[SwarmTask],
        *,
        session_id: str = "",
        max_concurrency: int = 4,
    ) -> List[SwarmResult]:
        """
        Görev listesini eş zamanlı olarak çalıştır.
        max_concurrency limiti aşıldığında semafore ile kısıtlanır.
        """
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(task: SwarmTask) -> SwarmResult:
            async with sem:
                return await self._execute_task(task, session_id=session_id)

        return list(await asyncio.gather(*[_bounded(t) for t in tasks]))

    # ── Sıralı pipeline ───────────────────────────────────────────────────

    async def run_pipeline(
        self,
        tasks: List[SwarmTask],
        *,
        session_id: str = "",
    ) -> List[SwarmResult]:
        """
        Görevleri sırayla yürüt; her görevin özeti bir sonrakinin context'ine eklenir.
        Kod üretimi → inceleme → güvenlik denetimi gibi akışlar için kullanışlıdır.
        """
        results: List[SwarmResult] = []
        accumulated_context: Dict[str, str] = {}

        for task in tasks:
            task.context.update(accumulated_context)
            result = await self._execute_task(task, session_id=session_id)
            results.append(result)
            # Başarılı sonuçları sonraki adım için context'e aktar
            if result.status == "success":
                accumulated_context[f"prev_{result.agent_role}"] = result.summary[:500]

        return results

    # ── İç yürütme ────────────────────────────────────────────────────────

    async def _execute_task(self, task: SwarmTask, *, session_id: str = "") -> SwarmResult:
        """Görevi uygun ajana yönlendirip çalıştırır."""
        started_at = time.monotonic()

        # Ajan seçimi
        spec = (
            self.router.route_by_role(task.preferred_agent)
            if task.preferred_agent
            else self.router.route(task.intent)
        )

        if spec is None:
            logger.warning("SwarmOrchestrator: '%s' için uygun ajan bulunamadı.", task.task_id)
            return SwarmResult(
                task_id=task.task_id,
                agent_role="none",
                status="skipped",
                summary="Uygun ajan bulunamadı.",
                elapsed_ms=0,
            )

        # Ajan örneği oluştur (hafif — konfigürasyon paylaşılır)
        try:
            agent = AgentRegistry.create(spec.role_name, cfg=self.cfg)
        except Exception as exc:
            logger.error("SwarmOrchestrator: ajan oluşturma hatası [%s]: %s", spec.role_name, exc)
            return SwarmResult(
                task_id=task.task_id,
                agent_role=spec.role_name,
                status="failed",
                summary=f"Ajan oluşturulamadı: {exc}",
                elapsed_ms=0,
            )

        # Görev zarfı oluştur
        envelope = TaskEnvelope(
            task_id=task.task_id,
            sender="swarm_orchestrator",
            receiver=spec.role_name,
            goal=task.goal,
            intent=task.intent,
            context={**task.context, "session_id": session_id},
        )

        # Görevi çalıştır
        self._active_agents[task.task_id] = agent
        try:
            result: TaskResult = await agent.handle(envelope)
            elapsed = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "SwarmOrchestrator: [%s] → %s tamamlandı (%dms, status=%s)",
                task.task_id, spec.role_name, elapsed, result.status,
            )
            return SwarmResult(
                task_id=task.task_id,
                agent_role=spec.role_name,
                status=result.status,
                summary=str(result.summary),
                elapsed_ms=elapsed,
                evidence=result.evidence,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started_at) * 1000)
            logger.error("SwarmOrchestrator: [%s] hata [%s]: %s", task.task_id, spec.role_name, exc)
            return SwarmResult(
                task_id=task.task_id,
                agent_role=spec.role_name,
                status="failed",
                summary=f"Görev başarısız: {exc}",
                elapsed_ms=elapsed,
            )
        finally:
            self._active_agents.pop(task.task_id, None)

    # ── Durum sorguları ───────────────────────────────────────────────────

    @property
    def active_task_count(self) -> int:
        """Şu an çalışan görev sayısı."""
        return len(self._active_agents)

    def available_agents(self) -> List[str]:
        """Kayıtlı tüm ajan rollerini listeler."""
        return [spec.role_name for spec in AgentRegistry.list_all()]