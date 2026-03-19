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
    FeedbackStore,
    DatasetExporter,
    LoRATrainer,
    flag_weak_response,
    get_feedback_store,
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


def _install_training_stubs(monkeypatch, *, include_bitsandbytes=True):
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

    class _Dataset:
        column_names = ["instruction", "output"]

        def map(self, fn, remove_columns):
            records["remove_columns"] = remove_columns
            mapped = fn({"instruction": "Komut", "output": "Yanıt"})
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

    def test_run_training_without_bitsandbytes_falls_back_to_standard_model_kwargs(self, monkeypatch, tmp_path):
        trainer = LoRATrainer(config=self._cfg(enabled=True, base_model="mock/model"))
        trainer.output_dir = str(tmp_path / "adapters-no-bnb")
        trainer.use_4bit = True

        records = _install_training_stubs(monkeypatch, include_bitsandbytes=False)

        result = trainer._run_training("dataset.jsonl")

        assert result["success"] is True
        assert records["model_kwargs"] == {"trust_remote_code": True}


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
