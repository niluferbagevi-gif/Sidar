"""Compatibility aliases for federation/action contracts.

Historically this module hand-maintained fallback copies of
``FederationTaskEnvelope`` and ``ActionFeedback`` to dodge import-order issues in
``agent.federation.service``.  The canonical contracts no longer import the
federation service, so the compatibility layer can subclass the canonical
implementations instead of duplicating their fields and prompt rendering.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.core.contracts import (
    ActionFeedback,
    FederationTaskEnvelope,
)
from agent.core.contracts import (
    derive_correlation_id as default_derive_correlation_id,
)

DeriveCorrelationId = Callable[..., str]


class FallbackFederationTaskEnvelope(FederationTaskEnvelope):
    """Backward-compatible alias around the canonical federation envelope."""

    def __init__(
        self,
        *,
        derive_correlation_id: DeriveCorrelationId = default_derive_correlation_id,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            task_id=str(kwargs.get("task_id", "")),
            source_system=str(kwargs.get("source_system", "")),
            source_agent=str(kwargs.get("source_agent", "")),
            target_system=str(kwargs.get("target_system", "")),
            target_agent=str(kwargs.get("target_agent", "")),
            goal=str(kwargs.get("goal", "")),
            intent=str(kwargs.get("intent", "mixed")),
            parent_task_id=kwargs.get("parent_task_id"),
            context=dict(kwargs.get("context", {}) or {}),
            inputs=list(kwargs.get("inputs", []) or []),
            protocol=str(kwargs.get("protocol", "federation.v1")),
            meta=dict(kwargs.get("meta", {}) or {}),
            correlation_id=str(kwargs.get("correlation_id", "")),
        )
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.parent_task_id,
            self.task_id,
        )


class FallbackActionFeedback(ActionFeedback):
    """Backward-compatible alias around the canonical action feedback contract."""

    def __init__(
        self,
        *,
        derive_correlation_id: DeriveCorrelationId = default_derive_correlation_id,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            feedback_id=str(kwargs.get("feedback_id", "")),
            source_system=str(kwargs.get("source_system", "")),
            source_agent=str(kwargs.get("source_agent", "")),
            action_name=str(kwargs.get("action_name", "")),
            status=str(kwargs.get("status", "received")),
            summary=str(kwargs.get("summary", "")),
            related_task_id=str(kwargs.get("related_task_id", "")),
            related_trigger_id=str(kwargs.get("related_trigger_id", "")),
            protocol=str(kwargs.get("protocol", "action_feedback.v1")),
            details=dict(kwargs.get("details", {}) or {}),
            meta=dict(kwargs.get("meta", {}) or {}),
            correlation_id=str(kwargs.get("correlation_id", "")),
        )
        self.correlation_id = derive_correlation_id(
            kwargs.get("correlation_id", ""),
            self.meta.get("correlation_id", ""),
            self.related_task_id,
            self.related_trigger_id,
            self.feedback_id,
        )


def bind_fallback_contracts(
    derive_correlation_id: DeriveCorrelationId,
) -> tuple[type[FallbackFederationTaskEnvelope], type[FallbackActionFeedback]]:
    """Return compatibility contract types bound to the active correlation resolver."""

    class BoundFallbackFederationTaskEnvelope(FallbackFederationTaskEnvelope):
        """FederationTaskEnvelope compatibility type using the provided resolver."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(derive_correlation_id=derive_correlation_id, **kwargs)

    class BoundFallbackActionFeedback(FallbackActionFeedback):
        """ActionFeedback compatibility type using the provided resolver."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(derive_correlation_id=derive_correlation_id, **kwargs)

    BoundFallbackFederationTaskEnvelope.__name__ = "FallbackFederationTaskEnvelope"
    BoundFallbackActionFeedback.__name__ = "FallbackActionFeedback"
    return BoundFallbackFederationTaskEnvelope, BoundFallbackActionFeedback
