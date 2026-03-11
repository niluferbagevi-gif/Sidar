"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

import uuid
from typing import Optional

from config import Config

from agent.base_agent import BaseAgent
from agent.core.contracts import TaskEnvelope, TaskResult
from agent.core.memory_hub import MemoryHub
from agent.core.registry import AgentRegistry
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent


class SupervisorAgent(BaseAgent):
    """Supervisor merkezli orkestrasyon: coder -> reviewer -> (gerekirse coder) zinciri."""

    SYSTEM_PROMPT = "Sen bir supervisor ajansın. Görevi doğru uzmana yönlendirip çıktıyı birleştirirsin."

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="supervisor")
        self.registry = AgentRegistry()
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

    async def _delegate(self, receiver: str, goal: str, intent: str, parent_task_id: Optional[str] = None) -> TaskResult:
        task_id = str(uuid.uuid4())
        envelope = TaskEnvelope(
            task_id=task_id,
            sender="supervisor",
            receiver=receiver,
            goal=goal,
            intent=intent,
            parent_task_id=parent_task_id,
        )
        agent = self.registry.get(receiver)
        summary = await agent.run_task(envelope.goal)
        self.memory_hub.add_role_note(receiver, summary)
        return TaskResult(task_id=task_id, status="done", summary=summary)

    async def run_task(self, task_prompt: str) -> str:
        intent = self._intent(task_prompt)
        self.memory_hub.add_global(task_prompt)

        if intent == "research":
            result = await self._delegate("researcher", task_prompt, "research")
            return result.summary

        if intent == "review":
            result = await self._delegate("reviewer", task_prompt, "review")
            return result.summary

        code_result = await self._delegate("coder", task_prompt, "code")
        review_goal = f"review_code|{code_result.summary[:800]}"
        review_result = await self._delegate("reviewer", review_goal, "review", parent_task_id=code_result.task_id)

        if self._review_requires_revision(review_result.summary):
            revise_prompt = (
                "Reviewer geri bildirimi sonrası düzeltme yap. "
                f"Orijinal görev: {task_prompt}\n"
                f"Reviewer notu: {review_result.summary[:800]}"
            )
            second_code = await self._delegate("coder", revise_prompt, "code", parent_task_id=review_result.task_id)
            final_review = await self._delegate(
                "reviewer",
                f"review_code|{second_code.summary[:800]}",
                "review",
                parent_task_id=second_code.task_id,
            )
            return (
                f"{second_code.summary}\n\n---\n"
                f"Reviewer QA Özeti (2. tur):\n{final_review.summary}"
            )

        return f"{code_result.summary}\n\n---\nReviewer QA Özeti:\n{review_result.summary}"