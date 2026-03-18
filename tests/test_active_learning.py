"""Testler: Active Learning + LoRA/QLoRA Fine-tuning Döngüsü (Özellik 8)"""
from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


from core.active_learning import (
    FeedbackStore,
    DatasetExporter,
    LoRATrainer,
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
