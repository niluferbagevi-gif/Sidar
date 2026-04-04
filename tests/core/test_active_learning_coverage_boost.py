from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.active_learning as mod


class _Result:
    def __init__(self, rows=None, scalar_value=0):
        self._rows = rows or []
        self._scalar = scalar_value

    def fetchall(self):
        return [SimpleNamespace(_mapping=row) for row in self._rows]

    def scalar(self):
        return self._scalar


class _Conn:
    def __init__(self, queued_results=None):
        self.calls = []
        self._results = list(queued_results or [])

    async def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        return self._results.pop(0) if self._results else _Result()


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Engine:
    def __init__(self, conn):
        self.conn = conn
        self.disposed = False

    def begin(self):
        return _Begin(self.conn)

    def connect(self):
        return _Begin(self.conn)

    async def dispose(self):
        self.disposed = True


def test_feedback_store_initialize_and_get_pending_export_variants(monkeypatch):
    executed = []
    conn = _Conn()

    async def _exec(query, params=None):
        executed.append((query, params))
        return _Result(rows=[{"id": 1, "prompt": "p", "response": "r", "correction": "", "rating": 1, "user_id": "u", "provider": "x", "model": "m"}])

    conn.execute = _exec

    engine = _Engine(conn)
    monkeypatch.setattr(mod, "sql_text", lambda q: q, raising=False)
    monkeypatch.setattr(mod, "_SA_AVAILABLE", True)
    monkeypatch.setattr(mod, "create_async_engine", lambda *_a, **_k: engine, raising=False)

    store = mod.FeedbackStore(config=SimpleNamespace(ENABLE_ACTIVE_LEARNING=True, AL_MIN_RATING_FOR_TRAIN=3))
    async def _run():
        await store.initialize()
        return await store.get_pending_export()

    rows = asyncio.run(_run())

    assert rows and rows[0]["id"] == 1
    assert any("CREATE TABLE IF NOT EXISTS finetune_feedback" in str(q) for q, _ in executed)


def test_feedback_store_flag_and_mark_exported_empty_and_disabled():
    disabled = mod.FeedbackStore(config=SimpleNamespace(ENABLE_ACTIVE_LEARNING=False))

    async def _run():
        assert await disabled.record(prompt="p", response="r") is False
        assert await disabled.flag_weak_response("p", "r", 1, "n") is False
        assert await disabled.get_pending_export() == []
        assert await disabled.get_pending_signals() == []
        assert await disabled.stats() == {}
        await disabled.mark_exported([])

    asyncio.run(_run())


def test_dataset_exporter_formats_and_mark_done(monkeypatch, tmp_path: Path):
    called_ids = []

    class _Store:
        async def get_pending_export(self, min_rating=None):
            _ = min_rating
            return [
                {"id": 10, "prompt": "pr", "response": "res", "correction": "corr"},
                {"id": 11, "prompt": "pr2", "response": "res2", "correction": ""},
            ]

        async def mark_exported(self, ids):
            called_ids.extend(ids)

    exporter = mod.DatasetExporter(_Store())

    async def _run():
        out1 = await exporter.export(str(tmp_path / "a.jsonl"), fmt="jsonl")
        out2 = await exporter.export(str(tmp_path / "b.jsonl"), fmt="alpaca", mark_done=False)
        out3 = await exporter.export(str(tmp_path / "c.jsonl"), fmt="sharegpt")
        return out1, out2, out3

    out1, out2, out3 = asyncio.run(_run())

    assert out1["count"] == 2 and out2["count"] == 2 and out3["count"] == 2
    assert called_ids == [10, 11, 10, 11]
    assert "completion" in (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "instruction" in (tmp_path / "b.jsonl").read_text(encoding="utf-8")
    assert "conversations" in (tmp_path / "c.jsonl").read_text(encoding="utf-8")


def test_continuous_learning_run_cycle_paths(monkeypatch, tmp_path: Path):
    class _Store:
        min_rating_for_train = 1

        async def get_pending_signals(self, limit=10000):
            _ = limit
            return [
                {"id": 1, "prompt": "p", "response": "r", "correction": "c", "rating": 1, "tags": "[]"}
            ]

    cfg = SimpleNamespace(
        ENABLE_CONTINUOUS_LEARNING=True,
        CONTINUOUS_LEARNING_OUTPUT_DIR=str(tmp_path),
        CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES=2,
        CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES=2,
        CONTINUOUS_LEARNING_COOLDOWN_SECONDS=999,
    )
    pipeline = mod.ContinuousLearningPipeline(_Store(), trainer=SimpleNamespace(enabled=False), config=cfg)

    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)
    first = asyncio.run(pipeline.run_cycle(reason="r1"))
    assert first["reason"] == "insufficient_signals"

    monkeypatch.setattr(mod.time, "time", lambda: 1001.0)
    second = asyncio.run(pipeline.run_cycle(reason="r2"))
    assert second["reason"] == "cooldown_active"

    disabled = mod.ContinuousLearningPipeline(_Store(), config=SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=False))
    res_disabled = asyncio.run(disabled.run_cycle())
    assert res_disabled["reason"] == "continuous_learning_disabled"


def test_continuous_learning_schedule_cycle_paths(monkeypatch):
    pipeline = mod.ContinuousLearningPipeline(
        store=SimpleNamespace(),
        trainer=SimpleNamespace(enabled=False),
        config=SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=True),
    )

    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    assert pipeline.schedule_cycle() is False


def test_continuous_learning_schedule_cycle_success(monkeypatch):
    class _Loop:
        def __init__(self):
            self.tasks = []

        def create_task(self, coro, name=None):
            self.tasks.append((coro, name))
            return coro

    pipeline = mod.ContinuousLearningPipeline(
        store=SimpleNamespace(),
        trainer=SimpleNamespace(enabled=False),
        config=SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=True),
    )

    async def _ok(**_):
        return {"success": True}

    monkeypatch.setattr(pipeline, "run_cycle", _ok)
    loop = _Loop()
    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: loop)

    assert pipeline.schedule_cycle(reason="bg") is True
    coro, _name = loop.tasks[0]
    asyncio.run(coro)


class _FakeTokenizer:
    pad_token = None
    eos_token = "<eos>"

    @classmethod
    def from_pretrained(cls, *_a, **_k):
        return cls()

    def __call__(self, *_a, **_k):
        return {"input_ids": [1, 2, 3]}

    def save_pretrained(self, *_a, **_k):
        return None


class _FakeModel:
    @classmethod
    def from_pretrained(cls, *_a, **_k):
        return cls()

    def print_trainable_parameters(self):
        return None

    def save_pretrained(self, *_a, **_k):
        return None


class _FakeDataset:
    column_names = ["instruction", "output"]

    def map(self, fn, remove_columns=None):
        _ = remove_columns
        fn({"instruction": "p", "output": "o"})
        fn({"conversations": [{"from": "human", "value": "h"}, {"from": "gpt", "value": "a"}]})
        return self


class _FakeTrainer:
    def __init__(self, **_kwargs):
        pass

    def train(self):
        return SimpleNamespace(training_loss=0.1, global_step=7)


def test_lora_train_paths_and_run_training(monkeypatch, tmp_path: Path):
    trainer = mod.LoRATrainer(config=SimpleNamespace(ENABLE_LORA_TRAINING=False))
    assert trainer.train("dummy")["success"] is False

    trainer = mod.LoRATrainer(config=SimpleNamespace(ENABLE_LORA_TRAINING=True, LORA_BASE_MODEL=""))
    monkeypatch.setattr(trainer, "_check_peft", lambda: True)
    assert "ayarlanmamış" in trainer.train("dummy")["reason"]

    trainer = mod.LoRATrainer(
        config=SimpleNamespace(
            ENABLE_LORA_TRAINING=True,
            LORA_BASE_MODEL="base",
            LORA_OUTPUT_DIR=str(tmp_path),
            LORA_USE_4BIT=True,
        )
    )

    fake_peft = types.ModuleType("peft")
    fake_peft.LoraConfig = lambda **kwargs: kwargs
    fake_peft.get_peft_model = lambda model, _cfg: model
    fake_peft.TaskType = SimpleNamespace(CAUSAL_LM="causal")

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoTokenizer = _FakeTokenizer
    fake_transformers.AutoModelForCausalLM = _FakeModel
    fake_transformers.TrainingArguments = lambda **kwargs: kwargs
    fake_transformers.Trainer = _FakeTrainer
    fake_transformers.DataCollatorForSeq2Seq = lambda *a, **k: {"ok": True}

    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = lambda *_a, **_k: _FakeDataset()

    import sys

    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    monkeypatch.setattr(trainer, "_check_peft", lambda: True)

    result = trainer.train(str(tmp_path / "dataset.jsonl"))
    assert result["success"] is True
    assert result["steps"] == 7


def test_singleton_helpers_and_chunked(monkeypatch):
    mod._feedback_store = None
    mod._continuous_learning_pipeline = None

    class _Cfg:
        DATABASE_URL = "sqlite+aiosqlite:///tmp/a.db"
        ENABLE_CONTINUOUS_LEARNING = False

    class _ConfigCls:
        def __call__(self):
            return _Cfg()

    fake_config_module = types.ModuleType("config")
    fake_config_module.Config = _ConfigCls()

    import sys

    monkeypatch.setitem(sys.modules, "config", fake_config_module)

    store = mod.get_feedback_store()
    assert isinstance(store, mod.FeedbackStore)

    pipe = mod.get_continuous_learning_pipeline()
    assert isinstance(pipe, mod.ContinuousLearningPipeline)

    monkeypatch.setattr(pipe, "schedule_cycle", lambda **_k: True)
    assert mod.schedule_continuous_learning_cycle(reason="t") is True

    async def _flag(*_a, **_k):
        return True

    monkeypatch.setattr(store, "flag_weak_response", _flag)
    assert asyncio.run(mod.flag_weak_response("p", "r", 1, "n")) is True

    assert list(mod._chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_serialize_helpers_and_invalid_format():
    assert mod.ContinuousLearningPipeline._normalize_tags("[\"a\", \"\"]") == ["a"]
    assert mod.ContinuousLearningPipeline._normalize_tags("not-json") == []
    assert mod.ContinuousLearningPipeline._is_judge_reasoning_signal({"tags": ["weak_response", "judge_reasoning"]}) is True

    with pytest.raises(ValueError):
        mod.ContinuousLearningPipeline._serialize_sft_examples([{"instruction": "p", "output": "o"}], "x")

    rows = [{"instruction": "i", "output": "o", "input": ""}]
    assert mod.ContinuousLearningPipeline._serialize_sft_examples(rows, "alpaca")[0]["instruction"] == "i"

    p = Path("/tmp/sidar-active-learning-write-jsonl-test.jsonl")
    mod.ContinuousLearningPipeline._write_jsonl(p, [{"a": 1}])
    assert json.loads(p.read_text(encoding="utf-8").strip())["a"] == 1
    p.unlink(missing_ok=True)
