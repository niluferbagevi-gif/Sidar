import asyncio
import json
import sys
import types

import pytest

import core.judge as judge


class DummyConfig:
    TEXT_MODEL = "text-model"
    CODING_MODEL = "coding-model"


def _install_config_module(monkeypatch):
    fake = types.ModuleType("config")
    fake.Config = DummyConfig
    monkeypatch.setitem(sys.modules, "config", fake)


class FakeLLMClient:
    response = "0.75"

    def __init__(self, provider, config):
        self.provider = provider
        self.config = config

    async def chat(self, **kwargs):
        self.last_kwargs = kwargs
        value = self.response
        if isinstance(value, Exception):
            raise value
        return value


def _install_llm_client_module(monkeypatch, client_cls=FakeLLMClient):
    fake_mod = types.ModuleType("core.llm_client")
    fake_mod.LLMClient = client_cls
    monkeypatch.setitem(sys.modules, "core.llm_client", fake_mod)


@pytest.fixture
def judge_instance(monkeypatch):
    monkeypatch.setenv("JUDGE_ENABLED", "true")
    monkeypatch.setenv("JUDGE_SAMPLE_RATE", "1.0")
    _install_config_module(monkeypatch)
    return judge.LLMJudge()


def test_judge_result_properties():
    result = judge.JudgeResult(0.9, 0.1, 1.0, "m", "p")
    assert result.passed is True
    assert result.quality_score == 0.9
    assert result.quality_score_10 == 9.0


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("anthropic", None, "claude-3-5-haiku-20241022"),
        ("openai", None, "gpt-4o-mini"),
        ("litellm", None, "gpt-4o-mini"),
        ("other", "override-model", "override-model"),
        ("other", None, "text-model"),
    ],
)
def test_response_eval_model_selection(monkeypatch, provider, model, expected):
    _install_config_module(monkeypatch)
    monkeypatch.delenv("JUDGE_RESPONSE_MODEL", raising=False)
    monkeypatch.setenv("JUDGE_PROVIDER", provider)
    monkeypatch.setenv("JUDGE_ENABLED", "true")
    instance = judge.LLMJudge()
    instance.model = model
    assert instance._response_eval_model() == expected


def test_response_eval_model_env_override(monkeypatch):
    _install_config_module(monkeypatch)
    monkeypatch.setenv("JUDGE_RESPONSE_MODEL", "explicit")
    monkeypatch.setenv("JUDGE_ENABLED", "true")
    instance = judge.LLMJudge()
    assert instance._response_eval_model() == "explicit"


def test_should_evaluate(monkeypatch, judge_instance):
    monkeypatch.setattr(judge.random, "random", lambda: 0.3)
    assert judge_instance.should_evaluate() is True
    judge_instance.enabled = False
    assert judge_instance.should_evaluate() is False


@pytest.mark.asyncio
async def test_call_llm_success(monkeypatch, judge_instance):
    _install_llm_client_module(monkeypatch)
    assert await judge_instance._call_llm("sys", "user") == 0.75


@pytest.mark.asyncio
async def test_call_llm_non_string_returns_none(monkeypatch, judge_instance):
    class NonStringClient(FakeLLMClient):
        response = {"v": 1}

    _install_llm_client_module(monkeypatch, NonStringClient)
    assert await judge_instance._call_llm("sys", "user") is None


@pytest.mark.asyncio
async def test_call_llm_parses_and_clamps(monkeypatch, judge_instance):
    class ParseClient(FakeLLMClient):
        response = "score 1.4"

    _install_llm_client_module(monkeypatch, ParseClient)
    assert await judge_instance._call_llm("sys", "user") == 1.0


@pytest.mark.asyncio
async def test_call_llm_no_number_returns_none(monkeypatch, judge_instance):
    class NoNumberClient(FakeLLMClient):
        response = "not a number"

    _install_llm_client_module(monkeypatch, NoNumberClient)
    assert await judge_instance._call_llm("sys", "user") is None


@pytest.mark.asyncio
async def test_call_llm_exception_and_cancel(monkeypatch, judge_instance):
    class BoomClient(FakeLLMClient):
        response = RuntimeError("boom")

    _install_llm_client_module(monkeypatch, BoomClient)
    assert await judge_instance._call_llm("sys", "user") is None

    class CancelClient(FakeLLMClient):
        async def chat(self, **kwargs):
            raise asyncio.CancelledError()

    _install_llm_client_module(monkeypatch, CancelClient)
    with pytest.raises(asyncio.CancelledError, match=r"^$"):
        await judge_instance._call_llm("sys", "user")


@pytest.mark.asyncio
async def test_call_llm_json_paths(monkeypatch, judge_instance):
    _install_llm_client_module(monkeypatch)
    FakeLLMClient.response = json.dumps({"score": 9, "reasoning": "ok"})
    assert await judge_instance._call_llm_json("sys", "msg") == {"score": 9, "reasoning": "ok"}

    FakeLLMClient.response = "[]"
    assert await judge_instance._call_llm_json("sys", "msg") is None

    FakeLLMClient.response = "bad json"
    assert await judge_instance._call_llm_json("sys", "msg") is None


@pytest.mark.asyncio
async def test_call_llm_json_non_string_and_cancel(monkeypatch, judge_instance):
    class NonStringClient(FakeLLMClient):
        response = {"score": 7}

    _install_llm_client_module(monkeypatch, NonStringClient)
    assert await judge_instance._call_llm_json("sys", "msg") is None

    class CancelClient(FakeLLMClient):
        async def chat(self, **kwargs):
            raise asyncio.CancelledError()

    _install_llm_client_module(monkeypatch, CancelClient)
    with pytest.raises(asyncio.CancelledError, match=r"^$"):
        await judge_instance._call_llm_json("sys", "msg")


@pytest.mark.asyncio
async def test_evaluate_response_success_and_fallback(monkeypatch, judge_instance):
    monkeypatch.setattr(judge, "_inc_prometheus", lambda *args, **kwargs: None)

    async def ok_json(*args, **kwargs):
        return {"score": "8.4", "reasoning": "solid"}

    monkeypatch.setattr(judge_instance, "_call_llm_json", ok_json)
    out = await judge_instance.evaluate_response("p", "r", {"k": 1})
    assert out.score == 8
    assert out.reasoning == "solid"
    assert out.weak is False

    async def score_regex(*args, **kwargs):
        return {"score": "puan=10/10", "reasoning": "great"}

    monkeypatch.setattr(judge_instance, "_call_llm_json", score_regex)
    assert (await judge_instance.evaluate_response("p", "r", ["a", "b"])).score == 10

    async def parse_fail(*args, **kwargs):
        return None

    monkeypatch.setattr(judge_instance, "_call_llm_json", parse_fail)
    out3 = await judge_instance.evaluate_response("p", "r", "ctx")
    assert out3.error == "judge_json_parse_failed"
    assert out3.score == 5


@pytest.mark.asyncio
async def test_evaluate_response_disabled_or_empty(judge_instance):
    judge_instance.enabled = False
    assert await judge_instance.evaluate_response("p", "r", "c") is None
    judge_instance.enabled = True
    assert await judge_instance.evaluate_response("", "r", "c") is None
    assert await judge_instance.evaluate_response("p", "", "c") is None


@pytest.mark.asyncio
async def test_evaluate_rag_flow(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)
    calls = []

    async def fake_llm(system, prompt):
        calls.append((system, prompt))
        return 0.62 if len(calls) == 1 else 0.17

    saved = []
    monkeypatch.setattr(judge_instance, "_call_llm", fake_llm)
    monkeypatch.setattr(judge, "_inc_prometheus", lambda *args, **kwargs: None)
    monkeypatch.setattr(judge, "_record_judge_metrics", lambda result: saved.append(result))

    async def maybe_feedback(**kwargs):
        saved.append("feedback")
        return True

    monkeypatch.setattr(judge_instance, "_maybe_record_feedback", maybe_feedback)

    result = await judge_instance.evaluate_rag("q", ["d1", "d2"], answer="a")
    assert result.relevance_score == 0.62
    assert result.hallucination_risk == 0.17
    assert isinstance(saved[0], judge.JudgeResult)
    assert "feedback" in saved


@pytest.mark.asyncio
async def test_evaluate_rag_short_circuits(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: False)
    assert await judge_instance.evaluate_rag("q", ["d"]) is None
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)
    assert await judge_instance.evaluate_rag("", ["d"]) is None
    assert await judge_instance.evaluate_rag("q", []) is None


@pytest.mark.asyncio
async def test_evaluate_rag_defaults_when_llm_none(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)

    async def none_llm(*args, **kwargs):
        return None

    async def no_feedback(**kwargs):
        return False

    monkeypatch.setattr(judge_instance, "_call_llm", none_llm)
    monkeypatch.setattr(judge, "_inc_prometheus", lambda *args, **kwargs: None)
    monkeypatch.setattr(judge, "_record_judge_metrics", lambda result: None)
    monkeypatch.setattr(judge_instance, "_maybe_record_feedback", no_feedback)
    out = await judge_instance.evaluate_rag("q", ["d"], answer="a")
    assert out.relevance_score == 0.5
    assert out.hallucination_risk == 0.0


@pytest.mark.asyncio
async def test_evaluate_rag_without_answer_skips_hallucination(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)
    calls = {"n": 0}

    async def llm_once(*args, **kwargs):
        calls["n"] += 1
        return 0.8

    monkeypatch.setattr(judge_instance, "_call_llm", llm_once)
    monkeypatch.setattr(judge, "_inc_prometheus", lambda *args, **kwargs: None)
    monkeypatch.setattr(judge, "_record_judge_metrics", lambda result: None)
    monkeypatch.setattr(
        judge_instance, "_maybe_record_feedback", lambda **kwargs: asyncio.sleep(0, result=False)
    )
    out = await judge_instance.evaluate_rag("q", ["d1", "d2"], answer=None)
    assert out.relevance_score == 0.8
    assert out.hallucination_risk == 0.0
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_maybe_record_feedback_paths(judge_instance):
    result = judge.JudgeResult(0.2, 0.9, 1.0, "m", "p")

    judge_instance.auto_feedback_enabled = False
    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is False
    )

    judge_instance.auto_feedback_enabled = True
    judge_instance.auto_feedback_threshold = 1.0
    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is False
    )

    judge_instance.auto_feedback_threshold = 9.5
    assert (
        await judge_instance._maybe_record_feedback(
            query="", documents=["d"], answer="a", result=result
        )
        is False
    )


@pytest.mark.asyncio
async def test_maybe_record_feedback_success_and_exceptions(monkeypatch, judge_instance):
    result = judge.JudgeResult(0.2, 0.9, 1.0, "m", "p")
    judge_instance.auto_feedback_enabled = True
    judge_instance.auto_feedback_threshold = 9.5

    class Store:
        async def flag_weak_response(self, **kwargs):
            self.kwargs = kwargs
            return True

    store = Store()

    fake_mod = types.ModuleType("core.active_learning")
    fake_mod.get_feedback_store = lambda config: store
    fake_mod.schedule_continuous_learning_cycle = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "core.active_learning", fake_mod)

    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is True
    )

    fake_mod.schedule_continuous_learning_cycle = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("x")
    )
    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is True
    )

    class BadStore:
        async def flag_weak_response(self, **kwargs):
            raise RuntimeError("boom")

    fake_mod.get_feedback_store = lambda config: BadStore()
    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is False
    )

    class FalseStore:
        async def flag_weak_response(self, **kwargs):
            return False

    fake_mod.get_feedback_store = lambda config: FalseStore()
    assert (
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )
        is False
    )


@pytest.mark.asyncio
async def test_maybe_record_feedback_cancelled(monkeypatch, judge_instance):
    result = judge.JudgeResult(0.2, 0.9, 1.0, "m", "p")

    class CancelStore:
        async def flag_weak_response(self, **kwargs):
            raise asyncio.CancelledError()

    fake_mod = types.ModuleType("core.active_learning")
    fake_mod.get_feedback_store = lambda config: CancelStore()
    fake_mod.schedule_continuous_learning_cycle = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "core.active_learning", fake_mod)

    with pytest.raises(asyncio.CancelledError, match=r"^$"):
        await judge_instance._maybe_record_feedback(
            query="q", documents=["d"], answer="a", result=result
        )


@pytest.mark.asyncio
async def test_schedule_background_evaluation(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)
    called = {"v": 0}

    async def fake_eval(*args, **kwargs):
        called["v"] += 1

    monkeypatch.setattr(judge_instance, "evaluate_rag", fake_eval)

    judge_instance.schedule_background_evaluation("q", ["d"], "a")
    await asyncio.sleep(0)
    assert called["v"] == 1


@pytest.mark.asyncio
async def test_schedule_background_evaluation_exception(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)

    async def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(judge_instance, "evaluate_rag", boom)

    judge_instance.schedule_background_evaluation("q", ["d"], "a")
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_schedule_background_evaluation_cancel_raises(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(judge_instance, "evaluate_rag", cancel)

    judge_instance.schedule_background_evaluation("q", ["d"], "a")
    await asyncio.sleep(0)


def test_schedule_background_no_loop(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: True)

    def no_loop():
        raise RuntimeError("no loop")

    monkeypatch.setattr(judge.asyncio, "get_running_loop", no_loop)
    judge_instance.schedule_background_evaluation("q", ["d"], "a")


def test_schedule_background_skips_when_sampling_disabled(monkeypatch, judge_instance):
    monkeypatch.setattr(judge_instance, "_should_evaluate", lambda: False)
    judge_instance.schedule_background_evaluation("q", ["d"], "a")


def test_inc_prometheus_cache_and_errors(monkeypatch):
    judge._prometheus_gauges.clear()

    class Gauge:
        def __init__(self, name, desc):
            self.values = []

        def set(self, value):
            self.values.append(value)

    prom_mod = types.ModuleType("prometheus_client")
    prom_mod.Gauge = Gauge
    monkeypatch.setitem(sys.modules, "prometheus_client", prom_mod)

    judge._inc_prometheus("m", 1.0)
    judge._inc_prometheus("m", 2.0)
    assert len(judge._prometheus_gauges) == 1
    assert judge._prometheus_gauges["m"].values == [1.0, 2.0]

    class BadGauge:
        def __init__(self, name, desc):
            raise RuntimeError("x")

    prom_mod.Gauge = BadGauge
    judge._inc_prometheus("n", 1.0)


@pytest.mark.asyncio
async def test_record_judge_metrics_variants(monkeypatch):
    result = judge.JudgeResult(0.3, 0.4, 1.0, "m", "p")

    class Collector:
        def __init__(self, sink):
            self._usage_sink = sink

    sink_calls = []

    def sink(payload):
        sink_calls.append(payload)

    metrics_mod = types.ModuleType("core.llm_metrics")
    metrics_mod.get_llm_metrics_collector = lambda: Collector(sink)
    monkeypatch.setitem(sys.modules, "core.llm_metrics", metrics_mod)
    judge._record_judge_metrics(result)
    assert sink_calls and sink_calls[0]["type"] == "judge"

    async def async_sink(payload):
        return None

    assert await async_sink({"type": "judge"}) is None
    metrics_mod.get_llm_metrics_collector = lambda: Collector(async_sink)

    def no_loop():
        raise RuntimeError("no loop")

    monkeypatch.setattr(judge.asyncio, "get_running_loop", no_loop)
    judge._record_judge_metrics(result)

    metrics_mod.get_llm_metrics_collector = lambda: Collector(None)
    judge._record_judge_metrics(result)


@pytest.mark.asyncio
async def test_record_judge_metrics_async_sink_with_running_loop(monkeypatch):
    result = judge.JudgeResult(0.3, 0.4, 1.0, "m", "p")
    task_calls = {"n": 0}

    class Collector:
        def __init__(self, sink):
            self._usage_sink = sink

    async def async_sink(payload):
        return None

    assert await async_sink({"type": "judge"}) is None

    class _Loop:
        def create_task(self, coro):
            task_calls["n"] += 1
            coro.close()
            return None

    metrics_mod = types.ModuleType("core.llm_metrics")
    metrics_mod.get_llm_metrics_collector = lambda: Collector(async_sink)
    monkeypatch.setitem(sys.modules, "core.llm_metrics", metrics_mod)
    monkeypatch.setattr(judge.asyncio, "get_running_loop", lambda: _Loop())
    judge._record_judge_metrics(result)
    assert task_calls["n"] == 1


def test_record_judge_metrics_exception(monkeypatch):
    bad_mod = types.ModuleType("core.llm_metrics")
    bad_mod.get_llm_metrics_collector = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    monkeypatch.setitem(sys.modules, "core.llm_metrics", bad_mod)
    result = judge.JudgeResult(0.3, 0.4, 1.0, "m", "p")
    judge._record_judge_metrics(result)


def test_get_llm_judge_singleton(monkeypatch):
    _install_config_module(monkeypatch)
    judge._JUDGE = None
    first = judge.get_llm_judge()
    second = judge.get_llm_judge()
    assert first is second
