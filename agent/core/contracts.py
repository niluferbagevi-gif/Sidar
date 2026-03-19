"""Multi-agent iletişim kontratları (Supervisor <-> Specialist + direct P2P)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TaskEnvelope:
    """Supervisor tarafından role ajanlara iletilen görev zarfı."""

    task_id: str
    sender: str
    receiver: str
    goal: str
    intent: str = "mixed"
    parent_task_id: Optional[str] = None
    context: Dict[str, str] = field(default_factory=dict)
    inputs: List[str] = field(default_factory=list)


@dataclass
class TaskResult:
    """Role ajanların Supervisor'a döndürdüğü yapısal sonuç."""

    task_id: str
    status: str
    summary: str | P2PMessage
    evidence: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)

@dataclass
class P2PMessage:
    """Ajanlar arası doğrudan handoff mesajı için ortak protokol."""

    task_id: str
    reply_to: str
    target_agent: str
    payload: str
    intent: str = "mixed"
    parent_task_id: Optional[str] = None
    handoff_depth: int = 0
    protocol: str = "p2p.v1"
    meta: Dict[str, str] = field(default_factory=dict)

    @property
    def sender(self) -> str:
        return self.reply_to

    @property
    def receiver(self) -> str:
        return self.target_agent

    def bumped(self) -> "P2PMessage":
        return type(self)(
            task_id=self.task_id,
            reply_to=self.reply_to,
            target_agent=self.target_agent,
            payload=self.payload,
            intent=self.intent,
            parent_task_id=self.parent_task_id,
            handoff_depth=self.handoff_depth + 1,
            protocol=self.protocol,
            meta=dict(self.meta),
        )


@dataclass
class DelegationRequest(P2PMessage):
    """P2P yönlendirme isteği (router tarafından hedef ajana taşınır)."""


@dataclass
class DelegationResult:
    """P2P delegasyon sonucu."""

    task_id: str
    source_agent: str
    target_agent: str
    status: str
    content: str


def is_p2p_message(value: object) -> bool:
    """P2PMessage/DelegationRequest benzeri nesneleri sınıf farklarından bağımsız tanımlar."""
    if isinstance(value, P2PMessage):
        return True
    required = ("task_id", "reply_to", "target_agent", "payload")
    return type(value).__name__ in {"P2PMessage", "DelegationRequest"} and all(
        hasattr(value, attr) for attr in required
    )


def is_delegation_request(value: object) -> bool:
    """DelegationRequest benzeri nesneleri sınıf-referans farklarına rağmen tanımlar."""
    if isinstance(value, DelegationRequest):
        return True
    return type(value).__name__ == "DelegationRequest" and is_p2p_message(value)