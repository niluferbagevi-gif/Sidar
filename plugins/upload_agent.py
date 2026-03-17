"""Basit upload plugin ajanı."""

from __future__ import annotations

from agent.base_agent import BaseAgent


class UploadAgent(BaseAgent):
    """Yüklenen plugin akışları için minimum demo ajan."""

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "Boş görev alındı."
        return f"UploadAgent: {prompt}"