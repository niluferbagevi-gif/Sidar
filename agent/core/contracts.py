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
    summary: str
    evidence: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
