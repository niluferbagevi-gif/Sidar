"""Sidar Multi-Agent iskeleti için temel soyut ajan sınıfı."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Dict, Optional

from config import Config
from core.llm_client import LLMClient

ToolFunc = Callable[[str], Awaitable[str]]


class BaseAgent(ABC):
    """Uzman ajanlar için ortak LLM + tool dispatch altyapısı."""

    SYSTEM_PROMPT = "You are a specialist agent."

    def __init__(self, cfg: Optional[Config] = None, *, role_name: str = "base") -> None:
        self.cfg = cfg or Config()
        self.role_name = role_name
        self.llm = LLMClient(self.cfg.AI_PROVIDER, self.cfg)
        self.tools: Dict[str, ToolFunc] = {}

    def register_tool(self, name: str, func: ToolFunc) -> None:
        self.tools[name] = func

    async def call_tool(self, name: str, arg: str) -> str:
        if name not in self.tools:
            return f"[HATA] '{name}' aracı bu ajan için tanımlı değil."
        return await self.tools[name](arg)

    @abstractmethod
    async def run_task(self, task_prompt: str) -> str:
        """Ajanın bir görevi role-özel araçlarla tamamlamasını sağlar."""