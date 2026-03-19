"""Multi-agent iletişim kontratları (Supervisor <-> Specialist + direct P2P + federation)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

FEDERATION_PROTOCOL_V1 = "federation.v1"
LEGACY_FEDERATION_PROTOCOL_V1 = "swarm.federation.v1"
FEDERATION_PROTOCOL_ALIASES = frozenset({FEDERATION_PROTOCOL_V1, LEGACY_FEDERATION_PROTOCOL_V1})


def normalize_federation_protocol(protocol: object) -> str:
    """Federation protokol etiketlerini kanonik `federation.v1` değerine indirger."""
    value = str(protocol or "").strip().lower()
    if not value or value in FEDERATION_PROTOCOL_ALIASES:
        return FEDERATION_PROTOCOL_V1
    return value


@dataclass
class TaskEnvelope:
    """Supervisor tarafından role ajanlara iletilen görev zarfı."""

    task_id: str
    sender: str
    receiver: str
    goal: str
    intent: str = "mixed"
    parent_task_id: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    """Role ajanların Supervisor'a döndürdüğü yapısal sonuç."""

    task_id: str
    status: str
    summary: str | P2PMessage
    evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

@dataclass
class P2PMessage:
    """Ajanlar arası doğrudan handoff mesajı için ortak protokol."""

    task_id: str
    reply_to: str
    target_agent: str
    payload: str
    intent: str = "mixed"
    parent_task_id: str | None = None
    handoff_depth: int = 0
    protocol: str = "p2p.v1"
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def sender(self) -> str:
        return self.reply_to

    @property
    def receiver(self) -> str:
        return self.target_agent

    def bumped(self) -> P2PMessage:
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


@dataclass
class ExternalTrigger:
    """Webhook/cron gibi dış olaylar için standart tetik zarfı."""

    trigger_id: str
    source: str
    event_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    protocol: str = "trigger.v1"
    meta: dict[str, str] = field(default_factory=dict)

    def to_prompt(self) -> str:
        payload_blob = json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
        meta_blob = json.dumps(self.meta, ensure_ascii=False, sort_keys=True)
        return (
            f"[TRIGGER]\n"
            f"source={self.source}\n"
            f"event={self.event_name}\n"
            f"protocol={self.protocol}\n"
            f"meta={meta_blob}\n"
            f"payload={payload_blob}"
        )


@dataclass
class FederationTaskEnvelope:
    """Sidar ile dış ajan platformları arasındaki federasyon görevi."""

    task_id: str
    source_system: str
    source_agent: str
    target_system: str
    target_agent: str
    goal: str
    intent: str = "mixed"
    parent_task_id: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    protocol: str = FEDERATION_PROTOCOL_V1
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.protocol = normalize_federation_protocol(self.protocol)

    def to_task_envelope(self) -> TaskEnvelope:
        return TaskEnvelope(
            task_id=self.task_id,
            sender=f"{self.source_system}:{self.source_agent}",
            receiver=f"{self.target_system}:{self.target_agent}",
            goal=self.goal,
            intent=self.intent,
            parent_task_id=self.parent_task_id,
            context=dict(self.context),
            inputs=list(self.inputs),
        )

    def to_prompt(self) -> str:
        return (
            f"[FEDERATION TASK]\n"
            f"source_system={self.source_system}\n"
            f"source_agent={self.source_agent}\n"
            f"target_system={self.target_system}\n"
            f"target_agent={self.target_agent}\n"
            f"protocol={self.protocol}\n"
            f"intent={self.intent}\n"
            f"goal={self.goal}\n"
            f"context={json.dumps(self.context, ensure_ascii=False, sort_keys=True)}\n"
            f"inputs={json.dumps(self.inputs, ensure_ascii=False)}\n"
            f"meta={json.dumps(self.meta, ensure_ascii=False, sort_keys=True)}"
        )


@dataclass
class FederationTaskResult:
    """Federasyon üzerinden dönen yapısal sonuç."""

    task_id: str
    source_system: str
    source_agent: str
    target_system: str
    target_agent: str
    status: str
    summary: str
    protocol: str = FEDERATION_PROTOCOL_V1
    evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.protocol = normalize_federation_protocol(self.protocol)

    def to_task_result(self) -> TaskResult:
        return TaskResult(
            task_id=self.task_id,
            status=self.status,
            summary=self.summary,
            evidence=list(self.evidence),
            next_actions=list(self.next_actions),
        )

    def to_prompt(self) -> str:
        return (
            f"[FEDERATION RESULT]\n"
            f"source_system={self.source_system}\n"
            f"source_agent={self.source_agent}\n"
            f"target_system={self.target_system}\n"
            f"target_agent={self.target_agent}\n"
            f"protocol={self.protocol}\n"
            f"status={self.status}\n"
            f"summary={self.summary}\n"
            f"evidence={json.dumps(self.evidence, ensure_ascii=False)}\n"
            f"next_actions={json.dumps(self.next_actions, ensure_ascii=False)}\n"
            f"meta={json.dumps(self.meta, ensure_ascii=False, sort_keys=True)}"
        )


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


def is_external_trigger(value: object) -> bool:
    """ExternalTrigger benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, ExternalTrigger):
        return True
    required = ("trigger_id", "source", "event_name", "payload")
    return type(value).__name__ == "ExternalTrigger" and all(hasattr(value, attr) for attr in required)


def is_federation_task_envelope(value: object) -> bool:
    """FederationTaskEnvelope benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, FederationTaskEnvelope):
        return True
    required = ("task_id", "source_system", "source_agent", "target_system", "target_agent", "goal")
    return type(value).__name__ == "FederationTaskEnvelope" and all(
        hasattr(value, attr) for attr in required
    )


def is_federation_task_result(value: object) -> bool:
    """FederationTaskResult benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, FederationTaskResult):
        return True
    required = ("task_id", "source_system", "source_agent", "target_system", "target_agent", "status", "summary")
    return type(value).__name__ == "FederationTaskResult" and all(
        hasattr(value, attr) for attr in required
    )
