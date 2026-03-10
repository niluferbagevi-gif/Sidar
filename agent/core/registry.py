"""Uzman ajan kayıt/keşif katmanı."""

from __future__ import annotations

from typing import Dict, Iterable

from agent.base_agent import BaseAgent


class AgentRegistry:
    """Role adına göre ajan örneklerini saklar."""

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, role: str, agent: BaseAgent) -> None:
        self._agents[role] = agent

    def get(self, role: str) -> BaseAgent:
        return self._agents[role]

    def has(self, role: str) -> bool:
        return role in self._agents

    def roles(self) -> Iterable[str]:
        return tuple(self._agents.keys())