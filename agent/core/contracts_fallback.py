"""Fallback federation/action contracts used when canonical contracts are absent."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

DeriveCorrelationId = Callable[..., str]


def default_derive_correlation_id(*values: object) -> str:
    """Return the first non-empty value as a string correlation id."""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


class FallbackFederationTaskEnvelope:
    """Minimal FederationTaskEnvelope-compatible fallback contract."""

    def __init__(
        self,
        *,
        derive_correlation_id: DeriveCorrelationId = default_derive_correlation_id,
        **kwargs: Any,
    ) -> None:
        self.task_id = str(kwargs.get("task_id", ""))
        self.source_system = str(kwargs.get("source_system", ""))
        self.source_agent = str(kwargs.get("source_agent", ""))
        self.target_system = str(kwargs.get("target_system", ""))
        self.target_agent = str(kwargs.get("target_agent", ""))
        self.goal = str(kwargs.get("goal", ""))
        self.protocol = str(kwargs.get("protocol", "federation.v1"))
        self.intent = str(kwargs.get("intent", "mixed"))
        self.context = dict(kwargs.get("context", {}) or {})
        self.inputs = list(kwargs.get("inputs", []) or [])
        self.meta = dict(kwargs.get("meta", {}) or {})
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.task_id,
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


class FallbackActionFeedback:
    """Minimal ActionFeedback-compatible fallback contract."""

    def __init__(
        self,
        *,
        derive_correlation_id: DeriveCorrelationId = default_derive_correlation_id,
        **kwargs: Any,
    ) -> None:
        self.feedback_id = str(kwargs.get("feedback_id", ""))
        self.source_system = str(kwargs.get("source_system", ""))
        self.source_agent = str(kwargs.get("source_agent", ""))
        self.action_name = str(kwargs.get("action_name", ""))
        self.status = str(kwargs.get("status", "received"))
        self.summary = str(kwargs.get("summary", ""))
        self.related_task_id = str(kwargs.get("related_task_id", ""))
        self.related_trigger_id = str(kwargs.get("related_trigger_id", ""))
        self.details = dict(kwargs.get("details", {}) or {})
        self.meta = dict(kwargs.get("meta", {}) or {})
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.related_task_id,
            self.related_trigger_id,
            self.feedback_id,
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
