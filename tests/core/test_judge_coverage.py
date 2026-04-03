from __future__ import annotations

import asyncio
import json
import types

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
