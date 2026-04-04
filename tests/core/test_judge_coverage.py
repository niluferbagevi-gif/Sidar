from __future__ import annotations

import asyncio
import json
import types
import sys

import pytest
import core.judge as judge


def test_judge_result_and_response_evaluation_properties() -> None:
    result = judge.JudgeResult(
        relevance_score=0.9,
        hallucination_risk=0.1,
        evaluated_at=0.0,
        model="m",
        provider="p",
    )
    assert result.passed is True
    assert result.quality_score == 0.9
    assert result.quality_score_10 == 9.0

    weak = judge.ResponseEvaluation(score=7, reasoning="x", evaluated_at=0.0, model="m", provider="p")
    assert weak.weak is True


def test_llm_judge_response_model_and_evaluate_response(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_PROVIDER": "openai",
    }.get(key, default))
    j = judge.LLMJudge()

    assert j._response_eval_model() == "gpt-4o-mini"

    async def _ok_json(*_args, **_kwargs):
        return {"score": "9", "reasoning": "good"}

    monkeypatch.setattr(j, "_call_llm_json", _ok_json)
    evaluated = asyncio.run(j.evaluate_response("p", "r", {"x": 1}))
    assert evaluated is not None
    assert evaluated.score == 9
    assert evaluated.reasoning == "good"

    async def _bad_json(*_args, **_kwargs):
        return {"score": "score=11", "reasoning": ""}

    monkeypatch.setattr(j, "_call_llm_json", _bad_json)
    parsed = asyncio.run(j.evaluate_response("p", "r", ["ctx"]))
    assert parsed is not None
    assert parsed.score == 5


def test_llm_judge_rag_feedback_and_background(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_PROVIDER": "ollama",
        "JUDGE_SAMPLE_RATE": "1",
    }.get(key, default))
    j = judge.LLMJudge()

    vals = iter([0.8, 0.2])

    async def _call(*_args, **_kwargs):
        return next(vals)

    monkeypatch.setattr(j, "_call_llm", _call)
    monkeypatch.setattr(j, "_maybe_record_feedback", lambda **_kwargs: asyncio.sleep(0, result=False))
    res = asyncio.run(j.evaluate_rag("q", ["d1", "d2"], answer="a"))
    assert res is not None
    assert res.quality_score_10 == 8.0

    created = []

    class _Loop:
        def create_task(self, coro, name=None):
            created.append(name)
            coro.close()

    monkeypatch.setattr(j, "_should_evaluate", lambda: True)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _Loop())
    j.schedule_background_evaluation("q", ["d1"], "a")
    assert created == ["sidar_judge_eval"]


def test_judge_feedback_and_metric_recording(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_AUTO_FEEDBACK_ENABLED": "true",
        "JUDGE_AUTO_FEEDBACK_THRESHOLD": "9.5",
    }.get(key, default))
    j = judge.LLMJudge()

    class _Store:
        async def flag_weak_response(self, **kwargs):
            self.kwargs = kwargs
            return True

    store = _Store()
    active_learning_mod = types.SimpleNamespace(
        get_feedback_store=lambda _cfg: store,
        schedule_continuous_learning_cycle=lambda **_kwargs: None,
    )
    import sys

    monkeypatch.setitem(sys.modules, "core.active_learning", active_learning_mod)
    result = judge.JudgeResult(0.4, 0.8, 0.0, "m", "p")
    ok = asyncio.run(j._maybe_record_feedback(query="q", documents=["d"], answer="ans", result=result))
    assert ok is True

    payloads = []

    class _Collector:
        def __init__(self):
            self._usage_sink = payloads.append

    llm_metrics_mod = types.SimpleNamespace(get_llm_metrics_collector=lambda: _Collector())
    monkeypatch.setitem(sys.modules, "core.llm_metrics", llm_metrics_mod)

    judge._record_judge_metrics(result)
    assert payloads and payloads[0]["type"] == "judge"

    parsed = asyncio.run(j._call_llm_json("system", "msg", model="m"))
    assert parsed is None

    assert isinstance(json.dumps({"ok": True}), str)


def test_judge_helpers_and_model_selection_branches(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_SAMPLE_RATE": "1",
        "JUDGE_PROVIDER": "anthropic",
    }.get(key, default))
    j = judge.LLMJudge()

    assert j.should_evaluate() is True
    assert j._response_eval_model() == "claude-3-5-haiku-20241022"

    j.model = "override-model"
    assert j._response_eval_model() == "override-model"

    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_PROVIDER": "ollama",
        "JUDGE_RESPONSE_MODEL": "resp-model",
    }.get(key, default))
    j2 = judge.LLMJudge()
    assert j2._response_eval_model() == "resp-model"


def test_inc_prometheus_and_singleton(monkeypatch):
    judge._prometheus_gauges.clear()
    class _Gauge:
        def __init__(self, *_args, **_kwargs):
            self.value = None

        def set(self, value):
            self.value = value

    monkeypatch.setitem(sys.modules, "prometheus_client", types.SimpleNamespace(Gauge=_Gauge))
    judge._inc_prometheus("metric_ok", 1.0)
    assert "metric_ok" in judge._prometheus_gauges

    class _BrokenGauge:
        def set(self, _value):
            raise RuntimeError("boom")

    judge._prometheus_gauges["metric_fail"] = _BrokenGauge()
    judge._inc_prometheus("metric_fail", 1.0)  # exception path swallowed

    judge._JUDGE = None
    first = judge.get_llm_judge()
    second = judge.get_llm_judge()
    assert first is second


def test_call_llm_and_json_paths(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_PROVIDER": "ollama",
    }.get(key, default))
    j = judge.LLMJudge()

    class _Client:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return "score=0.73"

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_Client))
    val = asyncio.run(j._call_llm("s", "u"))
    assert val == 0.73

    class _ClientBad:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return 123

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientBad))
    assert asyncio.run(j._call_llm("s", "u")) is None

    class _ClientNoNumber:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return "no numeric value"

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientNoNumber))
    assert asyncio.run(j._call_llm("s", "u")) is None

    class _ClientRaises:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            raise RuntimeError("fail")

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientRaises))
    assert asyncio.run(j._call_llm("s", "u")) is None

    class _ClientCancel:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            raise asyncio.CancelledError()

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientCancel))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(j._call_llm("s", "u"))

    class _ClientJson:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return '{"score": 8, "reasoning":"ok"}'

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientJson))
    parsed = asyncio.run(j._call_llm_json("s", "u"))
    assert isinstance(parsed, dict)
    assert parsed["score"] == 8

    class _ClientJsonList:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config

        async def chat(self, **_kwargs):
            return '["not","dict"]'

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientJsonList))
    assert asyncio.run(j._call_llm_json("s", "u")) is None

    monkeypatch.setitem(sys.modules, "core.llm_client", types.SimpleNamespace(LLMClient=_ClientCancel))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(j._call_llm_json("s", "u"))


def test_evaluate_response_and_rag_guard_paths(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_PROVIDER": "ollama",
        "JUDGE_SAMPLE_RATE": "1",
    }.get(key, default))
    j = judge.LLMJudge()

    assert asyncio.run(j.evaluate_response("", "resp", None)) is None
    assert asyncio.run(j.evaluate_response("p", "", None)) is None

    async def _none_json(*_args, **_kwargs):
        return None

    monkeypatch.setattr(j, "_call_llm_json", _none_json)
    ev = asyncio.run(j.evaluate_response("p", "r", 123))
    assert ev is not None
    assert ev.error == "judge_json_parse_failed"

    monkeypatch.setattr(j, "_should_evaluate", lambda: False)
    assert asyncio.run(j.evaluate_rag("q", ["d"])) is None
    monkeypatch.setattr(j, "_should_evaluate", lambda: True)
    assert asyncio.run(j.evaluate_rag("", ["d"])) is None
    assert asyncio.run(j.evaluate_rag("q", [])) is None

    vals = iter([None, 0.4])

    async def _call(*_args, **_kwargs):
        return next(vals)

    monkeypatch.setattr(j, "_call_llm", _call)
    monkeypatch.setattr(j, "_maybe_record_feedback", lambda **_kwargs: asyncio.sleep(0, result=False))
    res = asyncio.run(j.evaluate_rag("q", ["d"], answer=None))
    assert res is not None
    assert res.relevance_score == 0.5
    assert res.hallucination_risk == 0.0


def test_feedback_background_and_metrics_exception_paths(monkeypatch):
    monkeypatch.setattr(judge.os, "getenv", lambda key, default="": {
        "JUDGE_ENABLED": "true",
        "JUDGE_AUTO_FEEDBACK_ENABLED": "true",
        "JUDGE_AUTO_FEEDBACK_THRESHOLD": "9.0",
        "JUDGE_SAMPLE_RATE": "1",
    }.get(key, default))
    j = judge.LLMJudge()
    result = judge.JudgeResult(0.3, 0.8, 0.0, "m", "p")

    j.auto_feedback_enabled = False
    assert asyncio.run(j._maybe_record_feedback(query="q", documents=["d"], answer="a", result=result)) is False
    j.auto_feedback_enabled = True

    high = judge.JudgeResult(0.95, 0.01, 0.0, "m", "p")
    assert asyncio.run(j._maybe_record_feedback(query="q", documents=["d"], answer="a", result=high)) is False
    assert asyncio.run(j._maybe_record_feedback(query="", documents=["d"], answer="", result=result)) is False

    class _Store:
        async def flag_weak_response(self, **_kwargs):
            return True

    active_learning_mod = types.SimpleNamespace(
        get_feedback_store=lambda _cfg: _Store(),
        schedule_continuous_learning_cycle=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setitem(sys.modules, "core.active_learning", active_learning_mod)
    assert asyncio.run(j._maybe_record_feedback(query="q", documents=["d"], answer="a", result=result)) is True

    active_learning_bad = types.SimpleNamespace(
        get_feedback_store=lambda _cfg: (_ for _ in ()).throw(RuntimeError("store fail")),
        schedule_continuous_learning_cycle=lambda **_kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "core.active_learning", active_learning_bad)
    assert asyncio.run(j._maybe_record_feedback(query="q", documents=["d"], answer="a", result=result)) is False

    monkeypatch.setattr(j, "_should_evaluate", lambda: False)
    j.schedule_background_evaluation("q", ["d"], "a")

    monkeypatch.setattr(j, "_should_evaluate", lambda: True)

    class _Loop:
        def create_task(self, coro, name=None):
            assert name == "sidar_judge_eval"
            asyncio.run(coro)

    async def _raise_eval(*_args, **_kwargs):
        raise RuntimeError("eval fail")

    monkeypatch.setattr(j, "evaluate_rag", _raise_eval)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _Loop())
    j.schedule_background_evaluation("q", ["d"], "a")

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    j.schedule_background_evaluation("q", ["d"], "a")

    class _Awaitable:
        def __await__(self):
            if False:
                yield None
            return None

        def close(self):
            self.closed = True

    class _Collector:
        def __init__(self):
            self._usage_sink = lambda _payload: _Awaitable()

    monkeypatch.setitem(sys.modules, "core.llm_metrics", types.SimpleNamespace(get_llm_metrics_collector=lambda: _Collector()))
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    judge._record_judge_metrics(result)

    monkeypatch.setitem(sys.modules, "core.llm_metrics", types.SimpleNamespace(get_llm_metrics_collector=lambda: (_ for _ in ()).throw(RuntimeError("x"))))
    judge._record_judge_metrics(result)
