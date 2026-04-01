import json

from agent import sidar_agent


def test_default_derive_correlation_id_returns_first_non_empty():
    assert sidar_agent._default_derive_correlation_id("", None, "  ", "abc", "def") == "abc"


def test_fallback_federation_task_envelope_uses_meta_correlation_and_builds_prompt():
    envelope = sidar_agent._FallbackFederationTaskEnvelope(
        task_id="task-1",
        source_system="web",
        source_agent="agent-a",
        target_system="sidar",
        target_agent="reviewer",
        goal="run checks",
        context={"lang": "tr"},
        inputs=[{"path": "core/rag.py"}],
        meta={"correlation_id": "corr-123"},
    )

    prompt = envelope.to_prompt()
    assert envelope.correlation_id == "corr-123"
    assert "[FEDERATION TASK]" in prompt
    assert "target_agent=reviewer" in prompt
    assert f"context={json.dumps({'lang': 'tr'}, ensure_ascii=False, sort_keys=True)}" in prompt


def test_fallback_action_feedback_prefers_explicit_correlation_id():
    feedback = sidar_agent._FallbackActionFeedback(
        feedback_id="fb-1",
        action_name="run_tests",
        summary="ok",
        correlation_id="corr-explicit",
        meta={"correlation_id": "corr-meta"},
    )

    assert feedback.correlation_id == "corr-explicit"
    assert "[ACTION FEEDBACK]" in feedback.to_prompt()
    assert "action_name=run_tests" in feedback.to_prompt()
