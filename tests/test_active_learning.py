"""Testler: Active Learning + LoRA/QLoRA Fine-tuning Döngüsü (Özellik 8)"""
from __future__ import annotations
import asyncio
import builtins
import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


def _run(coro):
    return asyncio.run(coro)


from core.active_learning import (
    ContinuousLearningPipeline,
    FeedbackStore,
    DatasetExporter,
    LoRATrainer,
    flag_weak_response,
    get_feedback_store,
    get_continuous_learning_pipeline,
    schedule_continuous_learning_cycle,
    _chunked,
)


# ─── FeedbackStore — devre dışı modu ────────────────────────────────────────

class TestFeedbackStoreDisabled:
    def setup_method(self):
        cfg = MagicMock()
        cfg.ENABLE_ACTIVE_LEARNING = False
        cfg.AL_MIN_RATING_FOR_TRAIN = 1
        self.store = FeedbackStore(config=cfg)

    def test_not_initialized(self):
        assert self.store._engine is None

    def test_initialize_noop(self):
        _run(self.store.initialize())
        assert self.store._engine is None

    def test_record_returns_false(self):
        result = _run(self.store.record("prompt", "response", rating=1))
        assert result is False

    def test_pending_export_empty(self):
        result = _run(self.store.get_pending_export())
        assert result == []

    def test_stats_empty(self):
        result = _run(self.store.stats())
        assert result == {}


def test_active_learning_module_sets_sa_unavailable_when_sqlalchemy_import_fails(monkeypatch):
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("sqlalchemy"):
            raise ImportError("sqlalchemy missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)

    spec = importlib.util.spec_from_file_location("active_learning_no_sa", Path("core/active_learning.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    cfg = MagicMock()
    cfg.ENABLE_ACTIVE_LEARNING = True
    cfg.AL_MIN_RATING_FOR_TRAIN = 1
    store = mod.FeedbackStore(config=cfg)
    _run(store.initialize())

    assert mod._SA_AVAILABLE is False
    assert store._engine is None


# ─── FeedbackStore — SQLite entegrasyon ──────────────────────────────────────

def _make_store(tmp_path, enabled=True):
    db = tmp_path / "test_fb.db"
    cfg = MagicMock()
    cfg.ENABLE_ACTIVE_LEARNING = enabled
    cfg.AL_MIN_RATING_FOR_TRAIN = 1
    cfg.ENABLE_CONTINUOUS_LEARNING = False
    cfg.CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 20
    cfg.CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 10
    cfg.CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 5000
    cfg.CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 3600
    cfg.CONTINUOUS_LEARNING_OUTPUT_DIR = str(tmp_path / "continuous_learning")
    cfg.CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
    cfg.ENABLE_LORA_TRAINING = False
    cfg.LORA_BASE_MODEL = ""
    cfg.LORA_RANK = 8
    cfg.LORA_ALPHA = 16
    cfg.LORA_DROPOUT = 0.05
    cfg.LORA_EPOCHS = 1
    cfg.LORA_BATCH_SIZE = 1
    cfg.LORA_USE_4BIT = False
    cfg.LORA_OUTPUT_DIR = str(tmp_path / "lora")
    return FeedbackStore(database_url=f"sqlite+aiosqlite:///{db}", config=cfg)


def _try_init(store):
    try:
        _run(store.initialize())
        return store._engine is not None
    except Exception as e:
        if "aiosqlite" in str(e) or "sqlalchemy" in str(e) or "No module" in str(e):
            return False
        raise


class TestFeedbackStoreWithSQLite:
    def test_initialize(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        assert store._engine is not None
        _run(store.close())

    def test_record_and_retrieve(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        ok = _run(store.record("Soru nedir?", "Bu bir cevaptır.", rating=1))
        assert ok is True
        rows = _run(store.get_pending_export(min_rating=1))
        assert len(rows) == 1
        assert rows[0]["prompt"] == "Soru nedir?"
        assert rows[0]["rating"] == 1
        _run(store.close())

    def test_negative_rating_not_in_positive_export(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(store.record("Kötü soru", "Kötü cevap", rating=-1))
        rows = _run(store.get_pending_export(min_rating=1))
        assert len(rows) == 0
        _run(store.close())

    def test_mark_exported(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(store.record("Soru", "Cevap", rating=1))
        rows = _run(store.get_pending_export(min_rating=1))
        ids = [r["id"] for r in rows]
        _run(store.mark_exported(ids))
        rows_after = _run(store.get_pending_export(min_rating=1))
        assert len(rows_after) == 0
        _run(store.close())

    def test_stats_returns_counts(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(store.record("Soru 1", "Cevap 1", rating=1))
        _run(store.record("Soru 2", "Cevap 2", rating=-1))
        stats = _run(store.stats())
        assert stats["total"] == 2
        assert stats["positive"] == 1
        assert stats["negative"] == 1
        _run(store.close())

    def test_correction_stored(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(store.record("Soru", "Yanlış cevap", rating=1, correction="Doğru cevap"))
        rows = _run(store.get_pending_export(min_rating=1))
        assert rows[0]["correction"] == "Doğru cevap"
        _run(store.close())

    def test_flag_weak_response_records_negative_feedback(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        ok = _run(
            store.flag_weak_response(
                prompt="Özet çıkar",
                response="Eksik cevap",
                score=6,
                reasoning="Bağlamdan önemli maddeler eksik.",
                session_id="sess-weak",
            )
        )
        assert ok is True
        rows = _run(store.get_pending_export(min_rating=-1))
        assert len(rows) == 1
        assert rows[0]["rating"] == -1
        assert rows[0]["correction"] == "Bağlamdan önemli maddeler eksik."
        _run(store.close())


def test_feedback_store_record_propagates_db_execute_errors(monkeypatch):
    cfg = MagicMock()
    cfg.ENABLE_ACTIVE_LEARNING = True
    cfg.AL_MIN_RATING_FOR_TRAIN = 1
    store = FeedbackStore(config=cfg)

    class _DBError(Exception):
        pass

    class _Conn:
        async def execute(self, *_args, **_kwargs):
            raise _DBError("insert failed")

    class _Begin:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    store._engine = types.SimpleNamespace(begin=lambda: _Begin())

    import core.active_learning as active_learning_module

    monkeypatch.setattr(active_learning_module, "sql_text", lambda sql: sql, raising=False)

    with pytest.raises(_DBError, match="insert failed"):
        _run(store.record("prompt", "response", rating=1))


def test_flag_weak_response_returns_false_when_store_disabled(monkeypatch):
    cfg = MagicMock()
    cfg.ENABLE_ACTIVE_LEARNING = False
    cfg.AL_MIN_RATING_FOR_TRAIN = 1
    store = FeedbackStore(config=cfg)

    initialize_calls = []
    record_calls = []

    async def _initialize():
        initialize_calls.append(True)

    async def _record(**kwargs):
        record_calls.append(kwargs)
        return True

    monkeypatch.setattr(store, "initialize", _initialize)
    monkeypatch.setattr(store, "record", _record)

    ok = _run(
        store.flag_weak_response(
            prompt="soru",
            response="cevap",
            score=2,
            reasoning="eksik",
        )
    )

    assert ok is False
    assert initialize_calls == []
    assert record_calls == []


def test_flag_weak_response_returns_false_when_initialize_leaves_engine_unavailable(monkeypatch):
    cfg = MagicMock()
    cfg.ENABLE_ACTIVE_LEARNING = True
    cfg.AL_MIN_RATING_FOR_TRAIN = 1
    store = FeedbackStore(config=cfg)

    async def _no_engine():
        return None

    monkeypatch.setattr(store, "initialize", _no_engine)
    record_calls = []

    async def _record(**kwargs):
        record_calls.append(kwargs)
        return True

    monkeypatch.setattr(store, "record", _record)

    ok = _run(
        store.flag_weak_response(
            prompt="soru",
            response="cevap",
            score=3,
            reasoning="eksik",
        )
    )

    assert ok is False
    assert record_calls == []


def test_mark_exported_returns_immediately_when_ids_empty(tmp_path):
    store = _make_store(tmp_path)
    if not _try_init(store):
        pytest.skip("aiosqlite/sqlalchemy kurulu değil")
    _run(store.mark_exported([]))
    _run(store.close())


def _install_training_stubs(monkeypatch, *, include_bitsandbytes=True, dataset_row=None):
    records = {}

    class _Tokenizer:
        def __init__(self):
            self.pad_token = None
            self.eos_token = "<eos>"
            self.saved = None

        def __call__(self, text, truncation, max_length, padding):
            records["tokenized_text"] = text
            records["tokenize_kwargs"] = {
                "truncation": truncation,
                "max_length": max_length,
                "padding": padding,
            }
            return {"input_ids": [1, 2, 3]}

        def save_pretrained(self, out_dir):
            self.saved = out_dir
            records["tokenizer_saved"] = out_dir

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(model_name, trust_remote_code=True):
            records["tokenizer_model"] = model_name
            records["trust_remote_code"] = trust_remote_code
            tok = _Tokenizer()
            records["tokenizer"] = tok
            return tok

    class _Model:
        def __init__(self):
            self.saved = None
            self.trainable_printed = False

        def print_trainable_parameters(self):
            self.trainable_printed = True
            records["trainable_printed"] = True

        def save_pretrained(self, out_dir):
            self.saved = out_dir
            records["model_saved"] = out_dir

    class _AutoModel:
        @staticmethod
        def from_pretrained(model_name, **kwargs):
            records["model_name"] = model_name
            records["model_kwargs"] = kwargs
            model = _Model()
            records["model"] = model
            return model

    class _DataCollator:
        def __init__(self, tokenizer, model=None, padding=True):
            records["collator"] = {"tokenizer": tokenizer, "model": model, "padding": padding}

    class _TrainingArguments:
        def __init__(self, **kwargs):
            records["training_args"] = kwargs
            self.kwargs = kwargs

    class _Trainer:
        def __init__(self, model, args, train_dataset, data_collator):
            records["trainer_init"] = {
                "model": model,
                "args": args,
                "train_dataset": train_dataset,
                "data_collator": data_collator,
            }

        def train(self):
            records["trainer_trained"] = True
            return types.SimpleNamespace(training_loss=0.123, global_step=7)

    class _BitsAndBytesConfig:
        def __init__(self, **kwargs):
            records["bnb_kwargs"] = kwargs
            self.kwargs = kwargs

    sample_row = dataset_row or {"instruction": "Komut", "output": "Yanıt"}

    class _Dataset:
        column_names = list(sample_row.keys())

        def map(self, fn, remove_columns):
            records["remove_columns"] = remove_columns
            mapped = fn(sample_row)
            records["mapped"] = mapped
            return [{"input_ids": mapped["input_ids"], "labels": mapped["labels"]}]

    transformers_mod = types.ModuleType("transformers")
    transformers_mod.AutoTokenizer = _AutoTokenizer
    transformers_mod.AutoModelForCausalLM = _AutoModel
    transformers_mod.TrainingArguments = _TrainingArguments
    transformers_mod.Trainer = _Trainer
    transformers_mod.DataCollatorForSeq2Seq = _DataCollator
    if include_bitsandbytes:
        transformers_mod.BitsAndBytesConfig = _BitsAndBytesConfig

    peft_mod = types.ModuleType("peft")
    peft_mod.TaskType = types.SimpleNamespace(CAUSAL_LM="causal-lm")

    class _LoraConfig:
        def __init__(self, **kwargs):
            records["lora_kwargs"] = kwargs
            self.kwargs = kwargs

    def _get_peft_model(model, lora_config):
        records["peft_wrapped"] = {"model": model, "config": lora_config}
        return model

    peft_mod.LoraConfig = _LoraConfig
    peft_mod.get_peft_model = _get_peft_model

    datasets_mod = types.ModuleType("datasets")
    datasets_mod.load_dataset = lambda *args, **kwargs: records.__setitem__("load_dataset", {"args": args, "kwargs": kwargs}) or _Dataset()

    torch_mod = types.ModuleType("torch")
    torch_mod.float16 = "float16"

    monkeypatch.setitem(sys.modules, "transformers", transformers_mod)
    monkeypatch.setitem(sys.modules, "peft", peft_mod)
    monkeypatch.setitem(sys.modules, "datasets", datasets_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    return records


# ─── DatasetExporter ─────────────────────────────────────────────────────────

class TestDatasetExporter:
    def _store_with_data(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            return None, False
        _run(store.record("Prompt 1", "Response 1", rating=1))
        _run(store.record("Prompt 2", "Response 2", rating=1, correction="Corrected 2"))
        return store, True

    def test_export_jsonl_format(self, tmp_path):
        store, ok = self._store_with_data(tmp_path)
        if not ok:
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        out = str(tmp_path / "out.jsonl")
        exporter = DatasetExporter(store)
        result = _run(exporter.export(out, fmt="jsonl"))
        assert result["count"] == 2
        lines = (tmp_path / "out.jsonl").read_text().strip().splitlines()
        obj = json.loads(lines[0])
        assert "prompt" in obj and "completion" in obj
        _run(store.close())

    def test_export_alpaca_format(self, tmp_path):
        store, ok = self._store_with_data(tmp_path)
        if not ok:
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        out = str(tmp_path / "out_alpaca.jsonl")
        exporter = DatasetExporter(store)
        result = _run(exporter.export(out, fmt="alpaca"))
        assert result["format"] == "alpaca"
        obj = json.loads((tmp_path / "out_alpaca.jsonl").read_text().splitlines()[0])
        assert "instruction" in obj and "output" in obj
        _run(store.close())

    def test_export_sharegpt_format(self, tmp_path):
        store, ok = self._store_with_data(tmp_path)
        if not ok:
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        out = str(tmp_path / "out_sg.jsonl")
        exporter = DatasetExporter(store)
        result = _run(exporter.export(out, fmt="sharegpt"))
        obj = json.loads((tmp_path / "out_sg.jsonl").read_text().splitlines()[0])
        assert "conversations" in obj
        assert obj["conversations"][0]["from"] == "human"
        _run(store.close())

    def test_correction_used_as_completion(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(store.record("Q", "Wrong", rating=1, correction="Correct"))
        out = str(tmp_path / "out.jsonl")
        exporter = DatasetExporter(store)
        _run(exporter.export(out, fmt="jsonl"))
        obj = json.loads((tmp_path / "out.jsonl").read_text().strip())
        assert obj["completion"] == "Correct"
        _run(store.close())

    def test_export_empty_store(self, tmp_path):
        store = _make_store(tmp_path)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        out = str(tmp_path / "empty.jsonl")
        exporter = DatasetExporter(store)
        result = _run(exporter.export(out, fmt="jsonl"))
        assert result["count"] == 0
        _run(store.close())

    def test_unsupported_format_raises(self, tmp_path):
        store = _make_store(tmp_path)
        exporter = DatasetExporter(store)
        with pytest.raises(ValueError, match="Desteklenmeyen format"):
            _run(exporter.export(str(tmp_path / "x.jsonl"), fmt="csv"))

    def test_serialize_sft_examples_rejects_unknown_format_and_skips_blank_rows(self, tmp_path):
        store = _make_store(tmp_path)
        pipeline = ContinuousLearningPipeline(store, config=types.SimpleNamespace())

        with pytest.raises(ValueError, match="Desteklenmeyen continuous learning SFT formatı"):
            pipeline._serialize_sft_examples([], "csv")

        serialized = pipeline._serialize_sft_examples(
            [
                {"instruction": "  ", "output": "cevap"},
                {"instruction": "Soru", "output": "   "},
                {"instruction": "Geçerli", "output": "Yanıt"},
            ],
            "jsonl",
        )

        assert serialized == [{"prompt": "Geçerli", "completion": "Yanıt"}]


# ─── LoRATrainer ─────────────────────────────────────────────────────────────

class TestLoRATrainer:
    def _cfg(self, **kwargs):
        cfg = MagicMock()
        cfg.ENABLE_LORA_TRAINING = kwargs.get("enabled", False)
        cfg.LORA_BASE_MODEL = kwargs.get("base_model", "")
        cfg.LORA_RANK = 8
        cfg.LORA_ALPHA = 16
        cfg.LORA_DROPOUT = 0.05
        cfg.LORA_EPOCHS = 1
        cfg.LORA_BATCH_SIZE = 1
        cfg.LORA_USE_4BIT = False
        cfg.LORA_OUTPUT_DIR = "data/lora_test"
        return cfg

    def test_disabled_returns_reason(self):
        trainer = LoRATrainer(config=self._cfg(enabled=False))
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False
        assert "devre dışı" in result["reason"]

    def test_no_base_model_returns_reason(self):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model=""))
        # peft yoksa ayrı reason döner, ama base_model kontrolü de var
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False

    def test_peft_not_installed_returns_reason(self):
        cfg = self._cfg(enabled=True, base_model="some/model")
        trainer = LoRATrainer(config=cfg)
        # Ortamda peft yoksa graceful degrade
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False

    def test_check_peft_caches_result(self):
        cfg = self._cfg(enabled=True)
        trainer = LoRATrainer(config=cfg)
        first = trainer._check_peft()
        second = trainer._check_peft()
        assert first == second
        assert trainer._peft_available is not None

    def test_check_peft_marks_available_when_all_training_deps_exist(self, monkeypatch):
        cfg = self._cfg(enabled=True)
        trainer = LoRATrainer(config=cfg)
        trainer._peft_available = None

        monkeypatch.setitem(sys.modules, "peft", types.ModuleType("peft"))
        monkeypatch.setitem(sys.modules, "transformers", types.ModuleType("transformers"))
        monkeypatch.setitem(sys.modules, "datasets", types.ModuleType("datasets"))

        assert trainer._check_peft() is True
        assert trainer._peft_available is True


    def test_train_returns_base_model_missing_after_peft_check(self, monkeypatch):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model=""))
        monkeypatch.setattr(trainer, "_check_peft", lambda: True)
        result = trainer.train("some/path.jsonl")
        assert result == {"success": False, "reason": "LORA_BASE_MODEL ayarlanmamış"}

    def test_train_returns_run_training_exception_reason(self, monkeypatch):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model="mock/model"))
        monkeypatch.setattr(trainer, "_check_peft", lambda: True)
        monkeypatch.setattr(trainer, "_run_training", lambda _path: (_ for _ in ()).throw(RuntimeError("trainer boom")))

        result = trainer.train("dataset.jsonl")

        assert result == {"success": False, "reason": "trainer boom"}

    def test_run_training_success_with_mocked_transformers_and_peft(self, monkeypatch, tmp_path):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model="mock/model"))
        trainer.output_dir = str(tmp_path / "adapters")
        trainer.use_4bit = True

        records = _install_training_stubs(monkeypatch, include_bitsandbytes=True)

        result = trainer._run_training("dataset.jsonl")

        assert result["success"] is True
        assert result["train_loss"] == pytest.approx(0.123)
        assert result["steps"] == 7
        assert records["model_name"] == "mock/model"
        assert records["model_kwargs"]["trust_remote_code"] is True
        assert "quantization_config" in records["model_kwargs"]
        assert records["lora_kwargs"]["target_modules"] == ["q_proj", "v_proj"]
        assert records["mapped"]["labels"] == [1, 2, 3]
        assert records["training_args"]["output_dir"] == str(tmp_path / "adapters")
        assert records["trainer_trained"] is True
        assert records["model_saved"] == str(tmp_path / "adapters")
        assert records["tokenizer_saved"] == str(tmp_path / "adapters")

    def test_run_training_supports_sharegpt_rows(self, monkeypatch, tmp_path):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model="mock/model"))
        trainer.output_dir = str(tmp_path / "adapters-sharegpt")
        records = _install_training_stubs(
            monkeypatch,
            include_bitsandbytes=False,
            dataset_row={
                "conversations": [
                    {"from": "human", "value": "İsteği özetle"},
                    {"from": "gpt", "value": "Özet yanıt"},
                ]
            },
        )

        result = trainer._run_training("sharegpt.jsonl")

        assert result["success"] is True
        assert records["tokenized_text"] == "İsteği özetle\n\nÖzet yanıt"
        assert records["remove_columns"] == ["conversations"]

    def test_run_training_without_bitsandbytes_falls_back_to_standard_model_kwargs(self, monkeypatch, tmp_path):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model="mock/model"))
        trainer.output_dir = str(tmp_path / "adapters-no-bnb")
        trainer.use_4bit = True

        records = _install_training_stubs(monkeypatch, include_bitsandbytes=False)

        result = trainer._run_training("dataset.jsonl")

        assert result["success"] is True
        assert records["model_kwargs"] == {"trust_remote_code": True}


class TestContinuousLearningPipeline:
    def _cfg(self, tmp_path, **overrides):
        cfg = MagicMock()
        cfg.ENABLE_ACTIVE_LEARNING = True
        cfg.AL_MIN_RATING_FOR_TRAIN = 1
        cfg.ENABLE_CONTINUOUS_LEARNING = overrides.get("enabled", True)
        cfg.CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = overrides.get("min_sft", 2)
        cfg.CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = overrides.get("min_preference", 1)
        cfg.CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = overrides.get("max_pending", 100)
        cfg.CONTINUOUS_LEARNING_COOLDOWN_SECONDS = overrides.get("cooldown", 0)
        cfg.CONTINUOUS_LEARNING_OUTPUT_DIR = str(tmp_path / "cl")
        cfg.CONTINUOUS_LEARNING_SFT_FORMAT = overrides.get("sft_format", "alpaca")
        cfg.ENABLE_LORA_TRAINING = overrides.get("trainer_enabled", False)
        cfg.LORA_BASE_MODEL = "mock/model"
        cfg.LORA_RANK = 8
        cfg.LORA_ALPHA = 16
        cfg.LORA_DROPOUT = 0.05
        cfg.LORA_EPOCHS = 1
        cfg.LORA_BATCH_SIZE = 1
        cfg.LORA_USE_4BIT = False
        cfg.LORA_OUTPUT_DIR = str(tmp_path / "lora")
        return cfg

    def test_build_dataset_bundle_exports_sft_and_preference_sets(self, tmp_path):
        cfg = self._cfg(tmp_path)
        store = FeedbackStore(database_url=f"sqlite+aiosqlite:///{tmp_path/'cl.db'}", config=cfg)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")

        _run(store.record("Prompt 1", "Yanıt 1", rating=1, correction="İyileştirilmiş 1"))
        _run(store.record("Prompt 2", "Yanıt 2", rating=1))
        _run(
            store.record(
                "Prompt 3",
                "Zayıf yanıt",
                rating=-1,
                correction="Judge gerekçesi",
                tags=["judge:auto", "weak_response", "judge_reasoning"],
            )
        )

        pipeline = ContinuousLearningPipeline(store, config=cfg)
        manifest = _run(pipeline.build_dataset_bundle())

        assert manifest["counts"]["signals"] == 3
        assert manifest["counts"]["sft_examples"] == 2
        assert manifest["counts"]["preference_examples"] == 1
        assert manifest["counts"]["triage_only"] == 1

        sft_lines = Path(manifest["sft_path"]).read_text(encoding="utf-8").strip().splitlines()
        pref_lines = Path(manifest["preference_path"]).read_text(encoding="utf-8").strip().splitlines()
        assert len(sft_lines) == 2
        assert len(pref_lines) == 1
        assert json.loads(pref_lines[0])["chosen"] == "İyileştirilmiş 1"
        _run(store.close())

    def test_build_dataset_bundle_respects_sharegpt_sft_format(self, tmp_path):
        cfg = self._cfg(tmp_path, sft_format="sharegpt")
        store = FeedbackStore(database_url=f"sqlite+aiosqlite:///{tmp_path/'cl-sharegpt.db'}", config=cfg)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")

        _run(store.record("Prompt SG", "Yanıt SG", rating=1, correction="Düzeltilmiş SG"))
        pipeline = ContinuousLearningPipeline(store, config=cfg)
        manifest = _run(pipeline.build_dataset_bundle())

        sft_row = json.loads(Path(manifest["sft_path"]).read_text(encoding="utf-8").strip())
        assert manifest["sft_format"] == "sharegpt"
        assert sft_row == {
            "conversations": [
                {"from": "human", "value": "Prompt SG"},
                {"from": "gpt", "value": "Düzeltilmiş SG"},
            ]
        }
        _run(store.close())

    def test_build_dataset_bundle_respects_jsonl_sft_format(self, tmp_path):
        cfg = self._cfg(tmp_path, sft_format="jsonl")
        store = FeedbackStore(database_url=f"sqlite+aiosqlite:///{tmp_path/'cl-jsonl.db'}", config=cfg)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")

        _run(store.record("Prompt J", "Yanıt J", rating=1))
        pipeline = ContinuousLearningPipeline(store, config=cfg)
        manifest = _run(pipeline.build_dataset_bundle())

        sft_row = json.loads(Path(manifest["sft_path"]).read_text(encoding="utf-8").strip())
        assert sft_row == {"prompt": "Prompt J", "completion": "Yanıt J"}
        _run(store.close())

    def test_run_cycle_triggers_trainer_when_threshold_met(self, tmp_path):
        cfg = self._cfg(tmp_path, trainer_enabled=True, min_sft=1)
        store = FeedbackStore(database_url=f"sqlite+aiosqlite:///{tmp_path/'cl-train.db'}", config=cfg)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")

        _run(store.record("Prompt", "Yanıt", rating=1, correction="Daha iyi yanıt"))
        trainer = MagicMock()
        trainer.enabled = True
        trainer.train.return_value = {"success": True, "output_dir": str(tmp_path / "adapter")}

        pipeline = ContinuousLearningPipeline(store, config=cfg, trainer=trainer)
        result = _run(pipeline.run_cycle(reason="test"))

        assert result["success"] is True
        assert result["scheduled"] is True
        trainer.train.assert_called_once()
        assert result["training_result"]["success"] is True
        _run(store.close())

    def test_build_sft_examples_skips_below_threshold_and_judge_reasoning_rows(self, tmp_path):
        cfg = self._cfg(tmp_path)
        store = MagicMock()
        store.min_rating_for_train = 2

        pipeline = ContinuousLearningPipeline(store, config=cfg)
        examples = pipeline._build_sft_examples(
            [
                {"id": 1, "prompt": "P1", "response": "R1", "rating": 1, "correction": ""},
                {"id": 2, "prompt": "P2", "response": "R2", "rating": 2, "correction": ""},
                {
                    "id": 3,
                    "prompt": "P3",
                    "response": "R3",
                    "rating": 5,
                    "correction": "Reasoning",
                    "tags": ["judge:auto", "weak_response", "judge_reasoning"],
                },
                {"id": 4, "prompt": "P4", "response": "R4", "rating": 3, "correction": "C4"},
            ]
        )

        assert examples == [
            {
                "instruction": "P2",
                "input": "",
                "output": "R2",
                "source": "response",
                "feedback_id": 2,
            },
            {
                "instruction": "P4",
                "input": "",
                "output": "C4",
                "source": "correction",
                "feedback_id": 4,
            },
        ]

    def test_run_cycle_schedules_when_preference_threshold_met_without_training(self, tmp_path):
        cfg = self._cfg(tmp_path, min_sft=3, min_preference=1, trainer_enabled=False)
        store = FeedbackStore(database_url=f"sqlite+aiosqlite:///{tmp_path/'cl-pref.db'}", config=cfg)
        if not _try_init(store):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")

        _run(store.record("Prompt", "Yanıt", rating=-1, correction="Düzeltilmiş yanıt"))

        trainer = MagicMock()
        trainer.enabled = False
        pipeline = ContinuousLearningPipeline(store, config=cfg, trainer=trainer)
        result = _run(pipeline.run_cycle(reason="preference-only"))

        assert result["success"] is True
        assert result["scheduled"] is True
        assert result["manifest"]["counts"]["sft_examples"] == 0
        assert result["manifest"]["counts"]["preference_examples"] == 1
        assert result["training_result"]["reason"] == "trainer_disabled_or_insufficient_sft"
        trainer.train.assert_not_called()
        _run(store.close())

    def test_schedule_cycle_swallows_background_runtime_errors(self, tmp_path):
        cfg = self._cfg(tmp_path)

        async def _exercise():
            pipeline = ContinuousLearningPipeline(MagicMock(), config=cfg, trainer=MagicMock())

            async def _boom(*, reason):
                raise RuntimeError(f"duplicate/conflict: {reason}")

            pipeline.run_cycle = _boom

            assert pipeline.schedule_cycle(reason="judge:auto_feedback") is True
            await asyncio.sleep(0)

        _run(_exercise())

    def test_schedule_continuous_learning_cycle_uses_singleton(self, monkeypatch):
        calls = []

        class _Pipeline:
            def schedule_cycle(self, *, reason):
                calls.append(reason)
                return True

        from core import active_learning as al_mod

        monkeypatch.setattr(al_mod, "get_continuous_learning_pipeline", lambda config=None: _Pipeline())

        assert schedule_continuous_learning_cycle(reason="judge:auto_feedback") is True
        assert calls == ["judge:auto_feedback"]


# ─── Yardımcı: _chunked ──────────────────────────────────────────────────────

def test_chunked_splits_correctly():
    lst = list(range(10))
    chunks = list(_chunked(lst, 3))
    assert chunks == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]


def test_chunked_empty():
    assert list(_chunked([], 5)) == []


def test_chunked_exact_fit():
    assert list(_chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


# ─── Singleton get_feedback_store ────────────────────────────────────────────

def test_get_feedback_store_returns_instance():
    import core.active_learning as al_mod
    original = al_mod._feedback_store
    al_mod._feedback_store = None
    try:
        store = get_feedback_store()
        assert isinstance(store, FeedbackStore)
        store2 = get_feedback_store()
        assert store is store2
    finally:
        al_mod._feedback_store = original


def test_get_continuous_learning_pipeline_returns_instance(monkeypatch):
    import core.active_learning as al_mod

    original_store = al_mod._feedback_store
    original_pipeline = al_mod._continuous_learning_pipeline
    al_mod._feedback_store = None
    al_mod._continuous_learning_pipeline = None
    try:
        pipeline = get_continuous_learning_pipeline()
        assert isinstance(pipeline, ContinuousLearningPipeline)
        assert get_continuous_learning_pipeline() is pipeline
    finally:
        al_mod._feedback_store = original_store
        al_mod._continuous_learning_pipeline = original_pipeline


def test_module_level_flag_weak_response_uses_singleton(monkeypatch):
    calls = []

    class _Store:
        async def flag_weak_response(self, **kwargs):
            calls.append(kwargs)
            return True

    from core import active_learning
    monkeypatch.setattr(active_learning, "get_feedback_store", lambda config=None: _Store())

    ok = _run(
        flag_weak_response(
            prompt="prompt",
            response="response",
            score=5,
            reasoning="neden",
        )
    )

    assert ok is True
    assert calls[0]["score"] == 5


def test_feedback_store_get_pending_signals_handles_disabled_and_invalid_tags(tmp_path):
    import core.active_learning as active_learning_module

    disabled_cfg = MagicMock()
    disabled_cfg.ENABLE_ACTIVE_LEARNING = False
    disabled_cfg.AL_MIN_RATING_FOR_TRAIN = 1
    disabled_store = FeedbackStore(config=disabled_cfg)
    assert _run(disabled_store.get_pending_signals()) == []

    enabled_cfg = MagicMock()
    enabled_cfg.ENABLE_ACTIVE_LEARNING = True
    enabled_cfg.AL_MIN_RATING_FOR_TRAIN = 1
    store = FeedbackStore(config=enabled_cfg)

    class _Row:
        def __init__(self, mapping):
            self._mapping = mapping

    class _Result:
        def fetchall(self):
            return [
                _Row({"id": 1, "prompt": "P1", "response": "R1", "tags": '["judge:auto", "weak_response"]'}),
                _Row({"id": 2, "prompt": "P2", "response": "R2", "tags": "{broken-json"}),
            ]

    class _Conn:
        async def execute(self, *_args, **_kwargs):
            return _Result()

    class _Ctx:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    store._engine = types.SimpleNamespace(connect=lambda: _Ctx())
    active_learning_module.sql_text = lambda sql: sql
    rows = _run(store.get_pending_signals())

    assert rows[0]["tags"] == ["judge:auto", "weak_response"]
    assert rows[1]["tags"] == []


def test_continuous_learning_pipeline_normalize_and_example_filters(tmp_path):
    cfg = TestContinuousLearningPipeline()._cfg(tmp_path)
    store = MagicMock()
    store.min_rating_for_train = 1
    pipeline = ContinuousLearningPipeline(store, config=cfg)

    assert pipeline._normalize_tags('["a", "b"]') == ["a", "b"]
    assert pipeline._normalize_tags("{bad json") == []

    sft_examples = pipeline._build_sft_examples(
        [
            {"id": 1, "prompt": "", "response": "R1", "rating": 2, "correction": ""},
            {"id": 2, "prompt": "P2", "response": "", "rating": 2, "correction": ""},
            {"id": 3, "prompt": "P3", "response": "R3", "rating": 2, "correction": ""},
        ]
    )
    assert sft_examples == [
        {
            "instruction": "P3",
            "input": "",
            "output": "R3",
            "source": "response",
            "feedback_id": 3,
        }
    ]

    preference_examples = pipeline._build_preference_examples(
        [
            {"id": 10, "prompt": "P", "response": "same", "correction": "same", "rating": 1},
            {"id": 11, "prompt": "P2", "response": "bad", "correction": "good", "rating": 0},
        ]
    )
    assert preference_examples == []


def test_continuous_learning_run_cycle_disabled_cooldown_and_insufficient_signals(tmp_path, monkeypatch):
    disabled_cfg = TestContinuousLearningPipeline()._cfg(tmp_path, enabled=False)
    disabled = ContinuousLearningPipeline(MagicMock(), config=disabled_cfg, trainer=MagicMock())
    disabled_result = _run(disabled.run_cycle(reason="manual"))
    assert disabled_result == {
        "success": False,
        "scheduled": False,
        "reason": "continuous_learning_disabled",
    }

    cfg = TestContinuousLearningPipeline()._cfg(tmp_path, cooldown=60, min_sft=5, min_preference=5)
    trainer = MagicMock()
    trainer.enabled = False
    pipeline = ContinuousLearningPipeline(MagicMock(), config=cfg, trainer=trainer)

    pipeline._last_run_at = 100.0
    monkeypatch.setattr("core.active_learning.time.time", lambda: 120.0)
    cooldown_result = _run(pipeline.run_cycle(reason="cooldown"))
    assert cooldown_result["reason"] == "cooldown_active"
    assert cooldown_result["retry_after"] == 40

    monkeypatch.setattr("core.active_learning.time.time", lambda: 500.0)

    async def _bundle():
        return {
            "counts": {"sft_examples": 1, "preference_examples": 1},
            "sft_path": str(tmp_path / "bundle.jsonl"),
        }

    pipeline.build_dataset_bundle = _bundle
    insufficient = _run(pipeline.run_cycle(reason="low-signal"))
    assert insufficient["reason"] == "insufficient_signals"
    assert insufficient["trigger_reason"] == "low-signal"
    assert pipeline._last_run_at == 500.0


def test_continuous_learning_schedule_cycle_handles_missing_loop_and_cancelled_error(tmp_path, monkeypatch):
    cfg = TestContinuousLearningPipeline()._cfg(tmp_path)
    pipeline = ContinuousLearningPipeline(MagicMock(), config=cfg, trainer=MagicMock())

    monkeypatch.setattr("core.active_learning.asyncio.get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    assert pipeline.schedule_cycle(reason="background") is False

    async def _exercise_cancelled():
        captured = {}

        class _Loop:
            def create_task(self, coro, name=None):
                captured["coro"] = coro
                captured["name"] = name
                return "task"

        monkeypatch.setattr("core.active_learning.asyncio.get_running_loop", lambda: _Loop())

        async def _cancel(*, reason):
            raise asyncio.CancelledError()

        pipeline.run_cycle = _cancel
        assert pipeline.schedule_cycle(reason="judge:auto_feedback") is True
        assert captured["name"] == "sidar_continuous_learning"
        with pytest.raises(asyncio.CancelledError):
            await captured["coro"]

    _run(_exercise_cancelled())