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
import importlib
import importlib.util
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast

from agent.registry import AgentCatalog, AgentSpec

if TYPE_CHECKING:
    from agent.core.contracts import (
        BrokerTaskEnvelope,
        BrokerTaskResult,
        DelegationRequest,
        TaskEnvelope,
        TaskResult,
        is_delegation_request,
    )


def _is_contracts_module_healthy(module: ModuleType) -> bool:
    required = (
        "TaskEnvelope",
        "TaskResult",
        "DelegationRequest",
        "BrokerTaskEnvelope",
        "BrokerTaskResult",
        "is_delegation_request",
    )
    if not all(hasattr(module, name) for name in required):
        return False

    try:
        if getattr(module, "DelegationRequest", object) is object:
            return False

        task_envelope_cls = getattr(module, "TaskEnvelope", None)
        task_result_cls = getattr(module, "TaskResult", None)
        delegation_request_cls = getattr(module, "DelegationRequest", None)
        if not all(callable(cls) for cls in (task_envelope_cls, task_result_cls, delegation_request_cls)):
            return False

        cast(Any, task_envelope_cls)(task_id="t", sender="s", receiver="r", goal="g")
        cast(Any, task_result_cls)(task_id="t", status="success", summary="ok", evidence=[])
        cast(Any, delegation_request_cls)(
            task_id="t", reply_to="s", target_agent="r", payload="p"
        )
    except Exception:
        return False

    checker = getattr(module, "is_delegation_request", None)
    return callable(checker)


def _contracts_module() -> ModuleType:
    module = importlib.import_module("agent.core.contracts")
    if _is_contracts_module_healthy(module):
        return module

    module_path = Path(__file__).resolve().parent / "core" / "contracts.py"
    spec = importlib.util.spec_from_file_location("agent.core.contracts", module_path)
    if spec is None or spec.loader is None:
        return module
    repaired = importlib.util.module_from_spec(spec)
    sys.modules["agent.core.contracts"] = repaired
    spec.loader.exec_module(repaired)
    return repaired


if TYPE_CHECKING:
    from agent.core.contracts import (
        BrokerTaskEnvelope,
        BrokerTaskResult,
        DelegationRequest,
        TaskEnvelope,
        TaskResult,
        is_delegation_request,
    )
else:
    _contracts = _contracts_module()
    BrokerTaskEnvelope = _contracts.BrokerTaskEnvelope
    BrokerTaskResult = _contracts.BrokerTaskResult
    DelegationRequest = _contracts.DelegationRequest
    TaskEnvelope = _contracts.TaskEnvelope
    TaskResult = _contracts.TaskResult
    is_delegation_request = _contracts.is_delegation_request

logger = logging.getLogger(__name__)


def _ensure_contract_aliases() -> None:
    """Global kontrat aliaslarını sağlıklı modüle yeniden bağlar."""
    global \
        BrokerTaskEnvelope, \
        BrokerTaskResult, \
        DelegationRequest, \
        TaskEnvelope, \
        TaskResult, \
        is_delegation_request
    module = _contracts_module()
    BrokerTaskEnvelope = module.BrokerTaskEnvelope  # type: ignore[misc]
    BrokerTaskResult = module.BrokerTaskResult  # type: ignore[misc]
    DelegationRequest = module.DelegationRequest  # type: ignore[misc]
    TaskEnvelope = module.TaskEnvelope  # type: ignore[misc]
    TaskResult = module.TaskResult  # type: ignore[misc]
    is_delegation_request = module.is_delegation_request


# ── Görev intent → yetenek eşlemesi ──────────────────────────────────────

_INTENT_CAPABILITY_MAP: dict[str, str] = {
    "code_generation": "code_generation",
    "code_review": "code_review",
    "file_io": "file_io",
    "shell_execution": "shell_execution",
    "web_search": "web_search",
    "rag_search": "rag_search",
    "summarization": "summarization",
    "security_audit": "security_audit",
    "quality_check": "quality_check",
    "aws_management": "aws_management",
    "cloud_ops": "aws_management",
    "slack_notification": "slack_notification",
    "notifications": "slack_notification",
    "marketing_strategy": "marketing_strategy",
    "seo_analysis": "seo_analysis",
    "campaign_copy": "campaign_copy",
    "audience_ops": "audience_ops",
    "coverage_analysis": "coverage_analysis",
    "test_generation": "test_generation",
    "ci_remediation": "ci_remediation",
    # Üst düzey intent'ler → spesifik yetenek
    "code": "code_generation",
    "research": "web_search",
    "review": "code_review",
    "security": "security_audit",
    "marketing": "marketing_strategy",
    "seo": "seo_analysis",
    "campaign": "campaign_copy",
    "coverage": "coverage_analysis",
    "qa": "coverage_analysis",
    "tests": "test_generation",
    "mixed": "code_generation",  # varsayılan
}


@dataclass
class SwarmTask:
    """Swarm'a gönderilen tekil görev birimi."""

    goal: str
    intent: str = "mixed"
    context: dict[str, str] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: f"swarm-{uuid.uuid4().hex[:8]}")
    preferred_agent: str | None = None  # None → otomatik seçim


@dataclass
class SwarmResult:
    """Swarm görevinin tamamlanma raporu."""

    task_id: str
    agent_role: str
    status: str  # "success" | "failed" | "skipped"
    summary: str
    elapsed_ms: int
    evidence: list[str] = field(default_factory=list)
    handoffs: list[dict[str, str]] = field(default_factory=list)
    graph: dict[str, str] = field(default_factory=dict)


class AsyncDelegationBackend(Protocol):
    """Broker veya kuyruk tabanlı dağıtık delegasyon backend kontratı."""

    async def dispatch(self, envelope: BrokerTaskEnvelope) -> BrokerTaskResult:
        """Görevi dağıtık kuyruğa bırakır ve normalize edilmiş sonucu döndürür."""


class InMemoryDelegationBackend:
    """Test/prototip amaçlı broker uyumlu backend."""

    def __init__(self) -> None:
        self.dispatched: list[BrokerTaskEnvelope] = []

    async def dispatch(self, envelope: BrokerTaskEnvelope) -> BrokerTaskResult:
        self.dispatched.append(envelope)
        return BrokerTaskResult(
            task_id=envelope.task_id,
            sender=envelope.receiver,
            receiver=envelope.sender,
            status="queued",
            summary=f"Broker kuyruğuna alındı: {envelope.routing_key}",
            broker=envelope.broker,
            exchange=envelope.exchange,
            routing_key=envelope.routing_key,
            correlation_id=envelope.correlation_id,
        )


class TaskRouter:
    """
    Görev intent'ine göre uygun ajan rolünü seçer.
    AgentRegistry üzerinden çalışır — yeni kayıtlı ajanlar otomatik görünür.
    """

    @staticmethod
    def _catalog() -> Any:
        """Geçerli AgentCatalog referansını döndürür.

        Testlerde `agent.swarm.AgentCatalog` monkeypatch edildiğinde bu referansı
        korur; aksi halde registry modülündeki canlı sınıfa düşer.
        """
        registry_mod = importlib.import_module("agent.registry")
        live_catalog = getattr(registry_mod, "AgentCatalog", None)
        if (
            live_catalog is not None
            and hasattr(live_catalog, "find_by_capability")
            and hasattr(live_catalog, "list_all")
        ):
            return live_catalog
        local_catalog = AgentCatalog
        if hasattr(local_catalog, "find_by_capability") and hasattr(local_catalog, "list_all"):
            return local_catalog
        return live_catalog

    def route(self, intent: str) -> AgentSpec | None:
        """
        Intent → yetenek → ajan spec zinciriyle yönlendirme yapar.
        Birden fazla eşleşme varsa ilk bulunanı döndürür.
        """
        catalog = self._catalog()
        capability = _INTENT_CAPABILITY_MAP.get(intent, intent)
        candidates = catalog.find_by_capability(capability)
        if not candidates:
            # Fallback: herhangi bir kayıtlı ajan
            all_agents = catalog.list_all()
            return all_agents[0] if all_agents else None
        return cast(AgentSpec, candidates[0])

    def route_by_role(self, role_name: str) -> AgentSpec | None:
        """Doğrudan rol adıyla ajan seç."""
        catalog = self._catalog()
        getter = getattr(catalog, "get", None)
        if callable(getter):
            return cast(AgentSpec | None, getter(role_name))
        lister = getattr(catalog, "list_all", None)
        if callable(lister):
            for spec in lister() or []:
                if getattr(spec, "role_name", "") == role_name:
                    return cast(AgentSpec, spec)
        return None


def _looks_like_delegation_request(value: object) -> bool:
    _ensure_contract_aliases()
    checker = is_delegation_request if callable(is_delegation_request) else None
    if checker is not None:
        try:
            if checker(value):
                return True
        except Exception:
            pass
    return all(hasattr(value, attr) for attr in ("target_agent", "payload", "reply_to"))


class SwarmOrchestrator:
    """
    Dinamik çoklu ajan orkestrasyon motoru.

    Görevleri ajanlar arasında dağıtır, paralel yürütmeyi yönetir
    ve sonuçları birleştirir.
    """

    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg
        self.router = TaskRouter()
        self._active_agents: dict[str, object] = {}  # task_id → agent instance
        self.delegation_backend: AsyncDelegationBackend | None = None

    def configure_delegation_backend(self, backend: AsyncDelegationBackend | None) -> None:
        """Broker tabanlı delegasyon backend'ini enjekte eder."""
        self.delegation_backend = backend

    async def dispatch_distributed(
        self,
        task: SwarmTask,
        *,
        session_id: str = "",
        sender: str = "swarm_orchestrator",
        receiver: str | None = None,
        exchange: str = "sidar.swarm",
        broker: str = "memory",
        reply_queue: str = "",
    ) -> BrokerTaskResult:
        """Görevi broker uyumlu zarf ile dış/backplane delegasyonuna hazırlar."""
        _ensure_contract_aliases()
        if self.delegation_backend is None:
            raise RuntimeError("Dağıtık delegasyon backend'i yapılandırılmadı.")

        spec = (
            self.router.route_by_role(receiver)
            if receiver
            else (
                self.router.route_by_role(task.preferred_agent)
                if task.preferred_agent
                else self.router.route(task.intent)
            )
        )
        if spec is None:
            raise RuntimeError("Dağıtık delegasyon için uygun ajan bulunamadı.")

        envelope = TaskEnvelope(
            task_id=task.task_id,
            sender=sender,
            receiver=spec.role_name,
            goal=self._compose_goal_with_context(task.goal, task.context),
            intent=task.intent,
            parent_task_id=None,
            context={
                **task.context,
                "session_id": session_id,
                "distributed_dispatch": "true",
            },
        )
        broker_envelope = BrokerTaskEnvelope.from_task_envelope(
            envelope,
            broker=broker,
            exchange=exchange,
            reply_queue=reply_queue,
            headers={"session_id": session_id},
        )
        return await self.delegation_backend.dispatch(broker_envelope)

    def _loop_repeat_limit(self) -> int:
        """Yerel modellerde daha sıkı, uzak modellerde daha esnek tekrar limiti."""
        provider = str(getattr(self.cfg, "AI_PROVIDER", "") or "").lower()
        default_limit = 2 if provider == "ollama" else 3
        return max(
            1, int(getattr(self.cfg, "SWARM_LOOP_GUARD_MAX_REPEAT", default_limit) or default_limit)
        )

    @staticmethod
    def _browser_context_snapshot(context: dict[str, str]) -> dict[str, str]:
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
    def _compose_goal_with_context(cls, goal: str, context: dict[str, str]) -> str:
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

    @staticmethod
    def _should_fallback_to_supervisor(exc: Exception) -> bool:
        if isinstance(exc, json.JSONDecodeError):
            return True

        text = str(exc or "").lower()
        exc_name = type(exc).__name__.lower()
        json_signals = (
            "json",
            "decode",
            "parse",
            "schema",
            "validation",
            "unexpected format",
            "malformed",
        )
        if any(signal in exc_name for signal in json_signals):
            return True
        if any(signal in text for signal in json_signals):
            return True
        if "429" in text or "rate limit" in text or "too many requests" in text:
            return True
        return False

    async def _run_supervisor_fallback(
        self,
        task: SwarmTask,
        *,
        session_id: str,
        started_at: float,
        route_trace: list[str],
        handoff_chain: list[dict[str, str]],
        failed_role: str,
        reason: str,
    ) -> SwarmResult:
        from agent.core.supervisor import SupervisorAgent

        supervisor = SupervisorAgent(self.cfg)
        fallback_prompt = self._compose_goal_with_context(task.goal, task.context)
        fallback_output = await supervisor.run_task(fallback_prompt)
        if not isinstance(fallback_output, str) or not fallback_output.strip():
            raise RuntimeError("Supervisor fallback geçerli bir çıktı üretemedi.")

        elapsed = int((time.monotonic() - started_at) * 1000)
        next_handoffs = [
            *handoff_chain,
            {
                "task_id": task.task_id,
                "sender": failed_role,
                "receiver": "supervisor",
                "reason": reason,
                "intent": str(task.intent or ""),
                "swarm_hop": str(len(route_trace)),
            },
        ]
        return SwarmResult(
            task_id=task.task_id,
            agent_role="supervisor",
            status="success",
            summary=fallback_output.strip(),
            elapsed_ms=elapsed,
            evidence=[f"fallback:{failed_role}", reason],
            handoffs=next_handoffs,
            graph={
                "sender": failed_role,
                "receiver": "supervisor",
                "intent": str(task.intent or ""),
                "session_id": str(session_id or ""),
                "swarm_trace": " -> ".join(route_trace[-6:]),
                "fallback_reason": reason,
            },
        )

    async def _run_autonomous_feedback(
        self,
        *,
        prompt: str,
        response: str,
        context: dict[str, str],
        session_id: str,
        agent_role: str,
        task_id: str,
    ) -> None:
        if not prompt or not response:
            return
        try:
            from core.active_learning import flag_weak_response
            from core.judge import get_llm_judge

            judge = get_llm_judge()
            if not judge.enabled:
                return

            evaluation = await judge.evaluate_response(
                prompt=prompt, response=response, context=context
            )
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
        context: dict[str, str],
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
        base_context: dict[str, str],
        message: DelegationRequest,
        *,
        session_id: str,
        hop: int,
        route_trace: list[str],
    ) -> dict[str, str]:
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
        route_trace: list[str],
        handoff_chain: list[dict[str, str]],
    ) -> SwarmResult:
        _ensure_contract_aliases()
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
        tasks: list[SwarmTask],
        *,
        session_id: str = "",
        max_concurrency: int = 4,
    ) -> list[SwarmResult]:
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
        tasks: list[SwarmTask],
        *,
        session_id: str = "",
    ) -> list[SwarmResult]:
        """
        Görevleri sırayla yürüt; her görevin özeti bir sonrakinin context'ine eklenir.
        Kod üretimi → inceleme → güvenlik denetimi gibi akışlar için kullanışlıdır.
        """
        results: list[SwarmResult] = []
        accumulated_context: dict[str, str] = {}

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
        _route_trace: list[str] | None = None,
        _sender: str = "swarm_orchestrator",
        _parent_task_id: str | None = None,
        _handoff_chain: list[dict[str, str]] | None = None,
    ) -> SwarmResult:
        """Görevi uygun ajana yönlendirip çalıştırır."""
        _ensure_contract_aliases()
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
            agent = AgentCatalog.create(spec.role_name, cfg=self.cfg)
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
            result: TaskResult | None = None
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    handle_fn = getattr(agent, "handle", None)
                    run_task_fn = getattr(agent, "run_task", None)
                    if callable(handle_fn):
                        result = await handle_fn(envelope)
                    elif callable(run_task_fn):
                        legacy_summary = await run_task_fn(envelope.goal)
                        result = TaskResult(
                            task_id=envelope.task_id,
                            status="success",
                            summary=legacy_summary,
                            evidence=[],
                        )
                    else:
                        raise AttributeError(
                            f"Ajan '{spec.role_name}' ne handle ne de run_task metodu sağlıyor."
                        )
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

            if result is not None and _looks_like_delegation_request(result.summary):
                delegation = cast(DelegationRequest, result.summary)
                if not getattr(delegation, "reply_to", ""):
                    delegation.reply_to = spec.role_name
                bumped = delegation.bumped() if hasattr(delegation, "bumped") else delegation
                return await self._direct_handoff(
                    task,
                    cast(DelegationRequest, bumped),
                    session_id=session_id,
                    hop=_hop + 1,
                    route_trace=next_trace,
                    handoff_chain=handoff_chain,
                )

            elapsed = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "SwarmOrchestrator: [%s] → %s tamamlandı (%dms, status=%s)",
                task.task_id,
                spec.role_name,
                elapsed,
                result.status if result is not None else "unknown",
            )
            if result is not None and result.status == "success":
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
            if result is None:
                raise RuntimeError("Ajan geçerli TaskResult döndürmedi.")
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
                    "browser_signal_status": str(
                        task.context.get("browser_signal_status", "") or ""
                    ),
                    "browser_signal_risk": str(task.context.get("browser_signal_risk", "") or ""),
                    "browser_signal_summary": str(
                        task.context.get("browser_signal_summary", "") or ""
                    )[:300],
                },
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started_at) * 1000)
            logger.error("SwarmOrchestrator: [%s] hata [%s]: %s", task.task_id, spec.role_name, exc)
            if self._should_fallback_to_supervisor(exc):
                reason = f"fallback:{type(exc).__name__}"
                logger.warning(
                    "SwarmOrchestrator: [%s] supervisor fallback tetiklendi [%s] reason=%s",
                    task.task_id,
                    spec.role_name,
                    reason,
                )
                try:
                    return await self._run_supervisor_fallback(
                        task,
                        session_id=session_id,
                        started_at=started_at,
                        route_trace=next_trace,
                        handoff_chain=handoff_chain,
                        failed_role=spec.role_name,
                        reason=reason,
                    )
                except Exception as fallback_exc:
                    logger.error(
                        "SwarmOrchestrator: [%s] supervisor fallback hatası [%s]: %s",
                        task.task_id,
                        spec.role_name,
                        fallback_exc,
                    )
                    return SwarmResult(
                        task_id=task.task_id,
                        agent_role="supervisor",
                        status="failed",
                        summary=(
                            f"Görev başarısız: {exc}. "
                            f"Supervisor fallback da başarısız oldu: {fallback_exc}"
                        ),
                        elapsed_ms=elapsed,
                        handoffs=handoff_chain,
                    )
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

    def available_agents(self) -> list[str]:
        """Kayıtlı tüm ajan rollerini listeler."""
        return [spec.role_name for spec in AgentCatalog.list_all()]
