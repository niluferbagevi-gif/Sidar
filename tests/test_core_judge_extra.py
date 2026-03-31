"""
core/judge.py için ek birim testleri — kapsam artırımı.

Hedef satırlar:
  72-74   _inc_prometheus — prometheus_client.Gauge oluşturma
  174-199 _call_llm       — LLMClient çağrısı, yanıt parse, istisna yolları
  203-224 _call_llm_json  — JSON mod LLMClient çağrısı, parse, istisnalar
  321->324 evaluate_rag   — hallucination hall_val is not None dalı
  355-404 _maybe_record_feedback — auto-feedback tam akışı
  416-434 schedule_background_evaluation — asyncio arka plan görevi
  446-463 _record_judge_metrics — usage_sink entegrasyonu
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── yardımcı: judge modülünü her test için temiz yükle ──────────────────────

def _get_judge(
    *,
    text_model: str = "test-model",
    coding_model: str = "",
    judge_enabled: str = "true",
    judge_sample_rate: str = "1.0",
    extra_env: dict | None = None,
):
    """Config stub ile core.judge modülünü temiz olarak döndürür."""
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        TEXT_MODEL = text_model
        CODING_MODEL = coding_model

    cfg_stub.Config = _Cfg

    env = {
        "JUDGE_ENABLED": judge_enabled,
        "JUDGE_SAMPLE_RATE": judge_sample_rate,
        "JUDGE_PROVIDER": "ollama",
        "JUDGE_MODEL": "",
        "JUDGE_RESPONSE_MODEL": "",
        "JUDGE_AUTO_FEEDBACK_ENABLED": "true",
        "JUDGE_AUTO_FEEDBACK_THRESHOLD": "8.0",
    }
    if extra_env:
        env.update(extra_env)

    with patch.dict(sys.modules, {"config": cfg_stub}), patch.dict(os.environ, env, clear=True):
        if "core.judge" in sys.modules:
            del sys.modules["core.judge"]
        import core.judge as judge
    judge._JUDGE = None
    judge._prometheus_gauges = {}
    return judge


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# _inc_prometheus — satır 72-74
# ══════════════════════════════════════════════════════════════════════════════

class TestIncPrometheus:
    """prometheus_client.Gauge oluşturma ve singleton önbellek davranışı."""

    def test_creates_gauge_via_prometheus_client(self):
        judge = _get_judge()
        gauge_mock = MagicMock()
        gauge_class_mock = MagicMock(return_value=gauge_mock)

        prom_stub = types.ModuleType("prometheus_client")
        prom_stub.Gauge = gauge_class_mock

        with patch.dict(sys.modules, {"prometheus_client": prom_stub}):
            judge._inc_prometheus("sidar_test_metric", 0.75)

        gauge_class_mock.assert_called_once_with("sidar_test_metric", "sidar test metric")
        gauge_mock.set.assert_called_once_with(0.75)

    def test_gauge_cached_second_call_does_not_recreate(self):
        judge = _get_judge()
        gauge_mock = MagicMock()
        gauge_class_mock = MagicMock(return_value=gauge_mock)

        prom_stub = types.ModuleType("prometheus_client")
        prom_stub.Gauge = gauge_class_mock

        with patch.dict(sys.modules, {"prometheus_client": prom_stub}):
            judge._inc_prometheus("sidar_cached_metric", 0.1)
            judge._inc_prometheus("sidar_cached_metric", 0.2)

        # Gauge yalnızca bir kez oluşturulmalı
        assert gauge_class_mock.call_count == 1
        assert gauge_mock.set.call_count == 2

    def test_prometheus_exception_is_silenced(self):
        judge = _get_judge()

        prom_stub = types.ModuleType("prometheus_client")
        prom_stub.Gauge = MagicMock(side_effect=RuntimeError("registration error"))

        with patch.dict(sys.modules, {"prometheus_client": prom_stub}):
            # İstisna dışarıya sızmamalı
            judge._inc_prometheus("bad_metric", 1.0)

    def test_missing_prometheus_client_is_silenced(self):
        judge = _get_judge()
        # prometheus_client hiç kurulu değil
        saved = sys.modules.pop("prometheus_client", None)
        try:
            judge._inc_prometheus("missing_prom_metric", 0.5)
        finally:
            if saved is not None:
                sys.modules["prometheus_client"] = saved

    def test_set_raises_is_silenced(self):
        judge = _get_judge()
        gauge_mock = MagicMock()
        gauge_mock.set.side_effect = Exception("set failed")
        gauge_class_mock = MagicMock(return_value=gauge_mock)

        prom_stub = types.ModuleType("prometheus_client")
        prom_stub.Gauge = gauge_class_mock

        with patch.dict(sys.modules, {"prometheus_client": prom_stub}):
            judge._inc_prometheus("sidar_set_fail_metric", 0.5)


# ══════════════════════════════════════════════════════════════════════════════
# _call_llm — satır 174-199
# ══════════════════════════════════════════════════════════════════════════════

class TestCallLlm:
    """LLMClient çağrısı ve yanıt parse davranışları."""

    def _make_judge(self, **kw):
        judge = _get_judge(**kw)
        j = judge.LLMJudge()
        return judge, j

    def _stub_llm_client(self, judge_mod, response_value):
        """core.llm_client modülünü stub'la, chat() verilen değeri döndürsün."""
        llm_stub = types.ModuleType("core.llm_client")

        class _FakeClient:
            def __init__(self, **_kw):
                pass

            async def chat(self, **_kw):
                return response_value

        llm_stub.LLMClient = _FakeClient
        sys.modules["core.llm_client"] = llm_stub
        return llm_stub

    # -- başarılı parse yolları --

    def test_returns_float_from_plain_number_response(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, "0.85")
        result = _run(j._call_llm("system", "user"))
        assert result == pytest.approx(0.85)

    def test_returns_float_from_embedded_number(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, "The relevance score is 0.73 overall.")
        result = _run(j._call_llm("system", "user"))
        assert result == pytest.approx(0.73)

    def test_value_clamped_to_1(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, "1.9999")
        result = _run(j._call_llm("system", "user"))
        assert result == pytest.approx(1.0)

    def test_value_clamped_to_0(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, "0.0")
        result = _run(j._call_llm("system", "user"))
        assert result == pytest.approx(0.0)

    def test_returns_none_when_no_number_in_response(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, "no number here at all")
        result = _run(j._call_llm("system", "user"))
        assert result is None

    def test_returns_none_when_response_not_string(self):
        judge, j = self._make_judge()
        self._stub_llm_client(judge, 12345)  # int, str değil
        result = _run(j._call_llm("system", "user"))
        assert result is None

    def test_returns_none_on_llm_exception(self):
        judge, j = self._make_judge()

        llm_stub = types.ModuleType("core.llm_client")

        class _ErrorClient:
            def __init__(self, **_kw):
                pass

            async def chat(self, **_kw):
                raise ValueError("connection refused")

        llm_stub.LLMClient = _ErrorClient
        sys.modules["core.llm_client"] = llm_stub

        result = _run(j._call_llm("system", "user"))
        assert result is None

    def test_cancelled_error_propagates(self):
        judge, j = self._make_judge()

        llm_stub = types.ModuleType("core.llm_client")

        class _CancelClient:
            def __init__(self, **_kw):
                pass

            async def chat(self, **_kw):
                raise asyncio.CancelledError()

        llm_stub.LLMClient = _CancelClient
        sys.modules["core.llm_client"] = llm_stub

        with pytest.raises(asyncio.CancelledError):
            _run(j._call_llm("system", "user"))

    def test_uses_config_text_model_when_judge_model_unset(self):
        """self.model None iken config.TEXT_MODEL kullanılmalı."""
        judge, j = self._make_judge(text_model="config-text-model")
        j.model = None  # açıkça sıfırla
        j.config = types.SimpleNamespace(TEXT_MODEL="config-text-model", CODING_MODEL="")

        used_models = []
        llm_stub = types.ModuleType("core.llm_client")

        class _CapturingClient:
            def __init__(self, **_kw):
                pass

            async def chat(self, *, model, **_kw):
                used_models.append(model)
                return "0.5"

        llm_stub.LLMClient = _CapturingClient
        sys.modules["core.llm_client"] = llm_stub

        result = _run(j._call_llm("system", "user"))
        assert result == pytest.approx(0.5)
        assert used_models[0] == "config-text-model"


# ══════════════════════════════════════════════════════════════════════════════
# _call_llm_json — satır 203-224
# ══════════════════════════════════════════════════════════════════════════════

class TestCallLlmJson:
    def _make_judge(self, **kw):
        judge = _get_judge(**kw)
        j = judge.LLMJudge()
        return judge, j

    def _stub_json_client(self, response_str: str | None, raise_exc=None):
        llm_stub = types.ModuleType("core.llm_client")

        class _JsonClient:
            def __init__(self, **_kw):
                pass

            async def chat(self, **_kw):
                if raise_exc is not None:
                    raise raise_exc
                return response_str

        llm_stub.LLMClient = _JsonClient
        sys.modules["core.llm_client"] = llm_stub

    def test_returns_dict_on_valid_json(self):
        judge, j = self._make_judge()
        self._stub_json_client('{"score": 8, "reasoning": "good"}')
        result = _run(j._call_llm_json("system", "user"))
        assert result == {"score": 8, "reasoning": "good"}

    def test_returns_none_when_response_not_string(self):
        judge, j = self._make_judge()
        self._stub_json_client(None)  # NoneType döner
        result = _run(j._call_llm_json("system", "user"))
        assert result is None

    def test_returns_none_on_invalid_json(self):
        judge, j = self._make_judge()
        self._stub_json_client("not valid json {{{")
        result = _run(j._call_llm_json("system", "user"))
        assert result is None

    def test_returns_none_when_parsed_not_dict(self):
        judge, j = self._make_judge()
        self._stub_json_client("[1, 2, 3]")  # liste, dict değil
        result = _run(j._call_llm_json("system", "user"))
        assert result is None

    def test_returns_none_on_exception(self):
        judge, j = self._make_judge()
        self._stub_json_client(None, raise_exc=RuntimeError("network err"))
        result = _run(j._call_llm_json("system", "user"))
        assert result is None

    def test_cancelled_error_propagates(self):
        judge, j = self._make_judge()
        self._stub_json_client(None, raise_exc=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            _run(j._call_llm_json("system", "user"))

    def test_uses_provided_model_override(self):
        judge, j = self._make_judge()
        used_models = []
        llm_stub = types.ModuleType("core.llm_client")

        class _Cap:
            def __init__(self, **_kw):
                pass

            async def chat(self, *, model, **_kw):
                used_models.append(model)
                return '{"score": 7, "reasoning": "ok"}'

        llm_stub.LLMClient = _Cap
        sys.modules["core.llm_client"] = llm_stub

        result = _run(j._call_llm_json("system", "user", model="custom-judge-model"))
        assert result is not None
        assert used_models[0] == "custom-judge-model"


# ══════════════════════════════════════════════════════════════════════════════
# evaluate_rag — hallucination dalı (satır 321->324)
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateRagHallucinationBranch:
    """hall_val is not None dalının çalıştığını doğrula."""

    def _make_enabled_judge(self):
        """JUDGE_ENABLED=true, JUDGE_SAMPLE_RATE=1.0 ile LLMJudge oluştur."""
        judge = _get_judge(judge_enabled="true", judge_sample_rate="1.0")
        with patch.dict(os.environ, {"JUDGE_ENABLED": "true", "JUDGE_SAMPLE_RATE": "1.0"}):
            j = judge.LLMJudge()
        return judge, j

    def test_hallucination_score_used_when_llm_returns_value(self):
        judge, j = self._make_enabled_judge()

        call_counter = {"n": 0}

        async def _fake_call_llm(system, user_message):
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return 0.9   # relevance
            return 0.3       # hallucination

        j._call_llm = _fake_call_llm
        j._maybe_record_feedback = AsyncMock(return_value=False)

        result = _run(j.evaluate_rag("query text", ["doc"], answer="some answer"))
        assert result is not None
        assert result.relevance_score == pytest.approx(0.9)
        assert result.hallucination_risk == pytest.approx(0.3)

    def test_hallucination_remains_zero_when_llm_returns_none(self):
        judge, j = self._make_enabled_judge()

        call_count = {"n": 0}

        async def _fake_call_llm(system, user_message):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return 0.8  # relevance
            return None     # hallucination LLM başarısız

        j._call_llm = _fake_call_llm
        j._maybe_record_feedback = AsyncMock(return_value=False)

        result = _run(j.evaluate_rag("query", ["doc"], answer="answer"))
        assert result is not None
        assert result.hallucination_risk == 0.0

    def test_no_hallucination_call_when_answer_is_none(self):
        judge, j = self._make_enabled_judge()

        call_count = {"n": 0}

        async def _fake_call_llm(system, user_message):
            call_count["n"] += 1
            return 0.7

        j._call_llm = _fake_call_llm
        j._maybe_record_feedback = AsyncMock(return_value=False)

        result = _run(j.evaluate_rag("query", ["doc"], answer=None))
        assert result is not None
        # Sadece relevance çağrısı yapılmalı
        assert call_count["n"] == 1
        assert result.hallucination_risk == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# _maybe_record_feedback — satır 355-404
# ══════════════════════════════════════════════════════════════════════════════

class TestMaybeRecordFeedback:
    """Auto-feedback kayıt akışının tüm dalları."""

    def _make_result(self, judge, relevance=0.3, hallucination=0.8):
        """Zayıf kaliteli (quality_score_10 < 8) JudgeResult üret."""
        return judge.JudgeResult(
            relevance_score=relevance,
            hallucination_risk=hallucination,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )

    def test_returns_false_when_auto_feedback_disabled(self):
        judge = _get_judge(extra_env={"JUDGE_AUTO_FEEDBACK_ENABLED": "false"})
        with patch.dict(os.environ, {"JUDGE_AUTO_FEEDBACK_ENABLED": "false"}):
            j = judge.LLMJudge()
        result = self._make_result(judge)

        ok = _run(j._maybe_record_feedback(
            query="test", documents=["doc"], answer="ans", result=result
        ))
        assert ok is False

    def test_returns_false_when_quality_above_threshold(self):
        judge = _get_judge(extra_env={"JUDGE_AUTO_FEEDBACK_THRESHOLD": "5.0"})
        with patch.dict(os.environ, {"JUDGE_AUTO_FEEDBACK_THRESHOLD": "5.0"}):
            j = judge.LLMJudge()
        # quality_score_10 yüksek olsun: relevance=1.0, hallucination=0.0 → 10.0
        result = judge.JudgeResult(
            relevance_score=1.0,
            hallucination_risk=0.0,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )

        ok = _run(j._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        ))
        assert ok is False

    def test_returns_false_when_query_empty(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        ok = _run(j._maybe_record_feedback(
            query="", documents=["doc"], answer="ans", result=result
        ))
        assert ok is False

    def test_returns_false_when_response_text_empty(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        ok = _run(j._maybe_record_feedback(
            query="query", documents=[], answer="", result=result
        ))
        assert ok is False

    def test_calls_flag_weak_response_and_returns_true_on_success(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        store_mock = MagicMock()
        store_mock.flag_weak_response = AsyncMock(return_value=True)

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = MagicMock()

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            ok = _run(j._maybe_record_feedback(
                query="user question",
                documents=["doc1", "doc2"],
                answer="bad answer",
                result=result,
            ))

        assert ok is True
        store_mock.flag_weak_response.assert_awaited_once()

    def test_schedules_continuous_learning_when_ok(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        store_mock = MagicMock()
        store_mock.flag_weak_response = AsyncMock(return_value=True)
        schedule_mock = MagicMock()

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = schedule_mock

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            _run(j._maybe_record_feedback(
                query="q", documents=["d"], answer="a", result=result
            ))

        schedule_mock.assert_called_once()

    def test_returns_false_when_flag_weak_response_returns_false(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        store_mock = MagicMock()
        store_mock.flag_weak_response = AsyncMock(return_value=False)

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = MagicMock()

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            ok = _run(j._maybe_record_feedback(
                query="q", documents=["d"], answer="a", result=result
            ))

        assert ok is False

    def test_schedule_exception_is_silenced(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        store_mock = MagicMock()
        store_mock.flag_weak_response = AsyncMock(return_value=True)

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = MagicMock(
            side_effect=RuntimeError("schedule failed")
        )

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            ok = _run(j._maybe_record_feedback(
                query="q", documents=["d"], answer="a", result=result
            ))
        assert ok is True  # schedule hatası dönüş değerini etkilememeli

    def test_active_learning_import_error_returns_false(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        # import sırasında zorunlu ImportError üret
        import builtins
        real_import = builtins.__import__

        def _failing_import(name, *args, **kwargs):
            if name == "core.active_learning":
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_failing_import):
            ok = _run(j._maybe_record_feedback(
                query="q", documents=["d"], answer="a", result=result
            ))

        assert ok is False

    def test_get_feedback_store_raises_returns_false(self):
        """get_feedback_store Exception fırlatırsa lines 402-404 tetiklenmeli."""
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(
            side_effect=RuntimeError("store unavailable")
        )
        al_stub.schedule_continuous_learning_cycle = MagicMock()

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            ok = _run(j._maybe_record_feedback(
                query="q", documents=["d"], answer="a", result=result
            ))
        assert ok is False

    def test_cancelled_error_propagates(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        store_mock = MagicMock()
        store_mock.flag_weak_response = AsyncMock(side_effect=asyncio.CancelledError())

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = MagicMock()

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            with pytest.raises(asyncio.CancelledError):
                _run(j._maybe_record_feedback(
                    query="q", documents=["d"], answer="a", result=result
                ))

    def test_uses_documents_when_answer_is_none(self):
        """answer=None iken response_text documents'tan oluşturulmalı."""
        judge = _get_judge()
        j = judge.LLMJudge()
        result = self._make_result(judge)

        captured = {}
        store_mock = MagicMock()

        async def _capture_flag(**kw):
            captured.update(kw)
            return True

        store_mock.flag_weak_response = _capture_flag

        al_stub = types.ModuleType("core.active_learning")
        al_stub.get_feedback_store = MagicMock(return_value=store_mock)
        al_stub.schedule_continuous_learning_cycle = MagicMock()

        with patch.dict(sys.modules, {"core.active_learning": al_stub}):
            _run(j._maybe_record_feedback(
                query="q",
                documents=["doc_a", "doc_b"],
                answer=None,
                result=result,
            ))

        # response alanı documents'tan türetilmeli
        assert "doc_a" in captured.get("response", "")


# ══════════════════════════════════════════════════════════════════════════════
# schedule_background_evaluation — satır 416-434
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleBackgroundEvaluation:
    """Asyncio arka plan görevinin doğru oluşturulduğunu doğrula."""

    def test_creates_task_when_should_evaluate(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        j._should_evaluate = MagicMock(return_value=True)

        async def _run_test():
            completed = asyncio.Event()

            async def _fake_eval_rag(query, docs, answer=None):
                completed.set()
                return None

            j.evaluate_rag = _fake_eval_rag

            j.schedule_background_evaluation("query", ["doc"], "answer")
            await asyncio.wait_for(completed.wait(), timeout=2.0)

        _run(_run_test())

    def test_does_not_create_task_when_should_not_evaluate(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        j._should_evaluate = MagicMock(return_value=False)

        async def _run_test():
            was_called = []

            async def _fake_eval_rag(query, docs, answer=None):
                was_called.append(True)
                return None

            j.evaluate_rag = _fake_eval_rag

            j.schedule_background_evaluation("query", ["doc"])
            # Kısa süre bekle — görev oluşturulmamalı
            await asyncio.sleep(0.05)
            assert not was_called

        _run(_run_test())

    def test_background_exception_is_silenced(self):
        judge = _get_judge()
        j = judge.LLMJudge()
        j._should_evaluate = MagicMock(return_value=True)

        async def _run_test():
            completed = asyncio.Event()
            scheduled = []

            async def _failing_eval_rag(query, docs, answer=None):
                completed.set()
                raise RuntimeError("eval error")

            j.evaluate_rag = _failing_eval_rag
            loop = asyncio.get_running_loop()

            with patch("asyncio.create_task", side_effect=lambda c: scheduled.append(loop.create_task(c)) or scheduled[-1]):
                j.schedule_background_evaluation("query", ["doc"])
            await asyncio.wait_for(completed.wait(), timeout=2.0)
            await asyncio.gather(*scheduled, return_exceptions=True)
            # İstisna dışarıya sızmamalı

        _run(_run_test())

    def test_no_running_loop_is_silenced(self):
        """Event loop yokken RuntimeError sessizce atlatılmalı."""
        judge = _get_judge()
        j = judge.LLMJudge()
        j._should_evaluate = MagicMock(return_value=True)

        # Event loop dışından çağır
        j.schedule_background_evaluation("query", ["doc"])
        # Hata fırlatılmamalı

    def test_background_cancelled_error_propagates_within_task(self):
        """CancelledError arka plan görevinde raise edilmeli (satır 423)."""
        judge = _get_judge()
        j = judge.LLMJudge()
        j._should_evaluate = MagicMock(return_value=True)

        cancel_reached = []

        async def _run_test():
            cancelled_ev = asyncio.Event()
            scheduled = []

            async def _raising_eval_rag(query, docs, answer=None):
                cancel_reached.append(True)
                cancelled_ev.set()
                raise asyncio.CancelledError()

            j.evaluate_rag = _raising_eval_rag
            loop = asyncio.get_running_loop()
            with patch("asyncio.create_task", side_effect=lambda c: scheduled.append(loop.create_task(c)) or scheduled[-1]):
                j.schedule_background_evaluation("query", ["doc"])
            # Görevin çalışması için bekle
            await asyncio.wait_for(cancelled_ev.wait(), timeout=2.0)
            await asyncio.gather(*scheduled, return_exceptions=True)

        _run(_run_test())
        assert cancel_reached, "evaluate_rag çağrılmadı"


# ══════════════════════════════════════════════════════════════════════════════
# _record_judge_metrics — satır 446-463
# ══════════════════════════════════════════════════════════════════════════════

class TestRecordJudgeMetrics:
    def _make_result(self, judge):
        return judge.JudgeResult(
            relevance_score=0.7,
            hallucination_risk=0.2,
            evaluated_at=time.time(),
            model="test-model",
            provider="ollama",
        )

    def test_calls_usage_sink_with_correct_payload(self):
        judge = _get_judge()
        result = self._make_result(judge)

        payloads = []
        collector_mock = MagicMock()
        collector_mock._usage_sink = lambda payload: payloads.append(payload)

        metrics_stub = types.ModuleType("core.llm_metrics")
        metrics_stub.get_llm_metrics_collector = MagicMock(return_value=collector_mock)

        with patch.dict(sys.modules, {"core.llm_metrics": metrics_stub}):
            judge._record_judge_metrics(result)

        assert len(payloads) == 1
        p = payloads[0]
        assert p["type"] == "judge"
        assert p["judge_score"] == pytest.approx(0.7)
        assert p["hallucination_risk"] == pytest.approx(0.2)
        assert p["model"] == "test-model"
        assert p["provider"] == "ollama"

    def test_usage_sink_none_does_not_crash(self):
        judge = _get_judge()
        result = self._make_result(judge)

        collector_mock = MagicMock()
        collector_mock._usage_sink = None

        metrics_stub = types.ModuleType("core.llm_metrics")
        metrics_stub.get_llm_metrics_collector = MagicMock(return_value=collector_mock)

        with patch.dict(sys.modules, {"core.llm_metrics": metrics_stub}):
            judge._record_judge_metrics(result)  # İstisna fırlatılmamalı

    def test_awaitable_sink_is_scheduled_as_task(self):
        """Sink bir coroutine döndürürse asyncio.get_running_loop + create_task çağrılmalı."""
        judge = _get_judge()
        result = self._make_result(judge)

        async def _run_test():
            task_created = []

            async def _async_sink(payload):
                task_created.append(payload)

            collector_mock = MagicMock()
            collector_mock._usage_sink = _async_sink

            metrics_stub = types.ModuleType("core.llm_metrics")
            metrics_stub.get_llm_metrics_collector = MagicMock(return_value=collector_mock)

            with patch.dict(sys.modules, {"core.llm_metrics": metrics_stub}):
                judge._record_judge_metrics(result)

            # Oluşturulan görevi tamamlamak için kısa bekle
            await asyncio.sleep(0.05)
            assert len(task_created) == 1

        _run(_run_test())

    def test_awaitable_sink_outside_loop_is_silenced(self):
        """Loop yokken RuntimeError sessizce atlatılmalı."""
        judge = _get_judge()
        result = self._make_result(judge)

        call_count = []

        async def _async_sink(payload):
            call_count.append(payload)

        collector_mock = MagicMock()
        collector_mock._usage_sink = _async_sink

        metrics_stub = types.ModuleType("core.llm_metrics")
        metrics_stub.get_llm_metrics_collector = MagicMock(return_value=collector_mock)

        with patch.dict(sys.modules, {"core.llm_metrics": metrics_stub}):
            # Loop dışında çağır — hata fırlatılmamalı
            judge._record_judge_metrics(result)

    def test_exception_in_metrics_is_silenced(self):
        judge = _get_judge()
        result = self._make_result(judge)

        metrics_stub = types.ModuleType("core.llm_metrics")
        metrics_stub.get_llm_metrics_collector = MagicMock(
            side_effect=RuntimeError("metrics unavailable")
        )

        with patch.dict(sys.modules, {"core.llm_metrics": metrics_stub}):
            judge._record_judge_metrics(result)  # İstisna fırlatılmamalı

    def test_import_error_for_metrics_is_silenced(self):
        judge = _get_judge()
        result = self._make_result(judge)

        saved = sys.modules.pop("core.llm_metrics", None)
        try:
            judge._record_judge_metrics(result)
        finally:
            if saved is not None:
                sys.modules["core.llm_metrics"] = saved
