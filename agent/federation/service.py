"""Federation task and external-trigger prompt builders."""

from __future__ import annotations

import json
import sys
from importlib import import_module
from typing import Any

from agent.core.contracts_fallback import (
    bind_fallback_contracts,
    default_derive_correlation_id,
)
from core.ci_remediation import build_ci_failure_prompt

agent_contracts = sys.modules.get("agent.core.contracts") or import_module("agent.core.contracts")

derive_correlation_id = getattr(
    agent_contracts, "derive_correlation_id", default_derive_correlation_id
)

(
    FallbackFederationTaskEnvelope,
    FallbackActionFeedback,
) = bind_fallback_contracts(derive_correlation_id)

FederationTaskEnvelope = getattr(
    agent_contracts, "FederationTaskEnvelope", FallbackFederationTaskEnvelope
)
ActionFeedback = getattr(agent_contracts, "ActionFeedback", FallbackActionFeedback)


def trigger_attr(trigger: Any, name: str, default: Any = "") -> Any:
    """Read an attribute/key from dict or contract-like external triggers."""

    if isinstance(trigger, dict):
        return trigger.get(name, default)
    return getattr(trigger, name, default)


def trigger_payload(trigger: Any) -> dict[str, Any]:
    """Return a defensive payload copy from an external trigger."""

    raw_payload = trigger_attr(trigger, "payload", {})
    return dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}


def trigger_meta(trigger: Any) -> dict[str, Any]:
    """Return a defensive metadata copy from an external trigger."""

    raw_meta = trigger_attr(trigger, "meta", {})
    return dict(raw_meta or {}) if isinstance(raw_meta, dict) else {}


def trigger_to_prompt(trigger: Any) -> str:
    """Render a generic external trigger prompt when no specialized builder applies."""

    if isinstance(trigger, dict):
        event_name = str(trigger.get("event_name", "event"))
        payload = dict(trigger.get("payload", {}) or {})
        source = str(trigger.get("source", "external"))
        return f"[EXTERNAL EVENT]\\nsource={source}\\nevent_name={event_name}\\npayload={json.dumps(payload, ensure_ascii=False)}"
    to_prompt = getattr(trigger, "to_prompt", None)
    if callable(to_prompt):
        return str(to_prompt())
    event_name = str(getattr(trigger, "event_name", "event"))
    source = str(getattr(trigger, "source", "external"))
    payload = trigger_payload(trigger)
    return f"[EXTERNAL EVENT]\\nsource={source}\\nevent_name={event_name}\\npayload={json.dumps(payload, ensure_ascii=False)}"


def build_federation_task_prompt(trigger: Any, payload_dict: dict[str, Any]) -> str:
    """Build the prompt for a federation task payload."""

    federation_payload = dict(payload_dict.get("federation_task") or payload_dict)
    if payload_dict.get("federation_prompt"):
        return str(payload_dict.get("federation_prompt"))
    return FederationTaskEnvelope(
        task_id=str(federation_payload.get("task_id") or trigger_attr(trigger, "trigger_id", "")),
        source_system=str(
            federation_payload.get("source_system") or trigger_attr(trigger, "source", "external")
        ),
        source_agent=str(federation_payload.get("source_agent") or "external"),
        target_system=str(federation_payload.get("target_system") or "sidar"),
        target_agent=str(federation_payload.get("target_agent") or "supervisor"),
        goal=str(federation_payload.get("goal") or ""),
        protocol=str(federation_payload.get("protocol") or "federation.v1"),
        intent=str(federation_payload.get("intent") or "mixed"),
        context=dict(federation_payload.get("context") or {}),
        inputs=list(federation_payload.get("inputs") or []),
        meta=dict(federation_payload.get("meta") or {}),
        correlation_id=str(
            federation_payload.get("correlation_id") or trigger_attr(trigger, "correlation_id", "")
        ),
    ).to_prompt()


def build_action_feedback_prompt(trigger: Any, payload_dict: dict[str, Any]) -> str:
    """Build the prompt for action feedback emitted by a federated system."""

    event_name = str(trigger_attr(trigger, "event_name", "event"))
    return ActionFeedback(
        feedback_id=str(payload_dict.get("feedback_id") or trigger_attr(trigger, "trigger_id", "")),
        source_system=str(
            payload_dict.get("source_system") or trigger_attr(trigger, "source", "external")
        ),
        source_agent=str(payload_dict.get("source_agent") or "external"),
        action_name=str(payload_dict.get("action_name") or event_name),
        status=str(payload_dict.get("status") or "received"),
        summary=str(payload_dict.get("summary") or "Dış sistem action feedback sinyali alındı."),
        related_task_id=str(payload_dict.get("related_task_id") or ""),
        related_trigger_id=str(payload_dict.get("related_trigger_id") or ""),
        details=dict(payload_dict.get("details") or {}),
        meta=dict(payload_dict.get("meta") or trigger_meta(trigger) or {}),
        correlation_id=str(
            payload_dict.get("correlation_id") or trigger_attr(trigger, "correlation_id", "")
        ),
    ).to_prompt()


def build_trigger_prompt(
    trigger: Any,
    payload_dict: dict[str, Any],
    ci_context: dict[str, Any] | None,
) -> str:
    """Build the specialized prompt for CI, federation, feedback, or generic triggers."""

    if ci_context:
        return build_ci_failure_prompt(ci_context)

    if payload_dict.get("kind") == "federation_task":
        return build_federation_task_prompt(trigger, payload_dict)

    event_name = str(trigger_attr(trigger, "event_name", "event"))
    if payload_dict.get("kind") == "action_feedback" or event_name == "action_feedback":
        return build_action_feedback_prompt(trigger, payload_dict)

    return trigger_to_prompt(trigger)
