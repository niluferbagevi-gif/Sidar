"""Supervisor ajanı: görevi role ajanlara yönlendirir."""

from __future__ import annotations

import uuid
from typing import Optional

from config import Config

from agent.base_agent import BaseAgent
from agent.core.contracts import TaskEnvelope, TaskResult
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent


class SupervisorAgent(BaseAgent):
    """İlk faz supervisor: araştırma ve kod görevlerini uzman ajanlara delege eder."""

    SYSTEM_PROMPT = (
        "Sen bir supervisor ajansın. Görevi doğru uzmana yönlendirir, "
        "desteklenmeyen alanlarda legacy fallback sinyali üretirsin."
    )

    LEGACY_FALLBACK = "[LEGACY_FALLBACK]"

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="supervisor")
        self.researcher = ResearcherAgent(self.cfg)
        self.coder = CoderAgent(self.cfg)

    @staticmethod
    def _intent(prompt: str) -> str:
        text = (prompt or "").lower()
        research_tokens = (
            "araştır", "web", "url", "kaynak", "docs", "doküman", "nedir", "yenilik"
        )
        code_tokens = (
            "kod yaz", "dosya", "patch", "refactor", "test", "debug", "hata",
            "package", "pypi", "npm", "grep", "glob", "audit"
        )
        review_tokens = ("github", "pr", "pull request", "issue")

        if any(t in text for t in research_tokens):
            return "research"
        if any(t in text for t in code_tokens):
            return "code"
        if any(t in text for t in review_tokens):
            return "review"
        return "unknown"

    async def run_task(self, task_prompt: str) -> str:
        intent = self._intent(task_prompt)
        task_id = str(uuid.uuid4())

        if intent == "research":
            envelope = TaskEnvelope(
                task_id=task_id,
                sender="supervisor",
                receiver="researcher",
                goal=task_prompt,
                intent="research",
            )
            summary = await self.researcher.run_task(envelope.goal)
            result = TaskResult(
                task_id=task_id,
                status="done",
                summary=summary,
            )
            return result.summary

        if intent == "code":
            envelope = TaskEnvelope(
                task_id=task_id,
                sender="supervisor",
                receiver="coder",
                goal=task_prompt,
                intent="code",
            )
            summary = await self.coder.run_task(envelope.goal)
            result = TaskResult(
                task_id=task_id,
                status="done" if not summary.startswith("[LEGACY_FALLBACK]") else "fallback",
                summary=summary,
            )
            if result.status == "done":
                return result.summary

        return f"{self.LEGACY_FALLBACK} intent={intent}"