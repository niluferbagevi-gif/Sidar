"""
Tests for core/judge.py — LLM-as-a-Judge kalite değerlendirme modülü.
"""
import asyncio
import time
import pytest
from unittest.mock import patch

from core.judge import JudgeResult, LLMJudge, get_llm_judge


def _run(coro):
    """Async coroutine'i senkron olarak çalıştır."""
    return asyncio.run(coro)


# ─── JudgeResult ─────────────────────────────────────────────────────────────

class TestJudgeResult:
    def test_passed_high_relevance_low_risk(self):
        r = JudgeResult(
            relevance_score=0.85,
            hallucination_risk=0.1,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )
        assert r.passed is True

    def test_failed_low_relevance(self):
        r = JudgeResult(
            relevance_score=0.3,
            hallucination_risk=0.1,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )
        assert r.passed is False

    def test_failed_high_risk(self):
        r = JudgeResult(
            relevance_score=0.9,
            hallucination_risk=0.8,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )
        assert r.passed is False

    def test_borderline_passes(self):
        r = JudgeResult(
            relevance_score=0.5,
            hallucination_risk=0.5,
            evaluated_at=time.time(),
            model="m",
            provider="p",
        )
        assert r.passed is True


# ─── LLMJudge ────────────────────────────────────────────────────────────────

class TestLLMJudge:
    def _make_judge(self, enabled=True, sample_rate=1.0) -> LLMJudge:
        j = LLMJudge()
        j.enabled = enabled
        j.sample_rate = sample_rate
        j.provider = "ollama"
        return j

    def test_disabled_judge_should_not_evaluate(self):
        judge = self._make_judge(enabled=False)
        assert judge._should_evaluate() is False

    def test_zero_sample_rate_should_not_evaluate(self):
        judge = self._make_judge(enabled=True, sample_rate=0.0)
        assert judge._should_evaluate() is False

    def test_full_sample_rate_should_evaluate(self):
        judge = self._make_judge(enabled=True, sample_rate=1.0)
        assert judge._should_evaluate() is True

    def test_evaluate_rag_disabled_returns_none(self):
        async def _inner():
            judge = self._make_judge(enabled=False)
            result = await judge.evaluate_rag(
                query="Python nedir?",
                documents=["Python bir programlama dilidir."],
            )
            assert result is None
        _run(_inner())

    def test_evaluate_rag_empty_docs_returns_none(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)
            result = await judge.evaluate_rag(query="soru", documents=[])
            assert result is None
        _run(_inner())

    def test_evaluate_rag_with_mock_llm(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)
            call_count = [0]

            async def _fake_llm(system, user_msg):
                call_count[0] += 1
                return 0.85

            with patch.object(judge, "_call_llm", side_effect=_fake_llm):
                result = await judge.evaluate_rag(
                    query="FastAPI nedir?",
                    documents=["FastAPI Python ile yazılmış modern bir web framework'üdür."],
                    answer="FastAPI hızlı ve modern bir framework'tür.",
                )
            assert result is not None
            assert 0.0 <= result.relevance_score <= 1.0
            assert 0.0 <= result.hallucination_risk <= 1.0
        _run(_inner())

    def test_evaluate_rag_llm_returns_none_uses_neutral(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)

            async def _fail_llm(system, user_msg):
                return None

            with patch.object(judge, "_call_llm", side_effect=_fail_llm):
                result = await judge.evaluate_rag(
                    query="Soru",
                    documents=["Belge içeriği"],
                )
            assert result is not None
            assert result.relevance_score == 0.5  # nötr varsayılan
        _run(_inner())

    def test_schedule_background_no_loop(self):
        """Event loop yokken schedule_background_evaluation çökmemeli."""
        judge = self._make_judge(enabled=True, sample_rate=1.0)
        # RuntimeError beklenmemeli; sessizce görmezden gelinmeli
        judge.schedule_background_evaluation(
            query="test",
            documents=["belge"],
            answer="yanıt",
        )


# ─── Singleton ────────────────────────────────────────────────────────────────

def test_get_llm_judge_singleton():
    j1 = get_llm_judge()
    j2 = get_llm_judge()
    assert j1 is j2


# ─── LLMMetricEvent judge fields ─────────────────────────────────────────────

def test_llm_metric_event_judge_fields():
    from core.llm_metrics import LLMMetricEvent
    import time as _time
    event = LLMMetricEvent(
        timestamp=_time.time(),
        provider="ollama",
        model="gemma2:9b",
        latency_ms=120.5,
        prompt_tokens=50,
        completion_tokens=30,
        total_tokens=80,
        cost_usd=0.0,
        success=True,
        rate_limited=False,
        judge_score=0.9,
        hallucination_risk=0.05,
    )
    assert event.judge_score == 0.9
    assert event.hallucination_risk == 0.05


def test_llm_metric_event_judge_fields_optional():
    from core.llm_metrics import LLMMetricEvent
    import time as _time
    event = LLMMetricEvent(
        timestamp=_time.time(),
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=200.0,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        success=True,
        rate_limited=False,
    )
    assert event.judge_score is None
    assert event.hallucination_risk is None


def test_llm_metrics_collector_record_with_judge():
    from core.llm_metrics import LLMMetricsCollector
    collector = LLMMetricsCollector(max_events=10)
    collector.record(
        provider="ollama",
        model="gemma2:9b",
        latency_ms=100.0,
        prompt_tokens=20,
        completion_tokens=10,
        success=True,
        judge_score=0.75,
        hallucination_risk=0.2,
    )
    snapshot = collector.snapshot()
    assert snapshot["totals"]["calls"] == 1
    # judge_score recent event'de mevcut olmalı
    recent = snapshot["recent"]
    assert len(recent) == 1
    assert recent[0]["judge_score"] == 0.75
    assert recent[0]["hallucination_risk"] == 0.2
