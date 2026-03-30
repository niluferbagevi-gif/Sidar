"""
core/judge.py için birim testleri.
JudgeResult, ResponseEvaluation dataclass'larını ve
LLMJudge'ın devre dışı / örnekleme / model seçim davranışlarını kapsar.
LLMClient çağrıları gerektiren async entegrasyon testleri stub'lanır.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


def _get_judge():
    # Config stub — LLMJudge.__init__ içinde Config() çağrılıyor
    cfg_stub = types.ModuleType("config")
    class _Cfg:
        TEXT_MODEL = "test-model"
        CODING_MODEL = ""
    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "core.judge" in sys.modules:
        del sys.modules["core.judge"]
    import core.judge as judge
    judge._JUDGE = None
    return judge


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════
# JudgeResult dataclass
# ══════════════════════════════════════════════════════════════

class TestJudgeResult:
    def _make(self, relevance=0.8, hallucination=0.2, **kwargs):
        judge = _get_judge()
        import time
        return judge.JudgeResult(
            relevance_score=relevance,
            hallucination_risk=hallucination,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
            **kwargs,
        )

    def test_passed_when_both_thresholds_met(self):
        result = self._make(relevance=0.8, hallucination=0.2)
        assert result.passed is True

    def test_not_passed_when_relevance_too_low(self):
        result = self._make(relevance=0.4, hallucination=0.2)
        assert result.passed is False

    def test_not_passed_when_hallucination_too_high(self):
        result = self._make(relevance=0.8, hallucination=0.6)
        assert result.passed is False

    def test_quality_score_formula(self):
        result = self._make(relevance=1.0, hallucination=0.0)
        # (1.0 + (1.0 - 0.0)) / 2.0 = 1.0
        assert result.quality_score == 1.0

    def test_quality_score_neutral(self):
        result = self._make(relevance=0.5, hallucination=0.5)
        # (0.5 + 0.5) / 2.0 = 0.5
        assert result.quality_score == 0.5

    def test_quality_score_in_range(self):
        result = self._make(relevance=0.7, hallucination=0.3)
        assert 0.0 <= result.quality_score <= 1.0

    def test_quality_score_10_scales(self):
        result = self._make(relevance=1.0, hallucination=0.0)
        assert result.quality_score_10 == 10.0

    def test_quality_score_10_rounds(self):
        result = self._make(relevance=0.7, hallucination=0.3)
        # (0.7 + 0.7) / 2.0 = 0.7 → * 10 = 7.0
        assert result.quality_score_10 == 7.0

    def test_error_field_default_empty(self):
        result = self._make()
        assert result.error == ""


# ══════════════════════════════════════════════════════════════
# ResponseEvaluation dataclass
# ══════════════════════════════════════════════════════════════

class TestResponseEvaluation:
    def _make(self, score=9, **kwargs):
        judge = _get_judge()
        import time
        return judge.ResponseEvaluation(
            score=score,
            reasoning="test reasoning",
            evaluated_at=time.time(),
            model="test-model",
            provider="openai",
            **kwargs,
        )

    def test_weak_when_score_below_8(self):
        result = self._make(score=7)
        assert result.weak is True

    def test_not_weak_when_score_8(self):
        result = self._make(score=8)
        assert result.weak is False

    def test_not_weak_when_score_10(self):
        result = self._make(score=10)
        assert result.weak is False

    def test_error_default_empty(self):
        result = self._make()
        assert result.error == ""


# ══════════════════════════════════════════════════════════════
# LLMJudge — init & configuration
# ══════════════════════════════════════════════════════════════

class TestLLMJudgeInit:
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "false"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.enabled is False

    def test_enabled_when_set(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.enabled is True

    def test_sample_rate_clamped_to_0_1(self):
        with patch.dict(os.environ, {"JUDGE_SAMPLE_RATE": "5.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.sample_rate == 1.0

    def test_sample_rate_negative_clamped(self):
        with patch.dict(os.environ, {"JUDGE_SAMPLE_RATE": "-1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.sample_rate == 0.0

    def test_provider_default_ollama(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JUDGE_PROVIDER", None)
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.provider == "ollama"

    def test_auto_feedback_enabled_default(self):
        with patch.dict(os.environ, {"JUDGE_AUTO_FEEDBACK_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.auto_feedback_enabled is True


# ══════════════════════════════════════════════════════════════
# LLMJudge._should_evaluate / should_evaluate
# ══════════════════════════════════════════════════════════════

class TestShouldEvaluate:
    def test_always_false_when_disabled(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "false", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.should_evaluate() is False

    def test_always_false_when_rate_zero(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "0.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.should_evaluate() is False

    def test_always_true_when_rate_one_and_enabled(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j.should_evaluate() is True


# ══════════════════════════════════════════════════════════════
# LLMJudge._response_eval_model
# ══════════════════════════════════════════════════════════════

class TestResponseEvalModel:
    def test_override_env_used_first(self):
        with patch.dict(os.environ, {
            "JUDGE_ENABLED": "false",
            "JUDGE_RESPONSE_MODEL": "special-model",
        }):
            judge = _get_judge()
            j = judge.LLMJudge()
            assert j._response_eval_model() == "special-model"

    def test_anthropic_provider_returns_haiku(self):
        with patch.dict(os.environ, {
            "JUDGE_ENABLED": "false",
            "JUDGE_PROVIDER": "anthropic",
            "JUDGE_RESPONSE_MODEL": "",
            "JUDGE_MODEL": "",
        }):
            judge = _get_judge()
            j = judge.LLMJudge()
        model = j._response_eval_model()
        assert "haiku" in model.lower()

    def test_openai_provider_returns_gpt4o_mini(self):
        with patch.dict(os.environ, {
            "JUDGE_ENABLED": "false",
            "JUDGE_PROVIDER": "openai",
            "JUDGE_RESPONSE_MODEL": "",
            "JUDGE_MODEL": "",
        }):
            judge = _get_judge()
            j = judge.LLMJudge()
        model = j._response_eval_model()
        assert "gpt-4o-mini" in model

    def test_explicit_judge_model_used(self):
        with patch.dict(os.environ, {
            "JUDGE_ENABLED": "false",
            "JUDGE_PROVIDER": "ollama",
            "JUDGE_RESPONSE_MODEL": "",
            "JUDGE_MODEL": "gemma2:9b",
        }):
            judge = _get_judge()
            j = judge.LLMJudge()
        assert j._response_eval_model() == "gemma2:9b"


# ══════════════════════════════════════════════════════════════
# LLMJudge.evaluate_rag — disabled / no-sample paths
# ══════════════════════════════════════════════════════════════

class TestEvaluateRagDisabled:
    def test_returns_none_when_disabled(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "false", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        result = _run(j.evaluate_rag("query", ["doc"], "answer"))
        assert result is None

    def test_returns_none_when_sample_rate_zero(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "0.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        result = _run(j.evaluate_rag("query", ["doc"], "answer"))
        assert result is None

    def test_returns_none_when_empty_query(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        # Patch _call_llm to avoid actual LLM calls
        j._call_llm = AsyncMock(return_value=0.7)
        j._maybe_record_feedback = AsyncMock(return_value=False)
        result = _run(j.evaluate_rag("", ["doc"]))
        assert result is None

    def test_returns_none_when_empty_documents(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm = AsyncMock(return_value=0.7)
        j._maybe_record_feedback = AsyncMock(return_value=False)
        result = _run(j.evaluate_rag("query", []))
        assert result is None


class TestEvaluateRagSuccess:
    def test_returns_judge_result_when_llm_succeeds(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()

        j._call_llm = AsyncMock(return_value=0.85)
        j._maybe_record_feedback = AsyncMock(return_value=False)
        result = _run(j.evaluate_rag("query", ["document text"], "answer"))
        assert result is not None
        assert isinstance(result, judge.JudgeResult)
        assert result.relevance_score == 0.85

    def test_fallback_relevance_when_llm_returns_none(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            judge = _get_judge()
            j = judge.LLMJudge()

        j._call_llm = AsyncMock(return_value=None)
        j._maybe_record_feedback = AsyncMock(return_value=False)
        result = _run(j.evaluate_rag("query", ["doc"]))
        assert result is not None
        assert result.relevance_score == 0.5  # neutral fallback


# ══════════════════════════════════════════════════════════════
# LLMJudge.evaluate_response — disabled path
# ══════════════════════════════════════════════════════════════

class TestEvaluateResponseDisabled:
    def test_returns_none_when_disabled(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "false"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        result = _run(j.evaluate_response("prompt", "response", {}))
        assert result is None

    def test_returns_none_when_empty_prompt(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm_json = AsyncMock(return_value={"score": 8, "reasoning": "ok"})
        result = _run(j.evaluate_response("", "response", {}))
        assert result is None

    def test_returns_none_when_empty_response(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm_json = AsyncMock(return_value={"score": 8, "reasoning": "ok"})
        result = _run(j.evaluate_response("prompt", "", {}))
        assert result is None


class TestEvaluateResponseParsing:
    def test_json_parse_failure_sets_error_and_uses_default_score(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm_json = AsyncMock(return_value=None)
        result = _run(j.evaluate_response("prompt", "response", {"ctx": "v"}))
        assert result is not None
        assert result.error == "judge_json_parse_failed"
        assert result.score == 5

    def test_non_numeric_score_with_embedded_number_uses_regex_fallback(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm_json = AsyncMock(return_value={"score": "bence 9/10", "reasoning": "iyi"})
        result = _run(j.evaluate_response("prompt", "response", ["ctx"]))
        assert result is not None
        assert result.score == 9
        assert result.reasoning == "iyi"

    def test_score_is_clamped_to_upper_bound(self):
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true"}):
            judge = _get_judge()
            j = judge.LLMJudge()
        j._call_llm_json = AsyncMock(return_value={"score": 999, "reasoning": ""})
        result = _run(j.evaluate_response("prompt", "response", "ctx"))
        assert result is not None
        assert result.score == 10


# ══════════════════════════════════════════════════════════════
# get_llm_judge singleton
# ══════════════════════════════════════════════════════════════

class TestGetLlmJudge:
    def test_returns_instance(self):
        judge = _get_judge()
        j = judge.get_llm_judge()
        assert isinstance(j, judge.LLMJudge)

    def test_same_instance_on_repeated_calls(self):
        judge = _get_judge()
        j1 = judge.get_llm_judge()
        j2 = judge.get_llm_judge()
        assert j1 is j2
