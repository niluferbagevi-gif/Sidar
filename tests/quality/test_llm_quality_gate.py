"""Quality gate tests for deterministic judge score behavior."""

from __future__ import annotations

from core.judge import JudgeResult


def test_judge_result_passes_when_relevance_high_and_risk_low() -> None:
    result = JudgeResult(
        relevance_score=0.9,
        hallucination_risk=0.1,
        evaluated_at=1.0,
        model="judge-model",
        provider="ollama",
    )

    assert result.passed is True


def test_judge_result_fails_when_hallucination_risk_high() -> None:
    result = JudgeResult(
        relevance_score=0.95,
        hallucination_risk=0.8,
        evaluated_at=1.0,
        model="judge-model",
        provider="ollama",
    )

    assert result.passed is False


def test_quality_score_is_clamped_and_scaled() -> None:
    result = JudgeResult(
        relevance_score=1.5,
        hallucination_risk=-0.5,
        evaluated_at=1.0,
        model="judge-model",
        provider="ollama",
    )

    assert result.quality_score == 1.0
    assert result.quality_score_10 == 10.0
