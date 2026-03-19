"""Sidar Multi-Agent iskeleti için temel soyut ajan sınıfı."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Dict, Optional

from agent.core.contracts import DelegationRequest, TaskEnvelope, TaskResult, is_delegation_request

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


    async def call_llm(
        self,
        messages,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> str:
        response = await self.llm.chat(
            messages=messages,
            model=model,
            system_prompt=system_prompt or self.SYSTEM_PROMPT,
            temperature=temperature,
            stream=False,
            json_mode=json_mode,
        )
        return str(response)



    def delegate_to(
        self,
        target_agent: str,
        payload: str,
        *,
        task_id: str = "",
        reason: str = "",
        intent: str = "mixed",
        parent_task_id: str = "",
        handoff_depth: int = 0,
    ) -> DelegationRequest:
        """Uzman ajanın başka bir uzmana P2P delegasyon isteği oluşturmasını sağlar."""
        safe_task_id = task_id or f"p2p-{self.role_name}"
        meta = {"reason": reason} if reason else {}
        return DelegationRequest(
            task_id=safe_task_id,
            reply_to=self.role_name,
            target_agent=target_agent,
            payload=payload,
            intent=intent,
            parent_task_id=parent_task_id or None,
            handoff_depth=max(0, int(handoff_depth or 0)),
            meta=meta,
        )

    @staticmethod
    def is_delegation_message(result: object) -> bool:
        return is_delegation_request(result)

    async def handle(self, envelope: TaskEnvelope) -> TaskResult:
        """TaskEnvelope taşıyıcılarını ortak biçimde işler.

        SwarmOrchestrator gerçek ajan örneklerini de envelope tabanlı çalıştırabildiği için
        varsayılan davranış burada tutulur.
        """
        summary = await self.run_task(envelope.goal)
        if is_delegation_request(summary):
            if not getattr(summary, "task_id", ""):
                summary.task_id = envelope.task_id
            if not getattr(summary, "parent_task_id", None):
                summary.parent_task_id = envelope.parent_task_id or envelope.task_id
            summary.handoff_depth = max(
                int(getattr(summary, "handoff_depth", 0) or 0),
                int(envelope.context.get("p2p_handoff_depth", "0") or 0),
            )
        return TaskResult(
            task_id=envelope.task_id,
            status="success",
            summary=summary,
            evidence=[],
        )


    @abstractmethod
    async def run_task(self, task_prompt: str) -> str | DelegationRequest:
        """Ajanın bir görevi role-özel araçlarla tamamlamasını sağlar."""