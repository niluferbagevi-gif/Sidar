"""Multi-agent iletişim kontratları (Supervisor <-> Specialist)."""

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
    """Ajanlar arası doğrudan delegasyon mesajı."""

    task_id: str
    reply_to: str
    target_agent: str
    payload: str
    meta: Dict[str, str] = field(default_factory=dict)


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
