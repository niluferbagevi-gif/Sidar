from agent.base_agent import BaseAgent


class UploadAgent(BaseAgent):
    """Yüklenen plugin akışları için minimum demo ajan."""

    async def run_task(self, task_prompt: str) -> str:
        prompt = str(task_prompt or "").strip()
        if not prompt:
            return "Boş görev alındı."
        return f"UploadAgent: {prompt}"
