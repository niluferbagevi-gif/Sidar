"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Dict, Optional

from config import Config

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult, is_delegation_request
from agent.core.memory_hub import MemoryHub
from agent.core.registry import AgentRegistry
from agent.core.event_stream import get_agent_event_bus
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent

try:
    from opentelemetry import trace as otel_trace
    _tracer = otel_trace.get_tracer("sidar.supervisor")
except Exception:  # pragma: no cover
    _tracer = None  # type: ignore[assignment]

try:
    from core.agent_metrics import get_agent_metrics_collector as _get_agent_metrics
except Exception:  # pragma: no cover
    _get_agent_metrics = None  # type: ignore[assignment]


class _NullSpan:
    """OTel bağımlılığı yokken `with _tracer.start_as_current_span(...)` yerine kullanılır."""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def set_attribute(self, *_args):
        pass


class SupervisorAgent(BaseAgent):
    MAX_QA_RETRIES = 3
    """Supervisor merkezli orkestrasyon: coder -> reviewer -> (gerekirse coder) zinciri."""

    SYSTEM_PROMPT = "Sen bir supervisor ajansın. Görevi doğru uzmana yönlendirip çıktıyı birleştirirsin."

    def __init__(self, cfg: Optional[Config] = None) -> None:
        try:
            super().__init__(cfg=cfg, role_name="supervisor")
        except TypeError:
            # Bazı izolasyon testlerinde BaseAgent, yalın ``object`` ile stub'lanır.
            # Bu durumda object.__init__ yalnızca ``self`` kabul eder.
            self.cfg = cfg or Config()
            self.role_name = "supervisor"
            self.llm = None
            self.tools = {}

        self.registry = AgentRegistry()
        self.events = get_agent_event_bus()
        self.memory_hub = MemoryHub()

        try:
            self.registry.register("researcher", ResearcherAgent(self.cfg))
            self.registry.register("coder", CoderAgent(self.cfg))
            self.registry.register("reviewer", ReviewerAgent(self.cfg))

            self.researcher = self.registry.get("researcher")
            self.coder = self.registry.get("coder")
            self.reviewer = self.registry.get("reviewer")
        except TypeError:
            # BaseAgent stub'ının object olduğu test ortamlarında alt ajan kurulumunu atla.
            self.researcher = None
            self.coder = None
            self.reviewer = None

    @staticmethod
    def _intent(prompt: str) -> str:
        text = (prompt or "").lower()
        if any(t in text for t in ("araştır", "web", "url", "kaynak", "docs", "doküman", "nedir", "yenilik")):
            return "research"
        if any(t in text for t in ("github", "pull request", "issue", "review", "incele")):
            return "review"
        return "code"

    @staticmethod
    def _review_requires_revision(review_summary: str) -> bool:
        text = (review_summary or "").lower()
        revision_signals = (
            "fail(",
            "[test:fail",
            "[test:fail-closed",
            "regresyon",
            "hata",
            "risk: yüksek",
            "iyileştirme gerekli",
            "düzelt",
            "decision=reject",
            "rework_required",
        )
        return any(sig in text for sig in revision_signals)

    def _max_qa_retries(self) -> int:
        return int(getattr(getattr(self, "cfg", None), "MAX_QA_RETRIES", self.MAX_QA_RETRIES))

    @staticmethod
    def _is_reject_feedback_payload(payload: object) -> bool:
        text = str(payload or "")
        if not text.startswith("qa_feedback|"):
            return False
        body = text.split("|", 1)[1].strip()
        if not body:
            return False
        if body.startswith("{"):
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                return "decision=reject" in body.lower()
            return str(parsed.get("decision", "")).strip().lower() == "reject"
        return "decision=reject" in body.lower()

    async def _delegate(
        self,
        receiver: str,
        goal: str,
        intent: str,
        parent_task_id: Optional[str] = None,
        sender: str = "supervisor",
        context: Optional[Dict[str, str]] = None,
    ) -> TaskResult:
        task_id = str(uuid.uuid4())
        envelope = TaskEnvelope(
            task_id=task_id,
            sender=sender,
            receiver=receiver,
            goal=goal,
            intent=intent,
            parent_task_id=parent_task_id,
            context=dict(context or {}),
        )
        agent = self.registry.get(receiver)

        t0 = time.monotonic()
        status = "done"
        span_ctx = (
            _tracer.start_as_current_span(
                f"supervisor.delegate.{receiver}",
                attributes={
                    "sidar.receiver": receiver,
                    "sidar.intent": intent,
                    "sidar.task_id": task_id,
                    "sidar.parent_task_id": parent_task_id or "",
                },
            )
            if _tracer is not None
            else _NullSpan()
        )
        try:
            with span_ctx as span:
                summary = await agent.run_task(envelope.goal)
                if span is not None and hasattr(span, "set_attribute"):
                    span.set_attribute("sidar.result_len", len(str(summary)))
        except Exception:
            status = "error"
            raise
        finally:
            duration_s = time.monotonic() - t0
            if _get_agent_metrics is not None:
                try:
                    _get_agent_metrics().record(receiver, intent, status, duration_s)
                except Exception:
                    pass

        self.memory_hub.add_role_note(receiver, str(summary))
        return TaskResult(task_id=task_id, status=status, summary=summary)

    async def _route_p2p(self, request: DelegationRequest, *, parent_task_id: Optional[str] = None, max_hops: int = 4) -> TaskResult:
        """P2P delegasyon isteğini hedef ajana ileten hafif router köprüsü."""
        hop = 0
        qa_retries = 0
        current = request
        while hop < max_hops:
            hop += 1
            if current.target_agent == "coder" and self._is_reject_feedback_payload(current.payload):
                qa_retries += 1
                if qa_retries > self._max_qa_retries():
                    return TaskResult(
                        task_id=str(uuid.uuid4()),
                        status="failed",
                        summary=(
                            f"[P2P:STOP] Maksimum QA retry limiti aşıldı ({self._max_qa_retries()}). "
                            "Reviewer red zinciri fail-closed sonlandırıldı."
                        ),
                    )
            await self.events.publish("supervisor", f"P2P yönlendirme: {current.reply_to} → {current.target_agent}")
            result = await asyncio.wait_for(
                self._delegate(
                    current.target_agent,
                    current.payload,
                    intent=current.intent or "p2p",
                    parent_task_id=current.parent_task_id or parent_task_id or current.task_id,
                    sender=current.reply_to,
                    context={
                        "p2p_protocol": current.protocol,
                        "p2p_sender": current.reply_to,
                        "p2p_receiver": current.target_agent,
                        "p2p_reason": str(current.meta.get("reason", "")),
                        "p2p_handoff_depth": str(current.handoff_depth),
                    },
                ),
                timeout=getattr(getattr(self, "cfg", None), "REACT_TIMEOUT", 60),
            )
            if is_delegation_request(result.summary):
                current = result.summary.bumped() if hasattr(result.summary, "bumped") else result.summary
                continue
            return result
        return TaskResult(task_id=str(uuid.uuid4()), status="failed", summary="[P2P:FAIL] Maksimum delegasyon hop sayısı aşıldı.")

    async def run_task(self, task_prompt: str) -> str:
        await self.events.publish("supervisor", "Görev analiz ediliyor...")
        intent = self._intent(task_prompt)
        self.memory_hub.add_global(task_prompt)

        if intent == "research":
            await self.events.publish("supervisor", "Researcher ajanına yönlendiriliyor...")
            result = await self._delegate("researcher", task_prompt, "research")
            if is_delegation_request(result.summary):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        if intent == "review":
            await self.events.publish("supervisor", "Reviewer ajanına yönlendiriliyor...")
            result = await self._delegate("reviewer", task_prompt, "review")
            if is_delegation_request(result.summary):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        await self.events.publish("supervisor", "Coder ajanı kod üzerinde çalışıyor...")
        code_result = await self._delegate("coder", task_prompt, "code")
        if is_delegation_request(code_result.summary):
            code_result = await self._route_p2p(code_result.summary, parent_task_id=code_result.task_id)

        code_summary = str(code_result.summary)
        review_goal = f"review_code|{code_summary[:800]}"
        await self.events.publish("supervisor", "Reviewer kodu inceliyor ve testleri değerlendiriyor...")
        review_result = await self._delegate("reviewer", review_goal, "review", parent_task_id=code_result.task_id)
        if is_delegation_request(review_result.summary):
            review_result = await self._route_p2p(review_result.summary, parent_task_id=review_result.task_id)

        review_summary = str(review_result.summary)
        retries = 0
        latest_code_summary = code_summary

        while self._review_requires_revision(review_summary):
            retries += 1
            if retries > self._max_qa_retries():
                return (
                    f"{latest_code_summary}\n\n---\n"
                    f"Reviewer QA Özeti (limit aşıldı):\n{review_summary}\n"
                    f"[P2P:STOP] Maksimum QA retry limiti aşıldı ({self._max_qa_retries()})."
                )

            revise_prompt = (
                "Reviewer geri bildirimi sonrası düzeltme yap. "
                f"Orijinal görev: {task_prompt}\n"
                f"Reviewer notu: {review_summary[:800]}"
            )
            await self.events.publish("supervisor", f"Reviewer geri bildirimi sonrası kod turu başlatılıyor ({retries}/{self._max_qa_retries()})...")
            next_code = await self._delegate("coder", revise_prompt, "code", parent_task_id=review_result.task_id)
            if is_delegation_request(next_code.summary):
                next_code = await self._route_p2p(next_code.summary, parent_task_id=next_code.task_id)

            latest_code_summary = str(next_code.summary)
            await self.events.publish("supervisor", "Reviewer kontrolü tekrar çalıştırılıyor...")
            review_result = await self._delegate(
                "reviewer",
                f"review_code|{latest_code_summary[:800]}",
                "review",
                parent_task_id=next_code.task_id,
            )
            if is_delegation_request(review_result.summary):
                review_result = await self._route_p2p(review_result.summary, parent_task_id=review_result.task_id)
            review_summary = str(review_result.summary)

        suffix = f" ({retries + 1}. tur)" if retries else ""
        return f"{latest_code_summary}\n\n---\nReviewer QA Özeti{suffix}:\n{review_summary}"
