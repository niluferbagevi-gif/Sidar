import os


def test_llm_quality_gate_threshold() -> None:
    threshold = int(os.getenv("LLM_QUALITY_GATE_MIN_SCORE", "8"))
    assert threshold >= 1
