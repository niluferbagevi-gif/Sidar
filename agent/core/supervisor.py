"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

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
    """Supervisor merkezli orkestrasyon: coder -> reviewer -> (gerekirse coder) zinciri."""

    SYSTEM_PROMPT = "Sen bir supervisor ajansın. Görevi doğru uzmana yönlendirip çıktıyı birleştirirsin."

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="supervisor")
        self.registry = AgentRegistry()
        self.events = get_agent_event_bus()
        self.memory_hub = MemoryHub()

        self.registry.register("researcher", ResearcherAgent(self.cfg))
        self.registry.register("coder", CoderAgent(self.cfg))
        self.registry.register("reviewer", ReviewerAgent(self.cfg))

        self.researcher = self.registry.get("researcher")
        self.coder = self.registry.get("coder")
        self.reviewer = self.registry.get("reviewer")

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
            result = await self._delegate(
                current.target_agent,
                current.payload,
                intent="p2p",
                parent_task_id=parent_task_id,
                sender=current.reply_to,
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
        if self._review_requires_revision(review_summary):
            revise_prompt = (
                "Reviewer geri bildirimi sonrası düzeltme yap. "
                f"Orijinal görev: {task_prompt}\n"
                f"Reviewer notu: {review_summary[:800]}"
            )
            await self.events.publish("supervisor", "Reviewer geri bildirimi sonrası ikinci kod turu başlatılıyor...")
            second_code = await self._delegate("coder", revise_prompt, "code", parent_task_id=review_result.task_id)
            if isinstance(second_code.summary, DelegationRequest):
                second_code = await self._route_p2p(second_code.summary, parent_task_id=second_code.task_id)

            second_summary = str(second_code.summary)
            await self.events.publish("supervisor", "Final reviewer kontrolü çalıştırılıyor...")
            final_review = await self._delegate(
                "reviewer",
                f"review_code|{second_summary[:800]}",
                "review",
                parent_task_id=second_code.task_id,
            )
            if isinstance(final_review.summary, DelegationRequest):
                final_review = await self._route_p2p(final_review.summary, parent_task_id=final_review.task_id)
            return (
                f"{second_summary}\n\n---\n"
                f"Reviewer QA Özeti (2. tur):\n{final_review.summary}"
            )

        return f"{code_summary}\n\n---\nReviewer QA Özeti:\n{review_summary}"
