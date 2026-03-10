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
    """Supervisor merkezli orkestrasyon: coder -> reviewer zincirini destekler."""

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
        review_goal = f"list_prs|open\ncontext:{code_result.summary[:500]}"
        review_result = await self._delegate("reviewer", review_goal, "review", parent_task_id=code_result.task_id)
        return f"{code_result.summary}\n\n---\nReviewer QA Özeti:\n{review_result.summary}"