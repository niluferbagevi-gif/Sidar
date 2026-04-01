import json
from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_disabled_sets_execution_status() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=False)

    remediation = {"remediation_loop": {"status": "planned", "steps": []}}
    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="coverage low",
        remediation=remediation,
    )

    assert execution["status"] == "disabled"
    assert remediation["self_heal_execution"]["status"] == "disabled"


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_waits_for_hitl_when_required() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "pending", "detail": ""}],
        }
    }

    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="risky patch",
        remediation=remediation,
    )

    assert execution["status"] == "awaiting_hitl"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_marks_applied_when_plan_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)

    async def _fake_build_self_heal_plan(**_kwargs):
        return {"operations": [{"path": "a.py"}], "validation_commands": ["pytest -q"]}

    async def _fake_execute_self_heal_plan(**_kwargs):
        return {
            "status": "applied",
            "summary": "ok",
            "operations_applied": ["a.py"],
            "validation_results": [{"command": "pytest -q", "ok": True}],
        }

    monkeypatch.setattr(agent, "_build_self_heal_plan", _fake_build_self_heal_plan)
    monkeypatch.setattr(agent, "_execute_self_heal_plan", _fake_execute_self_heal_plan)

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": False,
            "steps": [
                {"name": "patch", "status": "pending", "detail": ""},
                {"name": "validate", "status": "pending", "detail": ""},
                {"name": "handoff", "status": "pending", "detail": ""},
            ],
        }
    }

    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="lint errors",
        remediation=remediation,
    )

    assert execution["status"] == "applied"
    assert remediation["remediation_loop"]["status"] == "applied"
    step_statuses = {s["name"]: s["status"] for s in remediation["remediation_loop"]["steps"]}
    assert step_statuses == {"patch": "completed", "validate": "completed", "handoff": "completed"}
