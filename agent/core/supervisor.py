"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

import asyncio
import importlib
import json
import time
import uuid
from typing import Dict, Optional

from config import Config

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult, is_delegation_request
from agent.core.memory_hub import MemoryHub
from agent.core.registry import ActiveAgentRegistry
from agent.core.event_stream import get_agent_event_bus
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent
from agent.roles.poyraz_agent import PoyrazAgent
from agent.roles.qa_agent import QAAgent
from agent.roles.coverage_agent import CoverageAgent


def _ensure_delegation_request_shape():
    contracts_mod = importlib.import_module("agent.core.contracts")
    req_cls = getattr(contracts_mod, "DelegationRequest", None)
    if req_cls is not object:
        return req_cls

    class _CompatDelegationRequest:
        def __init__(self, **kwargs) -> None:
            self.task_id = kwargs.get("task_id", "")
            self.reply_to = kwargs.get("reply_to", "")
            self.target_agent = kwargs.get("target_agent", "")
            self.payload = kwargs.get("payload", "")
            self.intent = kwargs.get("intent", "mixed")
            self.parent_task_id = kwargs.get("parent_task_id")
            self.handoff_depth = int(kwargs.get("handoff_depth", 0) or 0)
            self.protocol = kwargs.get("protocol", "p2p.v1")
            self.meta = dict(kwargs.get("meta", {}) or {})

        def bumped(self):
            return type(self)(
                task_id=self.task_id,
                reply_to=self.reply_to,
                target_agent=self.target_agent,
                payload=self.payload,
                intent=self.intent,
                parent_task_id=self.parent_task_id,
                handoff_depth=self.handoff_depth + 1,
                protocol=self.protocol,
                meta=dict(self.meta),
            )

    contracts_mod.DelegationRequest = _CompatDelegationRequest
    return _CompatDelegationRequest


DelegationRequest = _ensure_delegation_request_shape()

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
        self.cfg = cfg or Config()
        self.role_name = "supervisor"
        self.llm = None
        self.tools = {}
        base_init_failed = False
        try:
            # `super()` zincirinin testlerde farklı bir BaseAgent referansına bağlı kalabildiği
            # durumlarda monkeypatch beklentisini deterministic tutmak için doğrudan çağır.
            BaseAgent.__init__(self, cfg=self.cfg, role_name="supervisor")
        except (TypeError, AttributeError):
            # İzolasyon testlerinde BaseAgent init'i stub olabilir veya minimal cfg nesnesi
            # zorunlu alanları (örn. AI_PROVIDER) içermeyebilir.
            base_init_failed = True

        self.registry = ActiveAgentRegistry()
        self.events = get_agent_event_bus()
        self.memory_hub = MemoryHub()

        if base_init_failed:
            # Base init başarısızsa, alt ajanlar da aynı sebeple kırılabilir.
            # Bu durumda supervisor minimal ama güvenli state ile ayağa kalkar.
            self.researcher = None
            self.coder = None
            self.reviewer = None
            self.poyraz = None
            self.qa = None
            self.coverage = None
            return

        try:
            self.registry.register("researcher", ResearcherAgent(self.cfg))
            self.registry.register("coder", CoderAgent(self.cfg))
            self.registry.register("reviewer", ReviewerAgent(self.cfg))
            self.registry.register("poyraz", PoyrazAgent(self.cfg))
            self.registry.register("qa", QAAgent(self.cfg))

            self.researcher = self.registry.get("researcher")
            self.coder = self.registry.get("coder")
            self.reviewer = self.registry.get("reviewer")
            self.poyraz = self.registry.get("poyraz")
            self.qa = self.registry.get("qa")
            try:
                self.registry.register("coverage", CoverageAgent(self.cfg))
                self.coverage = self.registry.get("coverage")
            except Exception:
                self.coverage = self.qa
        except (TypeError, AttributeError):
            # BaseAgent stub'ının object olduğu test ortamlarında alt ajan kurulumunu atla.
            # Bazı izolasyon testlerinde BaseAgent init'i AttributeError da yükseltebilir.
            self.researcher = None
            self.coder = None
            self.reviewer = None
            self.poyraz = None
            self.qa = None
            self.coverage = None

    @staticmethod
    def _intent(prompt: str) -> str:
        text = (prompt or "").lower()
        if any(t in text for t in ("araştır", "web", "url", "kaynak", "docs", "doküman", "nedir", "yenilik")):
            return "research"
        if any(t in text for t in ("github", "pull request", "issue", "review", "incele")):
            return "review"
        if any(t in text for t in ("seo", "kampanya", "pazarlama", "hedef kitle", "growth", "funnel", "reklam")):
            return "marketing"
        if any(t in text for t in ("coverage", "kapsama", "pytest", "eksik test", "test yaz", "test üret", "qa")):
            return "coverage"
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

        if intent == "marketing":
            await self.events.publish("supervisor", "Poyraz ajanına yönlendiriliyor...")
            result = await self._delegate("poyraz", task_prompt, "marketing")
            if is_delegation_request(result.summary):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        if intent == "coverage":
            await self.events.publish("supervisor", "Coverage ajanına yönlendiriliyor...")
            receiver = "coverage" if self.registry.has("coverage") else "qa"
            result = await self._delegate(receiver, task_prompt, "coverage")
            if is_delegation_request(result.summary):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        await self.events.publish("supervisor", "Coder ajanı kod üzerinde çalışıyor...")
        code_result = await self._delegate("coder", task_prompt, "code")
        if is_delegation_request(code_result.summary):
            code_result = await self._route_p2p(code_result.summary, parent_task_id=code_result.task_id)

        code_summary = str(code_result.summary)
        if bool(getattr(getattr(self, "cfg", None), "CLI_FAST_MODE", False)):
            await self.events.publish(
                "supervisor",
                "CLI fast mode aktif: reviewer kalite kapısı atlandı, coder çıktısı döndürülüyor...",
            )
            return code_summary

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
