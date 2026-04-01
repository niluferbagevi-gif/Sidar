from __future__ import annotations

import os

import pytest

from core.judge import ResponseEvaluation


@pytest.mark.quality_gate
@pytest.mark.parametrize(
    ("score", "reason"),
    [
        (9, "Doğru ve bağlama sadık yanıt"),
        (8, "Küçük eksiklerle kabul edilebilir yanıt"),
    ],
)
def test_response_quality_gate(score: int, reason: str) -> None:
    """LLM değerlendirme skorlarının CI kalite kapısı eşiğinin altına düşmemesini doğrular."""
    threshold = int(os.getenv("LLM_QUALITY_GATE_MIN_SCORE", "8"))
    evaluation = ResponseEvaluation(
        score=score,
        reasoning=reason,
        evaluated_at=0.0,
        model="judge-ci",
        provider="offline",
    )

    assert evaluation.score >= threshold
