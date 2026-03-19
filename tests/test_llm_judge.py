"""
Tests for core/judge.py — LLM-as-a-Judge kalite değerlendirme modülü.
"""
import asyncio
import time
import pytest
from unittest.mock import patch

from core.judge import JudgeResult, LLMJudge, ResponseEvaluation, _record_judge_metrics, get_llm_judge


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

    def test_quality_score_scales_to_ten(self):
        r = JudgeResult(
            relevance_score=0.7,
            hallucination_risk=0.1,
            evaluated_at=time.time(),
            model="m",
            provider="p",
        )
        assert r.quality_score == pytest.approx(0.8)
        assert r.quality_score_10 == pytest.approx(8.0)


def test_response_evaluation_weak_threshold():
    result = ResponseEvaluation(
        score=7,
        reasoning="Eksik doğrulama",
        evaluated_at=time.time(),
        model="judge-mini",
        provider="openai",
    )
    assert result.weak is True


# ─── LLMJudge ────────────────────────────────────────────────────────────────

class TestLLMJudge:
    def _make_judge(self, enabled=True, sample_rate=1.0) -> LLMJudge:
        j = LLMJudge()
        j.enabled = enabled
        j.sample_rate = sample_rate
        j.provider = "ollama"
        j.auto_feedback_enabled = True
        j.auto_feedback_threshold = 8.0
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

    def test_evaluate_rag_records_weak_feedback_when_quality_low(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)
            calls = []

            class _Store:
                _engine = object()

                async def initialize(self):
                    raise AssertionError("initialize should not run when engine exists")

                async def flag_weak_response(self, **kwargs):
                    calls.append(kwargs)
                    return True

            async def _fake_llm(_system, user_msg):
                return 0.6 if "Belge" in user_msg else 0.7

            with patch.object(judge, "_call_llm", side_effect=_fake_llm), patch(
                "core.active_learning.get_feedback_store",
                return_value=_Store(),
            ):
                result = await judge.evaluate_rag(
                    query="RAG cevabı neden zayıf?",
                    documents=["Belge içeriği"],
                    answer="Kısa ama eksik yanıt",
                )

            assert result is not None
            assert result.quality_score_10 < 8.0
            assert len(calls) == 1
            assert calls[0]["score"] <= 8
            assert any(tag.startswith("quality_score:") for tag in calls[0]["tags"])
            assert calls[0]["session_id"] == "judge:auto"

        _run(_inner())

    def test_evaluate_rag_skips_autofeedback_when_quality_high(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)

            class _Store:
                _engine = object()

                async def initialize(self):
                    return None

                async def flag_weak_response(self, **_kwargs):
                    raise AssertionError("high quality result should not be recorded")

            async def _fake_llm(system, _user_msg):
                return 0.95 if "RAG kalite" in system else 0.05

            with patch.object(judge, "_call_llm", side_effect=_fake_llm), patch(
                "core.active_learning.get_feedback_store",
                return_value=_Store(),
            ):
                result = await judge.evaluate_rag(
                    query="İyi yanıt",
                    documents=["Belgeler güçlü ve yeterli"],
                    answer="Bağlamla uyumlu yanıt",
                )

            assert result is not None
            assert result.quality_score_10 >= 8.0

        _run(_inner())

    def test_evaluate_response_parses_score_and_reasoning_json(self):
        async def _inner():
            judge = self._make_judge(enabled=True, sample_rate=1.0)

            async def _fake_json(_system, _payload, *, model=None):
                assert model
                return {"score": 7, "reasoning": "Yanıt eksik ama kısmen doğru."}

            with patch.object(judge, "_call_llm_json", side_effect=_fake_json):
                result = await judge.evaluate_response(
                    prompt="Önbellek durumu nedir?",
                    response="Cache iyi görünüyor.",
                    context={"agent": "reviewer"},
                )

            assert result is not None
            assert result.score == 7
            assert result.reasoning == "Yanıt eksik ama kısmen doğru."
            assert result.weak is True

        _run(_inner())

    def test_evaluate_response_returns_none_when_disabled(self):
        async def _inner():
            judge = self._make_judge(enabled=False, sample_rate=1.0)
            result = await judge.evaluate_response(
                prompt="durum",
                response="yanıt",
                context={},
            )
            assert result is None

        _run(_inner())


def test_call_llm_json_returns_none_on_malformed_json(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return "{broken-json"

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm_json("sys", "msg", model="judge-test"))
    assert result is None


def test_call_llm_returns_none_on_unparseable_numeric_response(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return "Bozuk yanit { parse edilemez"

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm("sys", "msg"))
    assert result is None


def test_call_llm_json_returns_none_for_non_dict_json(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return '[1, 2, 3]'

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm_json("sys", "msg", model="judge-test"))
    assert result is None


def test_evaluate_rag_returns_none_for_blank_query():
    async def _inner():
        judge = LLMJudge()
        judge.enabled = True
        judge.sample_rate = 1.0

        result = await judge.evaluate_rag(query="", documents=["doc"])
        assert result is None

    _run(_inner())


def test_maybe_record_feedback_returns_false_when_quality_meets_threshold():
    async def _inner():
        judge = LLMJudge()
        judge.auto_feedback_enabled = True
        judge.auto_feedback_threshold = 7.5
        result = JudgeResult(
            relevance_score=0.9,
            hallucination_risk=0.1,
            evaluated_at=time.time(),
            model="judge",
            provider="ollama",
        )

        assert await judge._maybe_record_feedback(
            query="soru",
            documents=["doc"],
            answer="yanıt",
            result=result,
        ) is False

    _run(_inner())


def test_evaluate_response_marks_parse_failure_when_judge_returns_invalid_json(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True
    judge.provider = "ollama"

    async def _bad_json(*_args, **_kwargs):
        return None

    with patch.object(judge, "_call_llm_json", side_effect=_bad_json):
        result = _run(
            judge.evaluate_response(
                prompt="Sistemde ne oldu?",
                response="Bozuk değerlendirme yanıtı geldi.",
                context=["satır-1", "satır-2"],
            )
        )

    assert result is not None
    assert result.score == 5
    assert result.reasoning == ""
    assert result.error == "judge_json_parse_failed"


def test_evaluate_response_extracts_numeric_score_from_textual_score(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True
    judge.provider = "ollama"

    async def _fake_json(*_args, **_kwargs):
        return {"score": "Toplam puan: 9/10", "reasoning": "Bağlam güçlü."}

    with patch.object(judge, "_call_llm_json", side_effect=_fake_json):
        result = _run(
            judge.evaluate_response(
                prompt="Özetle",
                response="Yanıt başarılı.",
                context="tek bağlam",
            )
        )

    assert result is not None
    assert result.score == 9
    assert result.reasoning == "Bağlam güçlü."


def test_schedule_background_evaluation_allows_task_cancellation(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True
    judge.sample_rate = 1.0

    state = {"started": asyncio.Event(), "cancelled": False}

    async def _slow_eval(_query, _documents, _answer=None):
        state["started"].set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(judge, "evaluate_rag", _slow_eval)

    async def _runner():
        created = {}
        loop = asyncio.get_running_loop()
        real_create_task = loop.create_task

        def _capture(coro, *args, **kwargs):
            task = real_create_task(coro, *args, **kwargs)
            if kwargs.get("name") == "sidar_judge_eval" and "task" not in created:
                created["task"] = task
            return task

        monkeypatch.setattr(loop, "create_task", _capture)
        judge.schedule_background_evaluation("q", ["d1"], "yanıt")
        await asyncio.wait_for(state["started"].wait(), timeout=1)
        created["task"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await created["task"]

    _run(_runner())
    assert state["cancelled"] is True


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


def test_record_judge_metrics_ignores_usage_sink_errors(monkeypatch):
    import sys
    import types

    class _Collector:
        def __init__(self):
            self._usage_sink = lambda _payload: (_ for _ in ()).throw(RuntimeError("sink failed"))

    fake_mod = types.ModuleType("core.llm_metrics")
    fake_mod.get_llm_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.llm_metrics", fake_mod)

    result = JudgeResult(
        relevance_score=0.8,
        hallucination_risk=0.1,
        evaluated_at=time.time(),
        model="judge-mini",
        provider="ollama",
    )

    _record_judge_metrics(result)



def test_record_judge_metrics_ignores_missing_running_loop_for_async_sink(monkeypatch):
    import sys
    import types

    state = {"created": False}

    class _Awaitable:
        def __await__(self):
            if False:
                yield None
            return None

    def _sink(_payload):
        state["created"] = True
        return _Awaitable()

    class _Collector:
        def __init__(self):
            self._usage_sink = _sink

    fake_mod = types.ModuleType("core.llm_metrics")
    fake_mod.get_llm_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.llm_metrics", fake_mod)

    result = JudgeResult(
        relevance_score=0.7,
        hallucination_risk=0.2,
        evaluated_at=time.time(),
        model="judge-mini",
        provider="ollama",
    )

    _record_judge_metrics(result)
    assert state["created"] is True


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


def test_response_evaluation_weak_is_false_for_strong_score():
    result = ResponseEvaluation(
        score=8,
        reasoning="Yeterince güçlü",
        evaluated_at=time.time(),
        model="judge-mini",
        provider="openai",
    )
    assert result.weak is False


def test_should_evaluate_public_wrapper_matches_internal_result():
    judge = LLMJudge()
    judge.enabled = True
    judge.sample_rate = 1.0
    assert judge.should_evaluate() is True


def test_response_eval_model_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("JUDGE_RESPONSE_MODEL", "judge-override")
    judge = LLMJudge()
    judge.model = "judge-base"
    assert judge._response_eval_model() == "judge-override"


def test_response_eval_model_uses_provider_defaults(monkeypatch):
    monkeypatch.delenv("JUDGE_RESPONSE_MODEL", raising=False)

    anthropic = LLMJudge()
    anthropic.provider = "anthropic"
    anthropic.model = None
    assert anthropic._response_eval_model() == "claude-3-5-haiku-20241022"

    openai_judge = LLMJudge()
    openai_judge.provider = "openai"
    openai_judge.model = None
    assert openai_judge._response_eval_model() == "gpt-4o-mini"


def test_response_eval_model_falls_back_to_config_models(monkeypatch):
    monkeypatch.delenv("JUDGE_RESPONSE_MODEL", raising=False)
    judge = LLMJudge()
    judge.provider = "ollama"
    judge.model = None
    judge.config.TEXT_MODEL = "text-fallback"
    judge.config.CODING_MODEL = "code-fallback"
    assert judge._response_eval_model() == "text-fallback"

    judge.config.TEXT_MODEL = ""
    assert judge._response_eval_model() == "code-fallback"

    judge.config.CODING_MODEL = ""
    assert judge._response_eval_model() == "judge-default"


def test_call_llm_clamps_numeric_response(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return "1.4"

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm("sys", "msg"))
    assert result == 1.0


def test_call_llm_returns_none_for_non_string_response(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return {"not": "a string"}

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm("sys", "msg"))
    assert result is None


def test_call_llm_json_returns_parsed_dict(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return '{"score": 8, "reasoning": "Tutarlı"}'

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm_json("sys", "msg", model="judge-test"))
    assert result == {"score": 8, "reasoning": "Tutarlı"}


def test_evaluate_response_clamps_score_and_stringifies_reasoning():
    judge = LLMJudge()
    judge.enabled = True
    judge.provider = "ollama"

    async def _fake_json(*_args, **_kwargs):
        return {"score": 42, "reasoning": 123}

    with patch.object(judge, "_call_llm_json", side_effect=_fake_json):
        result = _run(
            judge.evaluate_response(
                prompt="Kaliteyi puanla",
                response="Yanıt",
                context="bağlam",
            )
        )

    assert result is not None
    assert result.score == 10
    assert result.reasoning == "123"


def test_evaluate_rag_without_answer_keeps_hallucination_at_zero():
    async def _inner():
        judge = LLMJudge()
        judge.enabled = True
        judge.sample_rate = 1.0

        async def _fake_llm(_system, _user_msg):
            return 0.9

        with patch.object(judge, "_call_llm", side_effect=_fake_llm):
            result = await judge.evaluate_rag(
                query="Belge alakası nedir?",
                documents=["Yalnızca alaka puanı hesaplanacak."],
                answer=None,
            )

        assert result is not None
        assert result.relevance_score == 0.9
        assert result.hallucination_risk == 0.0

    _run(_inner())


def test_maybe_record_feedback_short_circuits_without_query_or_response():
    async def _inner():
        judge = LLMJudge()
        judge.enabled = True
        judge.auto_feedback_enabled = True
        result = JudgeResult(
            relevance_score=0.2,
            hallucination_risk=0.9,
            evaluated_at=time.time(),
            model="judge",
            provider="ollama",
        )

        assert await judge._maybe_record_feedback(query="", documents=["doc"], answer="yanıt", result=result) is False
        assert await judge._maybe_record_feedback(query="soru", documents=["   "], answer=None, result=result) is False

    _run(_inner())


def test_schedule_background_evaluation_skips_when_sampling_disables_it(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True
    judge.sample_rate = 0.0

    async def _boom(*_args, **_kwargs):
        raise AssertionError("evaluate_rag should not be scheduled")

    monkeypatch.setattr(judge, "evaluate_rag", _boom)
    judge.schedule_background_evaluation("q", ["d1"], "yanıt")


def test_inc_prometheus_creates_and_reuses_gauge(monkeypatch):
    import core.judge as judge_mod

    state = {"constructed": 0, "set_values": []}

    class _Gauge:
        def __init__(self, name, description):
            state["constructed"] += 1
            self.name = name
            self.description = description

        def set(self, value):
            state["set_values"].append(value)

    import sys
    import types

    fake_mod = types.ModuleType("prometheus_client")
    fake_mod.Gauge = _Gauge
    monkeypatch.setitem(sys.modules, "prometheus_client", fake_mod)
    monkeypatch.setattr(judge_mod, "_prometheus_gauges", {})

    judge_mod._inc_prometheus("sidar_metric", 0.5)
    judge_mod._inc_prometheus("sidar_metric", 0.7)

    assert state["constructed"] == 1
    assert state["set_values"] == [0.5, 0.7]


def test_response_eval_model_returns_configured_model_when_present(monkeypatch):
    monkeypatch.delenv("JUDGE_RESPONSE_MODEL", raising=False)
    judge = LLMJudge()
    judge.model = "judge-configured"
    assert judge._response_eval_model() == "judge-configured"


def test_call_llm_returns_none_when_client_raises(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            raise RuntimeError("llm down")

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm("sys", "msg"))
    assert result is None


def test_call_llm_reraises_cancelled_error(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            raise asyncio.CancelledError()

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    with pytest.raises(asyncio.CancelledError):
        _run(judge._call_llm("sys", "msg"))


def test_call_llm_json_returns_none_for_non_string_response(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return {"score": 10}

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    result = _run(judge._call_llm_json("sys", "msg", model="judge-test"))
    assert result is None


def test_call_llm_json_reraises_cancelled_error(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            raise asyncio.CancelledError()

    import sys
    import types

    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = _Client
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)

    with pytest.raises(asyncio.CancelledError):
        _run(judge._call_llm_json("sys", "msg", model="judge-test"))


def test_maybe_record_feedback_returns_false_when_disabled():
    async def _inner():
        judge = LLMJudge()
        judge.auto_feedback_enabled = False
        result = JudgeResult(
            relevance_score=0.2,
            hallucination_risk=0.9,
            evaluated_at=time.time(),
            model="judge",
            provider="ollama",
        )

        assert await judge._maybe_record_feedback(query="soru", documents=["doc"], answer="yanıt", result=result) is False

    _run(_inner())


def test_maybe_record_feedback_reraises_cancelled_error(monkeypatch):
    async def _inner():
        judge = LLMJudge()
        judge.auto_feedback_enabled = True
        judge.auto_feedback_threshold = 8.0
        result = JudgeResult(
            relevance_score=0.2,
            hallucination_risk=0.9,
            evaluated_at=time.time(),
            model="judge",
            provider="ollama",
        )

        class _Store:
            async def flag_weak_response(self, **_kwargs):
                raise asyncio.CancelledError()

        with patch("core.active_learning.get_feedback_store", return_value=_Store()):
            with pytest.raises(asyncio.CancelledError):
                await judge._maybe_record_feedback(
                    query="soru",
                    documents=["doc"],
                    answer="yanıt",
                    result=result,
                )

    _run(_inner())


def test_maybe_record_feedback_handles_store_errors(monkeypatch):
    async def _inner():
        judge = LLMJudge()
        judge.auto_feedback_enabled = True
        judge.auto_feedback_threshold = 8.0
        result = JudgeResult(
            relevance_score=0.2,
            hallucination_risk=0.9,
            evaluated_at=time.time(),
            model="judge",
            provider="ollama",
        )

        class _Store:
            async def flag_weak_response(self, **_kwargs):
                raise RuntimeError("store failure")

        with patch("core.active_learning.get_feedback_store", return_value=_Store()):
            ok = await judge._maybe_record_feedback(
                query="soru",
                documents=["doc"],
                answer="yanıt",
                result=result,
            )

        assert ok is False

    _run(_inner())


def test_schedule_background_evaluation_swallows_non_cancelled_errors(monkeypatch):
    judge = LLMJudge()
    judge.enabled = True
    judge.sample_rate = 1.0

    async def _runner():
        done = asyncio.Event()

        async def _boom(_query, _documents, _answer=None):
            raise RuntimeError("background failure")

        loop = asyncio.get_running_loop()
        real_create_task = loop.create_task

        def _capture(coro, *args, **kwargs):
            async def _wrapped():
                try:
                    await coro
                finally:
                    done.set()

            task = real_create_task(_wrapped(), *args, **kwargs)
            if kwargs.get("name") == "sidar_judge_eval":
                return task
            return task

        monkeypatch.setattr(judge, "evaluate_rag", _boom)
        monkeypatch.setattr(loop, "create_task", _capture)

        judge.schedule_background_evaluation("q", ["d1"], "yanıt")
        await asyncio.wait_for(done.wait(), timeout=1)

    _run(_runner())


def test_record_judge_metrics_schedules_async_sink_when_loop_exists(monkeypatch):
    async def _runner():
        import sys
        import types

        scheduled = {}

        class _Awaitable:
            def __await__(self):
                if False:
                    yield None
                return None

        def _sink(_payload):
            return _Awaitable()

        class _Collector:
            def __init__(self):
                self._usage_sink = _sink

        fake_mod = types.ModuleType("core.llm_metrics")
        fake_mod.get_llm_metrics_collector = lambda: _Collector()
        monkeypatch.setitem(sys.modules, "core.llm_metrics", fake_mod)

        loop = asyncio.get_running_loop()
        real_create_task = loop.create_task

        def _capture(awaitable, *args, **kwargs):
            if type(awaitable).__name__ == "_Awaitable":
                scheduled["awaitable"] = awaitable
                return real_create_task(asyncio.sleep(0), *args, **kwargs)
            return real_create_task(awaitable, *args, **kwargs)

        monkeypatch.setattr(loop, "create_task", _capture)

        result = JudgeResult(
            relevance_score=0.7,
            hallucination_risk=0.2,
            evaluated_at=time.time(),
            model="judge-mini",
            provider="ollama",
        )

        _record_judge_metrics(result)
        await asyncio.sleep(0)

        assert scheduled["awaitable"] is not None

    _run(_runner())
