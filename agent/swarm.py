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
from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult, is_delegation_request

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
    "aws_management":   "aws_management",
    "cloud_ops":        "aws_management",
    "slack_notification": "slack_notification",
    "notifications":    "slack_notification",
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
    handoffs: List[Dict[str, str]] = field(default_factory=list)
    graph: Dict[str, str] = field(default_factory=dict)


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

    def _loop_repeat_limit(self) -> int:
        """Yerel modellerde daha sıkı, uzak modellerde daha esnek tekrar limiti."""
        provider = str(getattr(self.cfg, "AI_PROVIDER", "") or "").lower()
        default_limit = 2 if provider == "ollama" else 3
        return max(1, int(getattr(self.cfg, "SWARM_LOOP_GUARD_MAX_REPEAT", default_limit) or default_limit))

    @staticmethod
    def _browser_context_snapshot(context: Dict[str, str]) -> Dict[str, str]:
        session_id = str(context.get("browser_session_id", "") or "").strip()
        summary = str(context.get("browser_signal_summary", "") or "").strip()
        status = str(context.get("browser_signal_status", "") or "").strip()
        risk = str(context.get("browser_signal_risk", "") or "").strip()
        return {
            "browser_session_id": session_id,
            "browser_signal_summary": summary,
            "browser_signal_status": status,
            "browser_signal_risk": risk,
        }

    @classmethod
    def _compose_goal_with_context(cls, goal: str, context: Dict[str, str]) -> str:
        text = (goal or "").strip()
        browser_context = cls._browser_context_snapshot(context)
        if browser_context["browser_signal_summary"]:
            text += (
                "\n\n[BROWSER_SIGNALS]\n"
                f"session_id={browser_context['browser_session_id']}\n"
                f"status={browser_context['browser_signal_status']}\n"
                f"risk={browser_context['browser_signal_risk']}\n"
                f"summary={browser_context['browser_signal_summary']}"
            )
        return text

    async def _run_autonomous_feedback(
        self,
        *,
        prompt: str,
        response: str,
        context: Dict[str, str],
        session_id: str,
        agent_role: str,
        task_id: str,
    ) -> None:
        if not prompt or not response:
            return
        try:
            from core.judge import get_llm_judge
            from core.active_learning import flag_weak_response

            judge = get_llm_judge()
            if not judge.enabled:
                return

            evaluation = await judge.evaluate_response(prompt=prompt, response=response, context=context)
            if evaluation is None or evaluation.score >= 8:
                return

            await flag_weak_response(
                prompt=prompt,
                response=response,
                score=evaluation.score,
                reasoning=evaluation.reasoning,
                config=self.cfg,
                session_id=session_id or task_id,
                provider=evaluation.provider,
                model=evaluation.model,
                tags=[
                    "swarm:auto",
                    f"agent:{agent_role}",
                    f"task_id:{task_id}",
                ],
            )
        except Exception as exc:
            logger.debug("Swarm autonomous feedback hatası [%s]: %s", task_id, exc)

    def _schedule_autonomous_feedback(
        self,
        *,
        prompt: str,
        response: str,
        context: Dict[str, str],
        session_id: str,
        agent_role: str,
        task_id: str,
    ) -> None:
        if not prompt or not response:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._run_autonomous_feedback(
                    prompt=prompt,
                    response=response,
                    context=context,
                    session_id=session_id,
                    agent_role=agent_role,
                    task_id=task_id,
                ),
                name="sidar_swarm_autonomous_feedback",
            )
        except RuntimeError:
            pass

    @staticmethod
    def _goal_fingerprint(goal: str, *, max_chars: int = 180) -> str:
        text = " ".join((goal or "").strip().lower().split())
        return text[:max_chars]

    @staticmethod
    def _p2p_context(
        base_context: Dict[str, str],
        message: DelegationRequest,
        *,
        session_id: str,
        hop: int,
        route_trace: List[str],
    ) -> Dict[str, str]:
        return {
            **base_context,
            "session_id": session_id,
            "swarm_hop": str(hop),
            "swarm_trace": " -> ".join(route_trace[-6:]),
            "p2p_protocol": str(getattr(message, "protocol", "p2p.v1") or "p2p.v1"),
            "p2p_sender": str(message.reply_to or ""),
            "p2p_receiver": str(message.target_agent or ""),
            "p2p_intent": str(getattr(message, "intent", "") or ""),
            "p2p_reason": str((message.meta or {}).get("reason", "")),
            "p2p_handoff_depth": str(int(getattr(message, "handoff_depth", 0) or 0)),
        }

    async def _direct_handoff(
        self,
        task: SwarmTask,
        delegation: DelegationRequest,
        *,
        session_id: str,
        hop: int,
        route_trace: List[str],
        handoff_chain: List[Dict[str, str]],
    ) -> SwarmResult:
        target_role = (delegation.target_agent or "").strip()
        if not target_role:
            raise RuntimeError("DelegationRequest target_agent boş")

        delegated_task = SwarmTask(
            goal=str(delegation.payload or task.goal),
            intent=str(getattr(delegation, "intent", "") or task.intent),
            context=self._p2p_context(
                task.context,
                delegation,
                session_id=session_id,
                hop=hop,
                route_trace=route_trace,
            ),
            task_id=task.task_id,
            preferred_agent=target_role,
        )
        logger.info(
            "SwarmOrchestrator: [%s] direct handoff %s → %s (hop=%d)",
            task.task_id,
            delegation.reply_to,
            target_role,
            hop,
        )
        next_handoff_chain = [
            *handoff_chain,
            {
                "task_id": task.task_id,
                "sender": str(delegation.reply_to or ""),
                "receiver": str(target_role or ""),
                "reason": str((delegation.meta or {}).get("reason", "") or ""),
                "intent": str(getattr(delegation, "intent", "") or task.intent),
                "handoff_depth": str(int(getattr(delegation, "handoff_depth", 0) or 0)),
                "swarm_hop": str(hop),
            },
        ]
        return await self._execute_task(
            delegated_task,
            session_id=session_id,
            _hop=hop,
            _route_trace=route_trace,
            _sender=delegation.reply_to,
            _parent_task_id=delegation.parent_task_id or task.task_id,
            _handoff_chain=next_handoff_chain,
        )

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

    async def _execute_task(
        self,
        task: SwarmTask,
        *,
        session_id: str = "",
        _hop: int = 0,
        _route_trace: Optional[List[str]] = None,
        _sender: str = "swarm_orchestrator",
        _parent_task_id: Optional[str] = None,
        _handoff_chain: Optional[List[Dict[str, str]]] = None,
    ) -> SwarmResult:
        """Görevi uygun ajana yönlendirip çalıştırır."""
        started_at = time.monotonic()
        max_retries = max(0, int(getattr(self.cfg, "SWARM_TASK_MAX_RETRIES", 0) or 0))
        retry_delay_ms = max(0, int(getattr(self.cfg, "SWARM_TASK_RETRY_DELAY_MS", 0) or 0))
        max_hops = max(1, int(getattr(self.cfg, "SWARM_MAX_HANDOFF_HOPS", 4) or 4))
        route_trace = list(_route_trace or [])
        handoff_chain = list(_handoff_chain or [])

        if _hop > max_hops:
            return SwarmResult(
                task_id=task.task_id,
                agent_role=task.preferred_agent or "unknown",
                status="failed",
                summary=(
                    "Recursive loop guard devreye girdi: "
                    f"maksimum devir sayısı aşıldı (hop={_hop}, limit={max_hops})."
                ),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                handoffs=handoff_chain,
            )

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
                handoffs=handoff_chain,
            )

        fingerprint = self._goal_fingerprint(task.goal)
        current_step = f"{spec.role_name}|{task.intent}|{fingerprint}"
        step_count = route_trace.count(current_step)
        if step_count >= self._loop_repeat_limit():
            logger.warning(
                "SwarmOrchestrator: loop guard [%s] step=%s tekrar=%d",
                task.task_id,
                current_step,
                step_count,
            )
            return SwarmResult(
                task_id=task.task_id,
                agent_role=spec.role_name,
                status="failed",
                summary=(
                    "Recursive loop guard: aynı ajan/intente aynı görev tekrarlandı "
                    f"(count={step_count + 1})."
                ),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                handoffs=handoff_chain,
            )

        next_trace = route_trace + [current_step]

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
                handoffs=handoff_chain,
            )

        # Görev zarfı oluştur
        envelope = TaskEnvelope(
            task_id=task.task_id,
            sender=_sender,
            receiver=spec.role_name,
            goal=self._compose_goal_with_context(task.goal, task.context),
            intent=task.intent,
            parent_task_id=_parent_task_id,
            context={
                **task.context,
                "session_id": session_id,
                "swarm_hop": str(_hop),
                "swarm_trace": " -> ".join(next_trace[-6:]),
            },
        )

        # Görevi çalıştır
        self._active_agents[task.task_id] = agent
        try:
            result: Optional[TaskResult] = None
            last_exc: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    result = await agent.handle(envelope)
                    break
                except Exception as exc:  # pragma: no cover - branch specific tests verify behavior
                    last_exc = exc
                    if attempt >= max_retries:
                        raise
                    logger.warning(
                        "SwarmOrchestrator: [%s] retry %d/%d [%s] sebebi: %s",
                        task.task_id,
                        attempt + 1,
                        max_retries,
                        spec.role_name,
                        exc,
                    )
                    if retry_delay_ms > 0:
                        await asyncio.sleep(retry_delay_ms / 1000)

            if result is None and last_exc is not None:
                raise last_exc

            if is_delegation_request(result.summary):
                delegation = result.summary
                if not getattr(delegation, "reply_to", ""):
                    delegation.reply_to = spec.role_name
                bumped = delegation.bumped() if hasattr(delegation, "bumped") else delegation
                return await self._direct_handoff(
                    task,
                    bumped,
                    session_id=session_id,
                    hop=_hop + 1,
                    route_trace=next_trace,
                    handoff_chain=handoff_chain,
                )

            elapsed = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "SwarmOrchestrator: [%s] → %s tamamlandı (%dms, status=%s)",
                task.task_id, spec.role_name, elapsed, result.status,
            )
            if result.status == "success":
                self._schedule_autonomous_feedback(
                    prompt=task.goal,
                    response=str(result.summary),
                    context={
                        **envelope.context,
                        "intent": task.intent,
                        "agent_role": spec.role_name,
                        "evidence": "\n".join(result.evidence[:5]),
                        **self._browser_context_snapshot(task.context),
                    },
                    session_id=session_id,
                    agent_role=spec.role_name,
                    task_id=task.task_id,
                )
            return SwarmResult(
                task_id=task.task_id,
                agent_role=spec.role_name,
                status=result.status,
                summary=str(result.summary),
                elapsed_ms=elapsed,
                evidence=result.evidence,
                handoffs=handoff_chain,
                graph={
                    "sender": str(envelope.sender or ""),
                    "receiver": str(envelope.receiver or ""),
                    "intent": str(task.intent or ""),
                    "session_id": str(session_id or ""),
                    "swarm_hop": str(_hop),
                    "swarm_trace": " -> ".join(next_trace[-6:]),
                    "p2p_sender": str(task.context.get("p2p_sender", "") or ""),
                    "p2p_receiver": str(task.context.get("p2p_receiver", "") or ""),
                    "p2p_reason": str(task.context.get("p2p_reason", "") or ""),
                    "p2p_handoff_depth": str(task.context.get("p2p_handoff_depth", "") or ""),
                    "browser_session_id": str(task.context.get("browser_session_id", "") or ""),
                    "browser_signal_status": str(task.context.get("browser_signal_status", "") or ""),
                    "browser_signal_risk": str(task.context.get("browser_signal_risk", "") or ""),
                    "browser_signal_summary": str(task.context.get("browser_signal_summary", "") or "")[:300],
                },
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
                handoffs=handoff_chain,
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
