"""Multi-agent iletişim kontratları (Supervisor <-> Specialist + direct P2P + federation)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

FEDERATION_PROTOCOL_V1 = "federation.v1"
LEGACY_FEDERATION_PROTOCOL_V1 = "swarm.federation.v1"
FEDERATION_PROTOCOL_ALIASES = frozenset({FEDERATION_PROTOCOL_V1, LEGACY_FEDERATION_PROTOCOL_V1})
ACTION_FEEDBACK_PROTOCOL_V1 = "action_feedback.v1"
BROKER_PROTOCOL_V1 = "broker.task.v1"
LEGACY_BROKER_PROTOCOL_V1 = "swarm.broker.v1"
BROKER_PROTOCOL_ALIASES = frozenset({BROKER_PROTOCOL_V1, LEGACY_BROKER_PROTOCOL_V1})


def normalize_federation_protocol(protocol: object) -> str:
    """Federation protokol etiketlerini kanonik `federation.v1` değerine indirger."""
    value = str(protocol or "").strip().lower()
    if not value or value in FEDERATION_PROTOCOL_ALIASES:
        return FEDERATION_PROTOCOL_V1
    return value


def normalize_broker_protocol(protocol: object) -> str:
    """Broker protokol etiketlerini kanonik `broker.task.v1` değerine indirger."""
    value = str(protocol or "").strip().lower()
    if not value or value in BROKER_PROTOCOL_ALIASES:
        return BROKER_PROTOCOL_V1
    return value


def derive_broker_routing_key(*, receiver: str, intent: str, namespace: str = "sidar.swarm") -> str:
    role = str(receiver or "unknown").strip().lower() or "unknown"
    topic = str(intent or "mixed").strip().lower() or "mixed"
    ns = str(namespace or "sidar.swarm").strip().lower() or "sidar.swarm"
    return f"{ns}.{role}.{topic}"


def derive_correlation_id(*values: object) -> str:
    """Dış sistemler arası iz sürme için ilk anlamlı correlation id değerini seç."""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


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
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.meta.get("correlation_id", ""),
            self.payload.get("correlation_id", "") if isinstance(self.payload, dict) else "",
            self.payload.get("task_id", "") if isinstance(self.payload, dict) else "",
            self.trigger_id,
        )

    def to_prompt(self) -> str:
        payload_blob = json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
        meta_blob = json.dumps(self.meta, ensure_ascii=False, sort_keys=True)
        return (
            f"[TRIGGER]\n"
            f"source={self.source}\n"
            f"event={self.event_name}\n"
            f"protocol={self.protocol}\n"
            f"correlation_id={self.correlation_id}\n"
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
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.protocol = normalize_federation_protocol(self.protocol)
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.meta.get("correlation_id", ""),
            self.parent_task_id,
            self.task_id,
        )

    def to_task_envelope(self) -> TaskEnvelope:
        return TaskEnvelope(
            task_id=self.task_id,
            sender=f"{self.source_system}:{self.source_agent}",
            receiver=f"{self.target_system}:{self.target_agent}",
            goal=self.goal,
            intent=self.intent,
            parent_task_id=self.parent_task_id,
            context={**dict(self.context), "correlation_id": self.correlation_id},
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
            f"correlation_id={self.correlation_id}\n"
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
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.protocol = normalize_federation_protocol(self.protocol)
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.meta.get("correlation_id", ""),
            self.task_id,
        )

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
            f"correlation_id={self.correlation_id}\n"
            f"status={self.status}\n"
            f"summary={self.summary}\n"
            f"evidence={json.dumps(self.evidence, ensure_ascii=False)}\n"
            f"next_actions={json.dumps(self.next_actions, ensure_ascii=False)}\n"
            f"meta={json.dumps(self.meta, ensure_ascii=False, sort_keys=True)}"
        )


@dataclass
class BrokerTaskEnvelope:
    """Message broker üzerinden pod'lar arası taşınacak görev zarfı."""

    task_id: str
    sender: str
    receiver: str
    goal: str
    intent: str = "mixed"
    parent_task_id: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    broker: str = "memory"
    exchange: str = "sidar.swarm"
    routing_key: str = ""
    reply_queue: str = ""
    protocol: str = BROKER_PROTOCOL_V1
    headers: dict[str, str] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.protocol = normalize_broker_protocol(self.protocol)
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.headers.get("correlation_id", ""),
            self.parent_task_id,
            self.task_id,
        )
        if not self.routing_key:
            self.routing_key = derive_broker_routing_key(
                receiver=self.receiver, intent=self.intent, namespace=self.exchange
            )

    @classmethod
    def from_task_envelope(
        cls,
        envelope: TaskEnvelope,
        *,
        broker: str = "memory",
        exchange: str = "sidar.swarm",
        reply_queue: str = "",
        headers: dict[str, str] | None = None,
    ) -> BrokerTaskEnvelope:
        return cls(
            task_id=envelope.task_id,
            sender=envelope.sender,
            receiver=envelope.receiver,
            goal=envelope.goal,
            intent=envelope.intent,
            parent_task_id=envelope.parent_task_id,
            context=dict(envelope.context),
            inputs=list(envelope.inputs),
            broker=broker,
            exchange=exchange,
            reply_queue=reply_queue,
            headers=dict(headers or {}),
            correlation_id=str(envelope.context.get("correlation_id", "") or ""),
        )

    def to_task_envelope(self) -> TaskEnvelope:
        return TaskEnvelope(
            task_id=self.task_id,
            sender=self.sender,
            receiver=self.receiver,
            goal=self.goal,
            intent=self.intent,
            parent_task_id=self.parent_task_id,
            context={**dict(self.context), "correlation_id": self.correlation_id},
            inputs=list(self.inputs),
        )

    def to_prompt(self) -> str:
        return (
            f"[BROKER TASK]\n"
            f"broker={self.broker}\n"
            f"exchange={self.exchange}\n"
            f"routing_key={self.routing_key}\n"
            f"reply_queue={self.reply_queue}\n"
            f"protocol={self.protocol}\n"
            f"correlation_id={self.correlation_id}\n"
            f"sender={self.sender}\n"
            f"receiver={self.receiver}\n"
            f"intent={self.intent}\n"
            f"goal={self.goal}\n"
            f"context={json.dumps(self.context, ensure_ascii=False, sort_keys=True)}\n"
            f"inputs={json.dumps(self.inputs, ensure_ascii=False)}\n"
            f"headers={json.dumps(self.headers, ensure_ascii=False, sort_keys=True)}"
        )


@dataclass
class BrokerTaskResult:
    """Broker tabanlı delegasyonun taşınabilir sonucu."""

    task_id: str
    sender: str
    receiver: str
    status: str
    summary: str
    broker: str = "memory"
    exchange: str = "sidar.swarm"
    routing_key: str = ""
    protocol: str = BROKER_PROTOCOL_V1
    evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.protocol = normalize_broker_protocol(self.protocol)
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.headers.get("correlation_id", ""),
            self.task_id,
        )
        if not self.routing_key:
            self.routing_key = derive_broker_routing_key(
                receiver=self.receiver, intent=self.status, namespace=self.exchange
            )

    @classmethod
    def from_task_result(
        cls,
        result: TaskResult,
        *,
        sender: str,
        receiver: str,
        broker: str = "memory",
        exchange: str = "sidar.swarm",
        headers: dict[str, str] | None = None,
        correlation_id: str = "",
    ) -> BrokerTaskResult:
        return cls(
            task_id=result.task_id,
            sender=sender,
            receiver=receiver,
            status=result.status,
            summary=str(result.summary),
            broker=broker,
            exchange=exchange,
            evidence=list(result.evidence),
            next_actions=list(result.next_actions),
            headers=dict(headers or {}),
            correlation_id=correlation_id,
        )

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
            f"[BROKER RESULT]\n"
            f"broker={self.broker}\n"
            f"exchange={self.exchange}\n"
            f"routing_key={self.routing_key}\n"
            f"protocol={self.protocol}\n"
            f"correlation_id={self.correlation_id}\n"
            f"sender={self.sender}\n"
            f"receiver={self.receiver}\n"
            f"status={self.status}\n"
            f"summary={self.summary}\n"
            f"evidence={json.dumps(self.evidence, ensure_ascii=False)}\n"
            f"next_actions={json.dumps(self.next_actions, ensure_ascii=False)}\n"
            f"headers={json.dumps(self.headers, ensure_ascii=False, sort_keys=True)}"
        )


@dataclass
class ActionFeedback:
    """Dış sistemlerden gelen eylem geri besleme sinyalini standartlaştırır."""

    feedback_id: str
    source_system: str
    source_agent: str
    action_name: str
    status: str
    summary: str
    related_task_id: str = ""
    related_trigger_id: str = ""
    protocol: str = ACTION_FEEDBACK_PROTOCOL_V1
    details: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        self.correlation_id = derive_correlation_id(
            self.correlation_id,
            self.meta.get("correlation_id", ""),
            self.related_task_id,
            self.related_trigger_id,
            self.feedback_id,
        )

    def to_external_trigger(self) -> ExternalTrigger:
        payload = {
            "kind": "action_feedback",
            "feedback_id": self.feedback_id,
            "source_system": self.source_system,
            "source_agent": self.source_agent,
            "action_name": self.action_name,
            "status": self.status,
            "summary": self.summary,
            "related_task_id": self.related_task_id,
            "related_trigger_id": self.related_trigger_id,
            "details": dict(self.details or {}),
            "correlation_id": self.correlation_id,
        }
        meta = {
            **dict(self.meta or {}),
            "correlation_id": self.correlation_id,
            "feedback_status": self.status,
        }
        return ExternalTrigger(
            trigger_id=self.feedback_id,
            source=f"federation:{self.source_system}:action_feedback",
            event_name="action_feedback",
            payload=payload,
            protocol=self.protocol,
            meta=meta,
            correlation_id=self.correlation_id,
        )

    def to_prompt(self) -> str:
        return (
            f"[ACTION FEEDBACK]\n"
            f"source_system={self.source_system}\n"
            f"source_agent={self.source_agent}\n"
            f"action_name={self.action_name}\n"
            f"status={self.status}\n"
            f"correlation_id={self.correlation_id}\n"
            f"related_task_id={self.related_task_id}\n"
            f"related_trigger_id={self.related_trigger_id}\n"
            f"summary={self.summary}\n"
            f"details={json.dumps(self.details, ensure_ascii=False, sort_keys=True)}\n"
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
    return type(value).__name__ == "ExternalTrigger" and all(
        hasattr(value, attr) for attr in required
    )


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
    required = (
        "task_id",
        "source_system",
        "source_agent",
        "target_system",
        "target_agent",
        "status",
        "summary",
    )
    return type(value).__name__ == "FederationTaskResult" and all(
        hasattr(value, attr) for attr in required
    )


def is_action_feedback(value: object) -> bool:
    """ActionFeedback benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, ActionFeedback):
        return True
    required = ("feedback_id", "source_system", "source_agent", "action_name", "status", "summary")
    return type(value).__name__ == "ActionFeedback" and all(
        hasattr(value, attr) for attr in required
    )


def is_broker_task_envelope(value: object) -> bool:
    """BrokerTaskEnvelope benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, BrokerTaskEnvelope):
        return True
    required = ("task_id", "sender", "receiver", "goal", "broker", "exchange", "routing_key")
    return type(value).__name__ == "BrokerTaskEnvelope" and all(
        hasattr(value, attr) for attr in required
    )


def is_broker_task_result(value: object) -> bool:
    """BrokerTaskResult benzeri nesneleri duck-typing ile tanımlar."""
    if isinstance(value, BrokerTaskResult):
        return True
    required = ("task_id", "sender", "receiver", "status", "summary", "broker", "exchange")
    return type(value).__name__ == "BrokerTaskResult" and all(
        hasattr(value, attr) for attr in required
    )
