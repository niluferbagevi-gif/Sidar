from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.auto_handle import AutoHandle
from agent.registry import AgentCatalog
from agent.sidar_agent import ActionFeedback, FederationTaskEnvelope
from core.ci_remediation import build_ci_remediation_payload
from core.judge import JudgeResult, LLMJudge


class _DummyMemory:
    def clear(self) -> None:
        return None


@pytest.mark.asyncio
async def test_agent_catalog_and_auto_handle_heal_flow(tmp_path) -> None:
    log_file = tmp_path / "fail.log"
    log_file.write_text("mypy: error: Incompatible types in assignment", encoding="utf-8")

    auto = AutoHandle(
        code=SimpleNamespace(),
        health=SimpleNamespace(),
        github=SimpleNamespace(),
        memory=_DummyMemory(),
        web=SimpleNamespace(),
        pkg=SimpleNamespace(),
        docs=SimpleNamespace(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=2),
    )

    handled, message = await auto.handle(f".heal {log_file}")
    assert handled is True
    assert "self-heal" in message

    roles = {spec.role_name for spec in AgentCatalog.list_all()}
    assert {"coder", "researcher", "reviewer", "qa", "coverage", "poyraz"}.issubset(roles)


@pytest.mark.asyncio
async def test_judge_ci_and_federation_smoke(monkeypatch) -> None:
    monkeypatch.setenv("JUDGE_ENABLED", "true")
    monkeypatch.setenv("JUDGE_SAMPLE_RATE", "1")

    judge = LLMJudge()
    assert judge.should_evaluate() is True

    result = JudgeResult(
        relevance_score=0.8,
        hallucination_risk=0.1,
        evaluated_at=asyncio.get_running_loop().time(),
        model="judge-model",
        provider="ollama",
    )
    assert result.passed is True
    assert result.quality_score_10 >= 8

    remediation = build_ci_remediation_payload(
        {"failure_summary": "pytest failed", "failing_tests": ["tests/integration/test_sample.py::test_x"]},
        diagnosis="assertion error",
    )
    assert remediation["root_cause_summary"]
    assert remediation["remediation_loop"]["validation_commands"]

    env = FederationTaskEnvelope(
        task_id="t-1",
        source_system="ci",
        source_agent="supervisor",
        target_system="sidar",
        target_agent="coder",
        goal="Fix failing tests",
        inputs=["pytest -q"],
    )
    feedback = ActionFeedback(
        feedback_id="f-1",
        source_system="sidar",
        source_agent="reviewer",
        action_name="code_review",
        status="ok",
        summary="done",
    )

    assert "[FEDERATION TASK]" in env.to_prompt()
    assert "[ACTION FEEDBACK]" in feedback.to_prompt()
