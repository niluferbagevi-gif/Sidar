"""Unit tests for ``agent.core.contracts_fallback``."""

from agent.core.contracts_fallback import (
    FallbackActionFeedback,
    FallbackFederationTaskEnvelope,
    bind_fallback_contracts,
    default_derive_correlation_id,
)


def test_default_derive_correlation_id_returns_first_non_empty_value() -> None:
    """Default derive correlation id returns first non empty value."""
    assert default_derive_correlation_id("", "  ", None, "corr-1", "corr-2") == "corr-1"
    assert default_derive_correlation_id("", None, "   ") == ""


def test_fallback_federation_task_envelope_renders_prompt_with_correlation_id() -> None:
    """Fallback federation task envelope renders prompt with correlation id."""
    envelope = FallbackFederationTaskEnvelope(
        task_id="task-1",
        source_system="source-system",
        source_agent="source-agent",
        target_system="target-system",
        target_agent="target-agent",
        goal="Ship fallback contract extraction",
        context={"b": "2", "a": "1"},
        inputs=["input"],
    )

    prompt = envelope.to_prompt()

    assert envelope.correlation_id == "task-1"
    assert "[FEDERATION TASK]" in prompt
    assert "goal=Ship fallback contract extraction" in prompt
    assert 'context={"a": "1", "b": "2"}' in prompt


def test_fallback_action_feedback_renders_prompt_with_custom_correlation_id() -> None:
    """Fallback action feedback renders prompt with custom correlation id."""
    feedback = FallbackActionFeedback(
        derive_correlation_id=lambda *parts: "custom-correlation",
        feedback_id="feedback-1",
        source_system="source-system",
        source_agent="source-agent",
        action_name="deploy",
        status="accepted",
        summary="Action accepted",
        details={"safe": True},
    )

    prompt = feedback.to_prompt()

    assert feedback.correlation_id == "custom-correlation"
    assert "[ACTION FEEDBACK]" in prompt
    assert "action_name=deploy" in prompt
    assert 'details={"safe": true}' in prompt


def test_bind_fallback_contracts_centralizes_agent_specific_resolver() -> None:
    """Bind fallback contracts centralizes agent specific resolver."""
    envelope_cls, feedback_cls = bind_fallback_contracts(lambda *parts: "bound-corr")

    envelope = envelope_cls(task_id="task-2", goal="Use shared fallback source")
    feedback = feedback_cls(feedback_id="fb-2", summary="Accepted")

    assert envelope.correlation_id == "bound-corr"
    assert feedback.correlation_id == "bound-corr"
    assert issubclass(envelope_cls, FallbackFederationTaskEnvelope)
    assert issubclass(feedback_cls, FallbackActionFeedback)


def test_fallback_contracts_subclass_canonical_contracts() -> None:
    """Fallback contracts subclass canonical contracts."""
    from agent.core.contracts import ActionFeedback, FederationTaskEnvelope

    assert issubclass(FallbackFederationTaskEnvelope, FederationTaskEnvelope)
    assert issubclass(FallbackActionFeedback, ActionFeedback)
