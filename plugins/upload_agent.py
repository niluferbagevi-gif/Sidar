
from agent.base_agent import BaseAgent

class FileAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return task_prompt
