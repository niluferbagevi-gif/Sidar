"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from config import Config

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult
from agent.core.memory_hub import MemoryHub
from agent.core.registry import AgentRegistry
from agent.core.event_stream import get_agent_event_bus
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent


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
            "regresyon",
            "hata",
            "risk: yüksek",
            "iyileştirme gerekli",
            "düzelt",
        )
        return any(sig in text for sig in revision_signals)

    async def _delegate(self, receiver: str, goal: str, intent: str, parent_task_id: Optional[str] = None, sender: str = "supervisor") -> TaskResult:
        task_id = str(uuid.uuid4())
        envelope = TaskEnvelope(
            task_id=task_id,
            sender=sender,
            receiver=receiver,
            goal=goal,
            intent=intent,
            parent_task_id=parent_task_id,
        )
        agent = self.registry.get(receiver)
        summary = await agent.run_task(envelope.goal)
        self.memory_hub.add_role_note(receiver, str(summary))
        return TaskResult(task_id=task_id, status="done", summary=summary)

    async def _route_p2p(self, request: DelegationRequest, *, parent_task_id: Optional[str] = None, max_hops: int = 4) -> TaskResult:
        """P2P delegasyon isteğini hedef ajana ileten hafif router köprüsü."""
        hop = 0
        current = request
        while hop < max_hops:
            hop += 1
            await self.events.publish("supervisor", f"P2P yönlendirme: {current.reply_to} → {current.target_agent}")
            result = await asyncio.wait_for(
                self._delegate(
                    current.target_agent,
                    current.payload,
                    intent="p2p",
                    parent_task_id=parent_task_id,
                    sender=current.reply_to,
                ),
                timeout=getattr(getattr(self, "cfg", None), "REACT_TIMEOUT", 60),
            )
            if isinstance(result.summary, DelegationRequest):
                current = result.summary
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
            if isinstance(result.summary, DelegationRequest):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        if intent == "review":
            await self.events.publish("supervisor", "Reviewer ajanına yönlendiriliyor...")
            result = await self._delegate("reviewer", task_prompt, "review")
            if isinstance(result.summary, DelegationRequest):
                result = await self._route_p2p(result.summary, parent_task_id=result.task_id)
            return str(result.summary)

        await self.events.publish("supervisor", "Coder ajanı kod üzerinde çalışıyor...")
        code_result = await self._delegate("coder", task_prompt, "code")
        if isinstance(code_result.summary, DelegationRequest):
            code_result = await self._route_p2p(code_result.summary, parent_task_id=code_result.task_id)

        code_summary = str(code_result.summary)
        review_goal = f"review_code|{code_summary[:800]}"
        await self.events.publish("supervisor", "Reviewer kodu inceliyor ve testleri değerlendiriyor...")
        review_result = await self._delegate("reviewer", review_goal, "review", parent_task_id=code_result.task_id)
        if isinstance(review_result.summary, DelegationRequest):
            review_result = await self._route_p2p(review_result.summary, parent_task_id=review_result.task_id)

        review_summary = str(review_result.summary)
        retries = 0
        latest_code_summary = code_summary

        while self._review_requires_revision(review_summary):
            retries += 1
            if retries > self.MAX_QA_RETRIES:
                return (
                    f"{latest_code_summary}\n\n---\n"
                    f"Reviewer QA Özeti (limit aşıldı):\n{review_summary}\n"
                    f"[P2P:STOP] Maksimum QA retry limiti aşıldı ({self.MAX_QA_RETRIES})."
                )

            revise_prompt = (
                "Reviewer geri bildirimi sonrası düzeltme yap. "
                f"Orijinal görev: {task_prompt}\n"
                f"Reviewer notu: {review_summary[:800]}"
            )
            await self.events.publish("supervisor", f"Reviewer geri bildirimi sonrası kod turu başlatılıyor ({retries}/{self.MAX_QA_RETRIES})...")
            next_code = await self._delegate("coder", revise_prompt, "code", parent_task_id=review_result.task_id)
            if isinstance(next_code.summary, DelegationRequest):
                next_code = await self._route_p2p(next_code.summary, parent_task_id=next_code.task_id)

            latest_code_summary = str(next_code.summary)
            await self.events.publish("supervisor", "Reviewer kontrolü tekrar çalıştırılıyor...")
            review_result = await self._delegate(
                "reviewer",
                f"review_code|{latest_code_summary[:800]}",
                "review",
                parent_task_id=next_code.task_id,
            )
            if isinstance(review_result.summary, DelegationRequest):
                review_result = await self._route_p2p(review_result.summary, parent_task_id=review_result.task_id)
            review_summary = str(review_result.summary)

        suffix = f" ({retries + 1}. tur)" if retries else ""
        return f"{latest_code_summary}\n\n---\nReviewer QA Özeti{suffix}:\n{review_summary}"
