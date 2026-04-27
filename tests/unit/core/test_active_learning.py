import asyncio
import builtins
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

import core.active_learning as al


class DummyConfig:
    ENABLE_ACTIVE_LEARNING = True
    AL_MIN_RATING_FOR_TRAIN = 1
    ENABLE_CONTINUOUS_LEARNING = True
    CONTINUOUS_LEARNING_OUTPUT_DIR = "data/continuous_learning"
    CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 1
    CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 1
    CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 50
    CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 0
    CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
    ENABLE_LORA_TRAINING = True
    LORA_BASE_MODEL = "test/model"
    LORA_RANK = 8
    LORA_ALPHA = 16
    LORA_DROPOUT = 0.05
    LORA_OUTPUT_DIR = "data/lora_adapters"
    LORA_EPOCHS = 1
    LORA_BATCH_SIZE = 2
    LORA_USE_4BIT = False
    DATABASE_URL = "sqlite+aiosqlite:///data/sidar.db"


class InMemoryStore:
    def __init__(self, rows=None, min_rating=1):
        self.rows = list(rows or [])
        self.min_rating_for_train = min_rating
        self.marked = []

    async def get_pending_export(self, min_rating=None):
        threshold = self.min_rating_for_train if min_rating is None else min_rating
        return [r for r in self.rows if r.get("rating", 0) >= threshold and not r.get("exported")]

    async def mark_exported(self, ids):
        self.marked.extend(ids)

    async def get_pending_signals(self, limit=10000):
        return self.rows[:limit]


@pytest.mark.asyncio
async def test_feedback_store_noop_when_disabled_or_sqlalchemy_missing(monkeypatch):
    monkeypatch.setattr(al, "_SA_AVAILABLE", False)
    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    await store.initialize()
    assert store._engine is None

    disabled = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=False))
    assert await disabled.record("p", "r") is False
    assert await disabled.get_pending_export() == []
    assert await disabled.get_pending_signals() == []
    await disabled.mark_exported([1, 2])
    assert await disabled.stats() == {}


@pytest.mark.asyncio
async def test_feedback_store_flag_weak_response_merges_tags(monkeypatch):
    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    called = {}

    async def fake_initialize():
        store._engine = object()

    async def fake_record(**kwargs):
        called.update(kwargs)
        return True

    monkeypatch.setattr(store, "initialize", fake_initialize)
    monkeypatch.setattr(store, "record", fake_record)

    result = await store.flag_weak_response(
        prompt="p",
        response="r",
        score=11,
        reasoning=" why ",
        tags=["x"],
        user_id="u",
    )

    assert result is True
    assert called["rating"] == -1
    assert called["correction"] == "why"
    assert "weak_response" in called["tags"]
    assert "judge_reasoning" in called["tags"]
    assert "score:10" in called["tags"]


@pytest.mark.asyncio
async def test_feedback_store_get_pending_signals_parses_bad_json(monkeypatch):
    monkeypatch.setattr(al, "sql_text", lambda s: s, raising=False)

    class FakeRows:
        def fetchall(self):
            return [
                types.SimpleNamespace(_mapping={"tags": '["a"]'}),
                types.SimpleNamespace(_mapping={"tags": "bad-json"}),
            ]

    class FakeConn:
        async def execute(self, *args, **kwargs):
            return FakeRows()

    class Ctx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *args):
            return False

    class FakeEngine:
        def connect(self):
            return Ctx()

    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    store._engine = FakeEngine()

    out = await store.get_pending_signals()
    assert out[0]["tags"] == ["a"]
    assert out[1]["tags"] == []


@pytest.mark.asyncio
async def test_feedback_store_mark_exported_builds_chunked_placeholders(monkeypatch):
    monkeypatch.setattr(al, "sql_text", lambda s: s, raising=False)
    executed = []

    class FakeConn:
        async def execute(self, stmt, params):
            executed.append((str(stmt), params))

    class Ctx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *args):
            return False

    class FakeEngine:
        def begin(self):
            return Ctx()

    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    store._engine = FakeEngine()

    await store.mark_exported([1, 2, 3])
    assert executed
    sql, params = executed[0]
    assert "id_0" in sql and "id_1" in sql
    assert params["id_2"] == 3


@pytest.mark.asyncio
async def test_feedback_store_full_db_paths_and_close(monkeypatch):
    monkeypatch.setattr(al, "_SA_AVAILABLE", True)
    monkeypatch.setattr(al, "sql_text", lambda s: s, raising=False)

    executed = []

    class FakeResult:
        def __init__(self, scalar_value=None, rows=None):
            self._scalar = scalar_value
            self._rows = rows or []

        def scalar(self):
            return self._scalar

        def fetchall(self):
            return self._rows

    class FakeConn:
        def __init__(self, mode):
            self.mode = mode
            self.scalar_values = iter([7, 5, 2, 3])

        async def execute(self, stmt, params=None):
            executed.append((self.mode, str(stmt), params or {}))
            text = str(stmt)
            if "SELECT id, prompt" in text:
                rows = [
                    types.SimpleNamespace(
                        _mapping={
                            "id": 11,
                            "prompt": "p",
                            "response": "r",
                            "correction": "",
                            "rating": 1,
                            "user_id": "u",
                            "provider": "x",
                            "model": "m",
                        }
                    )
                ]
                return FakeResult(rows=rows)
            if "COUNT(*)" in text:
                return FakeResult(scalar_value=next(self.scalar_values))
            return FakeResult()

    class Ctx:
        def __init__(self, mode):
            self.mode = mode

        async def __aenter__(self):
            return FakeConn(self.mode)

        async def __aexit__(self, *args):
            return False

    class FakeEngine:
        def begin(self):
            return Ctx("begin")

        def connect(self):
            return Ctx("connect")

        async def dispose(self):
            executed.append(("dispose", "dispose", {}))

    monkeypatch.setattr(
        al, "create_async_engine", lambda *args, **kwargs: FakeEngine(), raising=False
    )

    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    await store.initialize()
    assert store._engine is not None

    assert (
        await store.record(
            prompt="p", response="r", rating=2, correction="c", user_id="u", tags=["t"]
        )
        is True
    )
    pending = await store.get_pending_export()
    assert pending[0]["id"] == 11

    stats = await store.stats()
    assert stats == {"total": 7, "positive": 5, "negative": 2, "pending_export": 3}

    await store.close()
    assert store._engine is None


@pytest.mark.asyncio
async def test_feedback_store_flag_weak_response_engine_missing_and_empty_reasoning(monkeypatch):
    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))

    async def init_without_engine():
        return None

    monkeypatch.setattr(store, "initialize", init_without_engine)
    assert await store.flag_weak_response("p", "r", 0, "") is False

    store._engine = object()
    called = {}

    async def fake_record(**kwargs):
        called.update(kwargs)
        return True

    monkeypatch.setattr(store, "record", fake_record)
    assert await store.flag_weak_response("p", "r", 0, "", tags=["base"]) is True
    assert "judge_reasoning" not in called["tags"]
    assert "score:1" in called["tags"]


@pytest.mark.asyncio
async def test_feedback_store_flag_weak_response_returns_false_when_disabled():
    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=False))
    assert await store.flag_weak_response("p", "r", 5, "reason") is False


@pytest.mark.asyncio
async def test_dataset_exporter_formats_and_empty_case(tmp_path):
    rows = [
        {"id": 1, "prompt": "p1", "response": "r1", "correction": "", "rating": 1},
        {"id": 2, "prompt": "p2", "response": "r2", "correction": "c2", "rating": 1},
    ]
    store = InMemoryStore(rows)
    exporter = al.DatasetExporter(store)

    jsonl_path = tmp_path / "a.jsonl"
    out_jsonl = await exporter.export(str(jsonl_path), fmt="jsonl")
    assert out_jsonl["count"] == 2
    lines = [json.loads(x) for x in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"prompt": "p1", "completion": "r1"}
    assert lines[1] == {"prompt": "p2", "completion": "c2"}
    assert store.marked == [1, 2]

    alpaca_path = tmp_path / "b.jsonl"
    out_alpaca = await exporter.export(str(alpaca_path), fmt="alpaca", mark_done=False)
    assert out_alpaca["format"] == "alpaca"

    sharegpt_path = tmp_path / "c.jsonl"
    out_share = await exporter.export(str(sharegpt_path), fmt="sharegpt")
    assert out_share["format"] == "sharegpt"

    empty_store = InMemoryStore([])
    empty = await al.DatasetExporter(empty_store).export(str(tmp_path / "empty.jsonl"))
    assert empty["count"] == 0


@pytest.mark.asyncio
async def test_dataset_exporter_rejects_unknown_format(tmp_path):
    store = InMemoryStore([])
    with pytest.raises(ValueError):
        await al.DatasetExporter(store).export(str(tmp_path / "x"), fmt="unknown")


@pytest.mark.asyncio
async def test_export_file_error(monkeypatch):
    store = InMemoryStore(
        [{"id": 1, "prompt": "p", "response": "r", "correction": "", "rating": 1}]
    )
    exporter = al.DatasetExporter(store)

    # asyncio.to_thread'den doğrudan PermissionError fırlatarak test et.
    # Not: al.Path (pathlib.Path) sınıf metodunu global olarak patch etmek yerine
    # to_thread'i patch etmek daha güvenlidir — diğer testleri etkilemez.
    async def fake_to_thread(func, *args, **kwargs):
        raise PermissionError("Erişim engellendi")

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    with pytest.raises(PermissionError):
        await exporter.export("/root/secret.jsonl")


def test_pipeline_helpers_and_example_builders():
    pipe = al.ContinuousLearningPipeline(InMemoryStore(), config=DummyConfig())

    assert pipe._normalize_tags(["a", "", 1]) == ["a", "1"]
    assert pipe._normalize_tags('["x","y"]') == ["x", "y"]
    assert pipe._normalize_tags("bad") == []
    assert pipe._normalize_tags('{"not":"a-list"}') == []
    assert pipe._normalize_tags(None) == []
    assert pipe._is_judge_reasoning_signal({"tags": ["judge_reasoning", "weak_response"]}) is True

    rows = [
        {"id": 1, "prompt": "p", "response": "r", "correction": "", "rating": 1, "tags": []},
        {"id": 2, "prompt": " ", "response": "r", "correction": "", "rating": 1, "tags": []},
        {"id": 3, "prompt": "p", "response": "", "correction": "", "rating": 1, "tags": []},
        {"id": 4, "prompt": "p", "response": "r", "correction": "c", "rating": -1, "tags": []},
        {
            "id": 5,
            "prompt": "p",
            "response": "r",
            "correction": "c",
            "rating": 1,
            "tags": ["judge_reasoning", "weak_response"],
        },
    ]
    sft = pipe._build_sft_examples(rows)
    assert [x["feedback_id"] for x in sft] == [1]

    pref = pipe._build_preference_examples(rows)
    assert [x["feedback_id"] for x in pref] == [4]


def test_pipeline_build_preference_examples_skips_equal_and_neutral_rows():
    pipe = al.ContinuousLearningPipeline(InMemoryStore(), config=DummyConfig())
    rows = [
        {
            "id": 10,
            "prompt": "p",
            "response": "same",
            "correction": "same",
            "rating": 1,
            "tags": [],
        },
        {"id": 11, "prompt": "p", "response": "r", "correction": "c", "rating": 0, "tags": []},
    ]
    assert pipe._build_preference_examples(rows) == []


def test_pipeline_serialize_and_write_jsonl(tmp_path):
    rows = [{"instruction": "p", "output": "o", "input": "i"}, {"instruction": "", "output": "o"}]

    alpaca = al.ContinuousLearningPipeline._serialize_sft_examples(rows, "alpaca")
    assert alpaca == [{"instruction": "p", "input": "i", "output": "o"}]

    jsonl = al.ContinuousLearningPipeline._serialize_sft_examples(rows, "jsonl")
    assert jsonl == [{"prompt": "p", "completion": "o"}]

    share = al.ContinuousLearningPipeline._serialize_sft_examples(rows, "sharegpt")
    assert share[0]["conversations"][0]["value"] == "p"

    with pytest.raises(ValueError):
        al.ContinuousLearningPipeline._serialize_sft_examples(rows, "x")

    out = tmp_path / "sft.jsonl"
    al.ContinuousLearningPipeline._write_jsonl(out, [{"a": 1}])
    assert out.exists()


@pytest.mark.asyncio
async def test_pipeline_build_dataset_bundle_and_manifest(tmp_path):
    rows = [
        {"id": 1, "prompt": "p1", "response": "r1", "correction": "", "rating": 1, "tags": []},
        {"id": 2, "prompt": "p2", "response": "r2", "correction": "c2", "rating": -1, "tags": []},
        {
            "id": 3,
            "prompt": "p3",
            "response": "r3",
            "correction": "c3",
            "rating": 1,
            "tags": ["judge_reasoning", "weak_response"],
        },
    ]
    store = InMemoryStore(rows)
    cfg = DummyConfig()
    cfg.CONTINUOUS_LEARNING_OUTPUT_DIR = str(tmp_path)
    pipe = al.ContinuousLearningPipeline(store, config=cfg)

    manifest = await pipe.build_dataset_bundle()
    assert manifest["counts"]["signals"] == 3
    assert manifest["counts"]["sft_examples"] == 1
    assert manifest["counts"]["preference_examples"] == 1
    assert Path(
        manifest["manifest_path"] if "manifest_path" in manifest else manifest["bundle_dir"]
    ).exists()
    assert Path(manifest["sft_path"]).exists()
    assert Path(manifest["preference_path"]).exists()


@pytest.mark.asyncio
async def test_pipeline_run_cycle_paths(monkeypatch):
    cfg = DummyConfig()
    store = InMemoryStore([])
    trainer = types.SimpleNamespace(enabled=True, train=lambda p: {"success": True, "path": p})
    pipe = al.ContinuousLearningPipeline(store, trainer=trainer, config=cfg)

    async def manifest_small():
        return {"counts": {"sft_examples": 0, "preference_examples": 0}, "sft_path": "x"}

    monkeypatch.setattr(pipe, "build_dataset_bundle", manifest_small)
    out = await pipe.run_cycle(reason="manual")
    assert out["reason"] == "insufficient_signals"

    pipe.cooldown_seconds = 60
    pipe._last_run_at = 100
    monkeypatch.setattr(al.time, "time", lambda: 120)
    out2 = await pipe.run_cycle()
    assert out2["reason"] == "cooldown_active"

    pipe.cooldown_seconds = 0

    async def manifest_ready():
        return {
            "counts": {"sft_examples": 2, "preference_examples": 0},
            "sft_path": "dataset.jsonl",
        }

    monkeypatch.setattr(pipe, "build_dataset_bundle", manifest_ready)
    out3 = await pipe.run_cycle(reason="cron")
    assert out3["success"] is True
    assert out3["training_result"]["success"] is True

    pipe_disabled = al.ContinuousLearningPipeline(
        store, trainer=trainer, config=types.SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=False)
    )
    assert (await pipe_disabled.run_cycle())["reason"] == "continuous_learning_disabled"


@pytest.mark.asyncio
async def test_pipeline_run_cycle_returns_default_training_result_when_trainer_disabled(
    monkeypatch,
):
    cfg = DummyConfig()
    trainer = types.SimpleNamespace(enabled=False, train=lambda p: {"success": True, "path": p})
    pipe = al.ContinuousLearningPipeline(InMemoryStore([]), trainer=trainer, config=cfg)

    async def manifest_ready():
        return {
            "counts": {"sft_examples": 3, "preference_examples": 0},
            "sft_path": "dataset.jsonl",
        }

    monkeypatch.setattr(pipe, "build_dataset_bundle", manifest_ready)
    out = await pipe.run_cycle(reason="manual")
    assert out["success"] is True
    assert out["training_result"]["reason"] == "trainer_disabled_or_insufficient_sft"


@pytest.mark.asyncio
async def test_pipeline_schedule_cycle(monkeypatch):
    cfg = DummyConfig()
    pipe = al.ContinuousLearningPipeline(InMemoryStore([]), config=cfg)

    async def fake_run_cycle(**kwargs):
        return {"success": True}

    monkeypatch.setattr(pipe, "run_cycle", fake_run_cycle)

    class FakeLoop:
        def __init__(self):
            self.created = []

        def create_task(self, coro, name=None):
            self.created.append((coro, name))
            return asyncio.create_task(coro)

    loop = FakeLoop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    assert pipe.schedule_cycle(reason="bg") is True
    await asyncio.sleep(0)
    assert loop.created and loop.created[0][1] == "sidar_continuous_learning"

    monkeypatch.setattr(
        asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop"))
    )
    assert pipe.schedule_cycle() is False


@pytest.mark.asyncio
async def test_pipeline_schedule_cycle_runner_handles_errors(monkeypatch):
    cfg = DummyConfig()
    pipe = al.ContinuousLearningPipeline(InMemoryStore([]), config=cfg)

    class FakeLoop:
        def create_task(self, coro, name=None):
            return asyncio.create_task(coro)

    async def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipe, "run_cycle", boom)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    assert pipe.schedule_cycle(reason="bg") is True
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_pipeline_schedule_cycle_disabled_and_cancelled_error(monkeypatch):
    disabled_pipe = al.ContinuousLearningPipeline(
        InMemoryStore([]),
        config=types.SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=False),
    )
    assert disabled_pipe.schedule_cycle(reason="bg") is False

    cfg = DummyConfig()
    pipe = al.ContinuousLearningPipeline(InMemoryStore([]), config=cfg)

    class CancelLoop:
        def create_task(self, coro, name=None):
            return asyncio.create_task(coro)

    async def cancelled(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(pipe, "run_cycle", cancelled)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: CancelLoop())
    assert pipe.schedule_cycle(reason="bg") is True
    await asyncio.sleep(0)


def test_lora_trainer_check_and_train_paths(monkeypatch):
    cfg = DummyConfig()
    trainer = al.LoRATrainer(config=cfg)

    monkeypatch.setitem(sys.modules, "peft", types.ModuleType("peft"))
    monkeypatch.setitem(sys.modules, "transformers", types.ModuleType("transformers"))
    monkeypatch.setitem(sys.modules, "datasets", types.ModuleType("datasets"))
    trainer._peft_available = None
    assert trainer._check_peft() is True

    trainer.enabled = False
    assert trainer.train("d")["reason"] == "LORA_TRAINING devre dışı"

    trainer.enabled = True
    monkeypatch.setattr(trainer, "_check_peft", lambda: False)
    assert trainer.train("d")["reason"] == "peft/transformers kurulu değil"

    monkeypatch.setattr(trainer, "_check_peft", lambda: True)
    trainer.base_model = ""
    assert trainer.train("d")["reason"] == "LORA_BASE_MODEL ayarlanmamış"

    trainer.base_model = "m"
    monkeypatch.setattr(trainer, "_run_training", lambda _: {"success": True})
    assert trainer.train("d")["success"] is True

    def boom(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(trainer, "_run_training", boom)
    assert trainer.train("d")["success"] is False


def test_lora_trainer_check_peft_importerror(monkeypatch):
    trainer = al.LoRATrainer(config=DummyConfig())
    trainer._peft_available = None

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {"peft", "transformers", "datasets"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert builtins.__import__("json").__name__ == "json"
    assert trainer._check_peft() is False


def test_lora_trainer_check_peft_uses_cached_value():
    trainer = al.LoRATrainer(config=DummyConfig())
    trainer._peft_available = False
    assert trainer._check_peft() is False


def test_lora_run_training_happy_path_with_fake_modules(monkeypatch, tmp_path):
    cfg = DummyConfig()
    cfg.LORA_OUTPUT_DIR = str(tmp_path / "out")
    trainer = al.LoRATrainer(config=cfg)

    class FakeTokenizer:
        eos_token = "<eos>"
        pad_token = None

        @staticmethod
        def from_pretrained(*args, **kwargs):
            return FakeTokenizer()

        def __call__(self, text, truncation=True, max_length=512, padding="max_length"):
            return {"input_ids": [1, 2, 3]}

        def save_pretrained(self, out):
            Path(out, "tok.txt").write_text("ok", encoding="utf-8")

    class FakeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return FakeModel()

        def print_trainable_parameters(self):
            return None

        def save_pretrained(self, out):
            Path(out, "model.txt").write_text("ok", encoding="utf-8")

    class FakeTrainResult:
        training_loss = 0.12
        global_step = 7

    class FakeTrainer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def train(self):
            return FakeTrainResult()

    class FakeDataset:
        column_names = ["instruction", "output"]

        def map(self, fn, remove_columns=None):
            fn({"instruction": "p", "output": "o"})
            fn({"conversations": [{"from": "human", "value": "h"}, {"from": "gpt", "value": "g"}]})
            return [{"x": 1}]

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = FakeModel
    fake_transformers.AutoTokenizer = FakeTokenizer
    fake_transformers.TrainingArguments = lambda **kwargs: kwargs
    fake_transformers.Trainer = lambda **kwargs: FakeTrainer(**kwargs)
    fake_transformers.DataCollatorForSeq2Seq = lambda tokenizer, model=None, padding=True: {
        "tok": tokenizer,
        "model": model,
        "padding": padding,
    }

    fake_peft = types.ModuleType("peft")
    fake_peft.TaskType = types.SimpleNamespace(CAUSAL_LM="causal")
    fake_peft.LoraConfig = lambda **kwargs: kwargs
    fake_peft.get_peft_model = lambda model, conf: model

    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = lambda *args, **kwargs: FakeDataset()

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)

    result = trainer._run_training("dataset.jsonl")
    assert result["success"] is True
    assert Path(result["output_dir"]).exists()


def test_lora_run_training_4bit_importerror_fallback(monkeypatch, tmp_path):
    cfg = DummyConfig()
    cfg.LORA_OUTPUT_DIR = str(tmp_path / "out4")
    cfg.LORA_USE_4BIT = True
    trainer = al.LoRATrainer(config=cfg)

    class FakeTokenizer:
        eos_token = "<eos>"
        pad_token = "pad"

        @staticmethod
        def from_pretrained(*args, **kwargs):
            return FakeTokenizer()

        def __call__(self, text, **kwargs):
            return {"input_ids": [1]}

        def save_pretrained(self, out):
            Path(out, "tok.txt").write_text("ok", encoding="utf-8")

    class FakeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            assert "quantization_config" not in kwargs
            return FakeModel()

        def print_trainable_parameters(self):
            return None

        def save_pretrained(self, out):
            Path(out, "model.txt").write_text("ok", encoding="utf-8")

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = FakeModel
    fake_transformers.AutoTokenizer = FakeTokenizer
    fake_transformers.TrainingArguments = lambda **kwargs: kwargs
    fake_transformers.Trainer = lambda **kwargs: types.SimpleNamespace(
        train=lambda: types.SimpleNamespace(training_loss=0.1, global_step=1)
    )
    fake_transformers.DataCollatorForSeq2Seq = lambda *args, **kwargs: None

    fake_peft = types.ModuleType("peft")
    fake_peft.TaskType = types.SimpleNamespace(CAUSAL_LM="causal")
    fake_peft.LoraConfig = lambda **kwargs: kwargs
    fake_peft.get_peft_model = lambda model, conf: model

    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = lambda *args, **kwargs: types.SimpleNamespace(
        column_names=["prompt", "completion"],
        map=lambda fn, remove_columns=None: [fn({"prompt": "p", "completion": "c"})],
    )

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)

    assert trainer._run_training("x")["success"] is True


def test_lora_run_training_4bit_quant_and_conversation_branches(monkeypatch, tmp_path):
    cfg = DummyConfig()
    cfg.LORA_OUTPUT_DIR = str(tmp_path / "out4-ok")
    cfg.LORA_USE_4BIT = True
    trainer = al.LoRATrainer(config=cfg)

    class FakeTokenizer:
        eos_token = "<eos>"
        pad_token = None

        @staticmethod
        def from_pretrained(*args, **kwargs):
            return FakeTokenizer()

        def __call__(self, text, **kwargs):
            return {"input_ids": [1, 2]}

        def save_pretrained(self, out):
            Path(out, "tok.txt").write_text("ok", encoding="utf-8")

    class FakeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            assert "quantization_config" in kwargs
            return FakeModel()

        def print_trainable_parameters(self):
            return None

        def save_pretrained(self, out):
            Path(out, "model.txt").write_text("ok", encoding="utf-8")

    class FakeDataset:
        column_names = ["conversations"]

        def map(self, fn, remove_columns=None):
            fn({"conversations": [{"from": "human", "value": "only-human"}]})
            fn({"conversations": [{"from": "gpt", "value": "only-gpt"}]})
            fn({"conversations": "not-a-list"})
            return [{"ok": 1}]

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = FakeModel
    fake_transformers.AutoTokenizer = FakeTokenizer
    fake_transformers.TrainingArguments = lambda **kwargs: kwargs
    fake_transformers.Trainer = lambda **kwargs: types.SimpleNamespace(
        train=lambda: types.SimpleNamespace(training_loss=0.1, global_step=1)
    )
    fake_transformers.DataCollatorForSeq2Seq = lambda *args, **kwargs: None
    fake_transformers.BitsAndBytesConfig = lambda **kwargs: kwargs

    fake_peft = types.ModuleType("peft")
    fake_peft.TaskType = types.SimpleNamespace(CAUSAL_LM="causal")
    fake_peft.LoraConfig = lambda **kwargs: kwargs
    fake_peft.get_peft_model = lambda model, conf: model

    fake_datasets = types.ModuleType("datasets")
    fake_datasets.load_dataset = lambda *args, **kwargs: FakeDataset()

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "float16"

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert trainer._run_training("x")["success"] is True


def test_chunked_and_singletons(monkeypatch):
    assert list(al._chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    al._feedback_store = None
    al._continuous_learning_pipeline = None

    fake_config_mod = types.ModuleType("config")

    class Config(DummyConfig):
        pass

    fake_config_mod.Config = Config
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    store1 = al.get_feedback_store()
    store2 = al.get_feedback_store()
    assert store1 is store2

    pipe1 = al.get_continuous_learning_pipeline()
    pipe2 = al.get_continuous_learning_pipeline()
    assert pipe1 is pipe2


def test_get_continuous_learning_pipeline_double_checked_lock_path(monkeypatch):
    al._continuous_learning_pipeline = None

    sentinel = object()

    class EnterSetsPipeline:
        def __enter__(self):
            al._continuous_learning_pipeline = sentinel
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(al, "_pipeline_lock", EnterSetsPipeline())
    assert al.get_continuous_learning_pipeline(config=DummyConfig()) is sentinel


def test_active_learning_module_importerror_sets_sa_false(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("sqlalchemy"):
            raise ImportError("sqlalchemy blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    reloaded = importlib.reload(al)
    assert reloaded._SA_AVAILABLE is False
    monkeypatch.setattr(builtins, "__import__", real_import)
    importlib.reload(reloaded)


def test_active_learning_module_import_success_sets_sa_true(monkeypatch):
    fake_sa_asyncio = types.ModuleType("sqlalchemy.ext.asyncio")
    fake_sa_asyncio.create_async_engine = lambda *args, **kwargs: object()
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.text = lambda value: value

    monkeypatch.setitem(sys.modules, "sqlalchemy.ext.asyncio", fake_sa_asyncio)
    monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sa)

    reloaded = importlib.reload(al)
    assert reloaded._SA_AVAILABLE is True


@pytest.mark.asyncio
async def test_feedback_store_close_no_engine_is_noop():
    store = al.FeedbackStore(config=types.SimpleNamespace(ENABLE_ACTIVE_LEARNING=True))
    await store.close()
    assert store._engine is None


@pytest.mark.asyncio
async def test_schedule_and_flag_wrappers(monkeypatch):
    fake_pipe = types.SimpleNamespace(schedule_cycle=lambda reason="background": reason == "ok")
    monkeypatch.setattr(al, "get_continuous_learning_pipeline", lambda config=None: fake_pipe)
    assert al.schedule_continuous_learning_cycle(reason="ok") is True

    class FakeStore:
        async def flag_weak_response(self, **kwargs):
            return kwargs["prompt"] == "p"

    monkeypatch.setattr(al, "get_feedback_store", lambda config=None: FakeStore())
    assert await al.flag_weak_response("p", "r", 1, "x") is True
