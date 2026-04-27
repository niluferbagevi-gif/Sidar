"""Uzman ajan kayıt/keşif katmanı."""

from __future__ import annotations

from collections.abc import Iterable

from agent.base_agent import BaseAgent


class ActiveAgentRegistry:
    """Role adına göre ajan örneklerini saklar."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, role: str, agent: BaseAgent) -> None:
        self._agents[role] = agent

    def get(self, role: str) -> BaseAgent:
        if role not in self._agents:
            raise KeyError(f"'{role}' rolü kayıtlı değil. Mevcut roller: {sorted(self._agents)}")
        return self._agents[role]

    def has(self, role: str) -> bool:
        return role in self._agents

    def roles(self) -> Iterable[str]:
        return tuple(self._agents.keys())


# Geriye dönük uyumluluk
AgentRegistry = ActiveAgentRegistry
