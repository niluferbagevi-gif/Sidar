"""
core/active_learning.py için birim testleri.
FeedbackStore (disabled path, config), DatasetExporter format sabitleri,
ContinuousLearningPipeline static yardımcıları kapsar.
SQLAlchemy gerektiren entegrasyon testleri skip'lenebilir.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest


def _get_al():
    if "core.active_learning" in sys.modules:
        del sys.modules["core.active_learning"]
    import core.active_learning as al
    return al


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════
# FeedbackStore — init
# ══════════════════════════════════════════════════════════════

class TestFeedbackStoreInit:
    def test_enabled_default_true(self):
        al = _get_al()
        fs = al.FeedbackStore()
        assert fs.enabled is True

    def test_enabled_false_via_config(self):
        al = _get_al()

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        fs = al.FeedbackStore(config=_Cfg())
        assert fs.enabled is False

    def test_min_rating_default(self):
        al = _get_al()
        fs = al.FeedbackStore()
        assert fs.min_rating_for_train == 1

    def test_min_rating_via_config(self):
        al = _get_al()

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = True
            AL_MIN_RATING_FOR_TRAIN = 0

        fs = al.FeedbackStore(config=_Cfg())
        assert fs.min_rating_for_train == 0

    def test_engine_none_initially(self):
        al = _get_al()
        fs = al.FeedbackStore()
        assert fs._engine is None


# ══════════════════════════════════════════════════════════════
# FeedbackStore — disabled paths
# ══════════════════════════════════════════════════════════════

class TestFeedbackStoreDisabled:
    def _make_disabled(self):
        al = _get_al()

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        return al.FeedbackStore(config=_Cfg())

    def test_initialize_noop_when_disabled(self):
        fs = self._make_disabled()
        _run(fs.initialize())
        assert fs._engine is None

    def test_record_returns_false_when_disabled(self):
        fs = self._make_disabled()
        result = _run(fs.record("prompt", "response"))
        assert result is False

    def test_record_returns_false_no_engine(self):
        al = _get_al()
        fs = al.FeedbackStore()  # enabled but no engine
        result = _run(fs.record("prompt", "response"))
        assert result is False

    def test_get_pending_export_returns_empty_when_disabled(self):
        fs = self._make_disabled()
        result = _run(fs.get_pending_export())
        assert result == []

    def test_get_pending_export_returns_empty_no_engine(self):
        al = _get_al()
        fs = al.FeedbackStore()
        result = _run(fs.get_pending_export())
        assert result == []

    def test_get_pending_signals_returns_empty_when_disabled(self):
        fs = self._make_disabled()
        result = _run(fs.get_pending_signals())
        assert result == []

    def test_stats_returns_empty_when_disabled(self):
        fs = self._make_disabled()
        result = _run(fs.stats())
        assert result == {}

    def test_stats_returns_empty_no_engine(self):
        al = _get_al()
        fs = al.FeedbackStore()
        result = _run(fs.stats())
        assert result == {}

    def test_flag_weak_response_returns_false_when_disabled(self):
        fs = self._make_disabled()
        result = _run(fs.flag_weak_response("prompt", "response", score=3, reasoning="bad"))
        assert result is False

    def test_close_noop_no_engine(self):
        al = _get_al()
        fs = al.FeedbackStore()
        _run(fs.close())  # should not raise
        assert fs._engine is None


class TestFeedbackStoreFlagWeakResponse:
    def test_flag_weak_response_adds_reasoning_tag_and_clamps_score(self, monkeypatch):
        al = _get_al()
        fs = al.FeedbackStore()
        fs._engine = object()  # initialize çağrısını atlamak için
        captured = {}

        async def _fake_record(**kwargs):
            captured.update(kwargs)
            return True

        monkeypatch.setattr(fs, "record", _fake_record)
        ok = _run(
            fs.flag_weak_response(
                prompt="p",
                response="r",
                score=99,
                reasoning="neden",
                tags=["manual"],
            )
        )
        assert ok is True
        assert "manual" in captured["tags"]
        assert "judge_reasoning" in captured["tags"]
        assert "score:10" in captured["tags"]

    def test_flag_weak_response_without_reasoning_skips_reasoning_tag(self, monkeypatch):
        al = _get_al()
        fs = al.FeedbackStore()
        fs._engine = object()
        captured = {}

        async def _fake_record(**kwargs):
            captured.update(kwargs)
            return True

        monkeypatch.setattr(fs, "record", _fake_record)
        ok = _run(fs.flag_weak_response(prompt="p", response="r", score=0, reasoning=""))
        assert ok is True
        assert "judge_reasoning" not in captured["tags"]
        assert "score:1" in captured["tags"]

    def test_flag_weak_response_returns_false_when_engine_still_missing_after_initialize(self, monkeypatch):
        al = _get_al()
        fs = al.FeedbackStore()
        fs._engine = None

        async def _fake_initialize():
            fs._engine = None

        monkeypatch.setattr(fs, "initialize", _fake_initialize)
        ok = _run(fs.flag_weak_response(prompt="p", response="r", score=4, reasoning="neden"))
        assert ok is False


# ══════════════════════════════════════════════════════════════
# DatasetExporter
# ══════════════════════════════════════════════════════════════

class TestDatasetExporter:
    def test_supported_formats(self):
        al = _get_al()
        assert "jsonl" in al.DatasetExporter.SUPPORTED_FORMATS
        assert "alpaca" in al.DatasetExporter.SUPPORTED_FORMATS
        assert "sharegpt" in al.DatasetExporter.SUPPORTED_FORMATS

    def test_unsupported_format_raises(self):
        al = _get_al()

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        fs = al.FeedbackStore(config=_Cfg())
        exporter = al.DatasetExporter(fs)
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            _run(exporter.export("/tmp/out.txt", fmt="parquet"))

    def test_export_empty_store_returns_zero_count(self):
        al = _get_al()

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        fs = al.FeedbackStore(config=_Cfg())
        exporter = al.DatasetExporter(fs)
        result = _run(exporter.export("/tmp/test_export.jsonl", fmt="jsonl"))
        assert result["count"] == 0
        assert result["format"] == "jsonl"

    def test_export_sharegpt_writes_expected_schema_and_marks_done(self, tmp_path):
        al = _get_al()
        marked_ids = []

        class _Store:
            async def get_pending_export(self, min_rating=1):
                return [
                    {"id": 10, "prompt": "Soru", "response": "Yanıt", "correction": ""},
                    {"id": 11, "prompt": "Soru2", "response": "Eski", "correction": "Yeni"},
                ]

            async def mark_exported(self, ids):
                marked_ids.extend(ids)

        out = tmp_path / "dataset.sharegpt.jsonl"
        exporter = al.DatasetExporter(_Store())

        result = _run(exporter.export(str(out), fmt="sharegpt", mark_done=True))

        assert result["count"] == 2
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        payload = json.loads(lines[1])
        assert payload["conversations"][0]["from"] == "human"
        assert payload["conversations"][1]["value"] == "Yeni"
        assert marked_ids == [10, 11]


# ══════════════════════════════════════════════════════════════
# ContinuousLearningPipeline — static helpers
# ══════════════════════════════════════════════════════════════

class TestNormalizeTags:
    def _norm(self, tags):
        al = _get_al()
        return al.ContinuousLearningPipeline._normalize_tags(tags)

    def test_list_of_strings_returned_as_is(self):
        result = self._norm(["tag1", "tag2"])
        assert result == ["tag1", "tag2"]

    def test_empty_list_returns_empty(self):
        assert self._norm([]) == []

    def test_json_string_parsed(self):
        result = self._norm('["a", "b"]')
        assert result == ["a", "b"]

    def test_invalid_json_string_returns_empty(self):
        result = self._norm("not json")
        assert result == []

    def test_non_string_non_list_returns_empty(self):
        result = self._norm(42)
        assert result == []

    def test_empty_string_tags_filtered(self):
        result = self._norm(["good", "  ", "also_good"])
        assert "  " not in result
        assert "good" in result

    def test_json_list_with_empty_strings_filtered(self):
        result = self._norm('["ok", "", "fine"]')
        assert "" not in result


class TestFeedbackStorePendingSignalsTagParsing:
    def test_get_pending_signals_invalid_json_tags_falls_back_to_empty_list(self):
        al = _get_al()
        if not hasattr(al, "sql_text"):
            al.sql_text = lambda value: value
        fs = al.FeedbackStore()

        class _Result:
            @staticmethod
            def fetchall():
                return [types.SimpleNamespace(_mapping={"id": 1, "tags": "{invalid}"})]

        class _Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def execute(self, *_args, **_kwargs):
                return _Result()

        class _Engine:
            def connect(self):
                return _Conn()

        fs._engine = _Engine()
        rows = _run(fs.get_pending_signals())
        assert rows[0]["tags"] == []


class TestIsJudgeReasoningSignal:
    def _check(self, row):
        al = _get_al()
        return al.ContinuousLearningPipeline._is_judge_reasoning_signal(row)

    def test_both_required_tags_detected(self):
        assert self._check({"tags": '["judge_reasoning", "weak_response"]'}) is True


class TestContinuousLearningPipelineBundle:
    def _check(self, row):
        al = _get_al()
        return al.ContinuousLearningPipeline._is_judge_reasoning_signal(row)

    def test_build_dataset_bundle_generates_manifest_and_files(self, tmp_path):
        al = _get_al()

        class _Store:
            min_rating_for_train = 1

            async def get_pending_signals(self, limit=100):
                return [
                    {
                        "id": 1,
                        "prompt": "p1",
                        "response": "r1",
                        "correction": "c1",
                        "rating": 1,
                        "tags": "[]",
                    },
                    {
                        "id": 2,
                        "prompt": "p2",
                        "response": "r2",
                        "correction": "",
                        "rating": 1,
                        "tags": "[]",
                    },
                ]

        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = True
            CONTINUOUS_LEARNING_OUTPUT_DIR = str(tmp_path / "bundles")
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 1
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 1
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 50
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"

        pipeline = al.ContinuousLearningPipeline(_Store(), config=_Cfg(), trainer=object())
        manifest = _run(pipeline.build_dataset_bundle())

        assert manifest["counts"]["signals"] == 2
        assert manifest["counts"]["sft_examples"] >= 1
        assert manifest["counts"]["preference_examples"] == 1
        assert Path(manifest["sft_path"]).exists()
        assert Path(manifest["preference_path"]).exists()

    def test_only_judge_reasoning_returns_false(self):
        assert self._check({"tags": '["judge_reasoning"]'}) is False

    def test_only_weak_response_returns_false(self):
        assert self._check({"tags": '["weak_response"]'}) is False

    def test_no_judge_tags_returns_false(self):
        assert self._check({"tags": '["user_tag"]'}) is False

    def test_empty_tags_returns_false(self):
        assert self._check({"tags": "[]"}) is False

    def test_missing_tags_returns_false(self):
        assert self._check({}) is False


# ══════════════════════════════════════════════════════════════
# SQLite integration (if sqlalchemy + aiosqlite available)
# ══════════════════════════════════════════════════════════════

try:
    import sqlalchemy  # noqa: F401
    import aiosqlite  # noqa: F401
    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False


@pytest.mark.skipif(not _SA_AVAILABLE, reason="sqlalchemy+aiosqlite required")
class TestFeedbackStoreSQLite:
    def _make(self):
        al = _get_al()
        return al.FeedbackStore("sqlite+aiosqlite:///:memory:")

    def test_initialize_creates_engine(self):
        async def _test():
            fs = self._make()
            await fs.initialize()
            assert fs._engine is not None
            await fs.close()
        asyncio.run(_test())

    def test_record_and_get_pending(self):
        async def _test():
            fs = self._make()
            await fs.initialize()
            ok = await fs.record("hello", "world", rating=1)
            assert ok is True
            rows = await fs.get_pending_export(min_rating=1)
            assert len(rows) == 1
            assert rows[0]["prompt"] == "hello"
            await fs.close()
        asyncio.run(_test())

    def test_negative_rating_not_in_pending_export(self):
        async def _test():
            fs = self._make()
            await fs.initialize()
            await fs.record("q", "a", rating=-1)
            rows = await fs.get_pending_export(min_rating=1)
            assert len(rows) == 0
            await fs.close()
        asyncio.run(_test())

    def test_stats_counts(self):
        async def _test():
            fs = self._make()
            await fs.initialize()
            await fs.record("q1", "a1", rating=1)
            await fs.record("q2", "a2", rating=-1)
            stats = await fs.stats()
            assert stats["total"] == 2
            assert stats["positive"] == 1
            assert stats["negative"] == 1
            await fs.close()
        asyncio.run(_test())

    def test_close_disposes_engine(self):
        async def _test():
            fs = self._make()
            await fs.initialize()
            await fs.close()
            assert fs._engine is None
        asyncio.run(_test())


class TestContinuousLearningPipelineLoop:
    def _make_pipeline(self, rows, *, enabled=True, trainer_enabled=False):
        al = _get_al()

        class _Store:
            min_rating_for_train = 1

            async def get_pending_signals(self, limit=10000):
                return list(rows)

        class _Trainer:
            enabled = trainer_enabled

            def train(self, dataset_path):
                return {"success": True, "dataset_path": dataset_path}

        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = enabled
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl-bundle"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 1
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 1
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 999
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"

        return al.ContinuousLearningPipeline(_Store(), trainer=_Trainer(), config=_Cfg())

    def test_run_cycle_disabled_returns_guard_reason(self):
        pipeline = self._make_pipeline([], enabled=False)
        result = _run(pipeline.run_cycle(reason="test"))
        assert result["success"] is False
        assert result["reason"] == "continuous_learning_disabled"

    def test_run_cycle_enters_cooldown_branch(self):
        pipeline = self._make_pipeline([], enabled=True)
        pipeline._last_run_at = __import__("time").time()
        result = _run(pipeline.run_cycle(reason="cooldown"))
        assert result["success"] is False
        assert result["reason"] == "cooldown_active"

    def test_run_cycle_insufficient_signals_branch(self):
        rows = [{"id": 1, "prompt": "p", "response": "r", "correction": "", "rating": 0, "tags": "[]"}]
        pipeline = self._make_pipeline(rows, enabled=True)
        pipeline.cooldown_seconds = 0
        result = _run(pipeline.run_cycle(reason="insufficient"))
        assert result["success"] is False
        assert result["reason"] == "insufficient_signals"

    def test_build_dataset_bundle_creates_sft_and_preference_counts(self, tmp_path):
        rows = [
            {"id": 10, "prompt": "p1", "response": "r1", "correction": "c1", "rating": 1, "tags": "[]"},
            {"id": 11, "prompt": "p2", "response": "r2", "correction": "c2", "rating": -1, "tags": "[]"},
        ]
        pipeline = self._make_pipeline(rows, enabled=True, trainer_enabled=True)
        pipeline.cooldown_seconds = 0
        manifest = _run(pipeline.build_dataset_bundle(output_dir=str(tmp_path)))
        assert manifest["counts"]["signals"] == 2
        assert manifest["counts"]["sft_examples"] >= 1
        assert manifest["counts"]["preference_examples"] >= 1

    def test_schedule_cycle_swallows_run_cycle_exception_in_background_task(self):
        pipeline = self._make_pipeline([], enabled=True)

        async def _boom(*, reason="background"):
            raise RuntimeError("background cycle failed")

        pipeline.run_cycle = _boom  # type: ignore[assignment]

        async def _scenario():
            scheduled = pipeline.schedule_cycle(reason="test-exception")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return scheduled

        assert _run(_scenario()) is True

# ===== MERGED FROM tests/test_core_active_learning_extra.py =====

import asyncio
import json
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub sqlalchemy so sql_text is available (needed for SA code paths)
# ---------------------------------------------------------------------------
if "sqlalchemy" not in sys.modules:
    _sa = types.ModuleType("sqlalchemy")
    _sa.text = lambda s: s  # sql_text stub - just return the string
    sys.modules["sqlalchemy"] = _sa

if "sqlalchemy.ext" not in sys.modules:
    _sa_ext = types.ModuleType("sqlalchemy.ext")
    sys.modules["sqlalchemy.ext"] = _sa_ext
    sys.modules["sqlalchemy"].ext = _sa_ext

if "sqlalchemy.ext.asyncio" not in sys.modules:
    _sa_ext_async = types.ModuleType("sqlalchemy.ext.asyncio")
    _sa_ext_async.create_async_engine = MagicMock(return_value=MagicMock())
    sys.modules["sqlalchemy.ext.asyncio"] = _sa_ext_async
    sys.modules["sqlalchemy.ext"].asyncio = _sa_ext_async


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _get_al():
    """Fresh import of core.active_learning after clearing module cache."""
    for key in list(sys.modules.keys()):
        if key in ("core.active_learning",):
            del sys.modules[key]
    import core.active_learning as al
    return al


def _make_enabled_store(al_mod):
    """Return an enabled FeedbackStore with a fake engine."""
    fs = al_mod.FeedbackStore()
    assert fs.enabled is True
    return fs


def _fake_engine():
    """Build a minimal async-engine mock."""
    engine = MagicMock()
    engine.dispose = AsyncMock()

    # context-manager helpers
    class _FakeConn:
        async def execute(self, *a, **kw):
            row = MagicMock()
            row._mapping = {
                "id": 1, "prompt": "p", "response": "r",
                "correction": "", "rating": 1,
                "user_id": "u", "provider": "", "model": "",
                "session_id": "s", "tags": "[]", "created_at": time.time(),
            }
            result = MagicMock()
            result.fetchall.return_value = [row]
            result.scalar.return_value = 5
            return result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    engine.connect = lambda: _FakeConn()
    engine.begin = lambda: _FakeConn()
    return engine


# ===========================================================================
# FeedbackStore — initialize (SA available path) - lines 85-91
# ===========================================================================

class Extra_TestFeedbackStoreInitialize:
    def test_initialize_noop_when_sa_not_available(self):
        al = _get_al()
        al._SA_AVAILABLE = False
        fs = al.FeedbackStore()
        _run(fs.initialize())
        assert fs._engine is None

    def test_initialize_creates_engine_when_sa_available(self):
        al = _get_al()

        mock_engine = MagicMock()

        class _FakeConn:
            async def execute(self, *a, **kw):
                return MagicMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        mock_engine.begin = lambda: _FakeConn()

        def _fake_create_engine(url, **kw):
            return mock_engine

        al._SA_AVAILABLE = True
        al.create_async_engine = _fake_create_engine

        fs = al.FeedbackStore()
        _run(fs.initialize())
        assert fs._engine is mock_engine

    def test_initialize_disabled_skips_even_if_sa_available(self):
        al = _get_al()
        al._SA_AVAILABLE = True

        class _Cfg:
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        fs = al.FeedbackStore(config=_Cfg())
        _run(fs.initialize())
        assert fs._engine is None


# ===========================================================================
# FeedbackStore — record (lines 108-126)
# ===========================================================================

class Extra_TestFeedbackStoreRecord:
    def test_record_returns_true_with_fake_engine(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        result = _run(fs.record(
            prompt="hello", response="world", rating=1,
            user_id="u1", session_id="s1", provider="openai",
            model="gpt-4", tags=["test"],
        ))
        assert result is True

    def test_record_with_correction(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        result = _run(fs.record(
            prompt="q", response="a", rating=1, correction="better answer",
        ))
        assert result is True

    def test_record_tags_default_empty(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        # No tags=None explicitly — should not raise
        result = _run(fs.record(prompt="p", response="r"))
        assert result is True


# ===========================================================================
# FeedbackStore — get_pending_export (lines 176-187)
# ===========================================================================

class Extra_TestFeedbackStoreGetPendingExport:
    def test_get_pending_export_with_engine(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        rows = _run(fs.get_pending_export(min_rating=0, limit=10))
        assert isinstance(rows, list)

    def test_get_pending_export_uses_store_threshold_when_none(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs.min_rating_for_train = 2
        fs._engine = _fake_engine()
        # Should not raise
        rows = _run(fs.get_pending_export())
        assert isinstance(rows, list)


# ===========================================================================
# FeedbackStore — mark_exported (lines 215-226)
# ===========================================================================

class Extra_TestMarkExported:
    def test_mark_exported_empty_list_noop(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        _run(fs.mark_exported([]))  # should not raise

    def test_mark_exported_no_engine_noop(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = None
        _run(fs.mark_exported([1, 2, 3]))  # should not raise

    def test_mark_exported_with_ids(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        _run(fs.mark_exported([1, 2, 3]))  # should not raise


# ===========================================================================
# FeedbackStore — stats (lines 238-243)
# ===========================================================================

class Extra_TestFeedbackStoreStats:
    def test_stats_with_engine(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        result = _run(fs.stats())
        assert isinstance(result, dict)

    def test_stats_keys_present(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        fs._engine = _fake_engine()
        result = _run(fs.stats())
        # Result is dict (may be empty if engine mock returns None)
        assert result is not None


# ===========================================================================
# FeedbackStore — close (lines 247-248)
# ===========================================================================

class Extra_TestFeedbackStoreClose:
    def test_close_disposes_engine(self):
        al = _get_al()
        fs = _make_enabled_store(al)
        engine = _fake_engine()
        fs._engine = engine
        _run(fs.close())
        assert fs._engine is None
        engine.dispose.assert_called_once()


# ===========================================================================
# DatasetExporter — export format branches (lines 300-325)
# ===========================================================================

class Extra_TestDatasetExporterFormats:
    def _store_with_rows(self, rows):
        class _Store:
            async def get_pending_export(self, min_rating=1):
                return rows

            async def mark_exported(self, ids):
                pass

        return _Store()

    def test_export_jsonl_format(self, tmp_path):
        al = _get_al()
        rows = [{"id": 1, "prompt": "Q", "response": "A", "correction": ""}]
        exporter = al.DatasetExporter(self._store_with_rows(rows))
        out = tmp_path / "out.jsonl"
        result = _run(exporter.export(str(out), fmt="jsonl"))
        assert result["count"] == 1
        line = json.loads(out.read_text())
        assert "prompt" in line
        assert "completion" in line

    def test_export_alpaca_format(self, tmp_path):
        al = _get_al()
        rows = [{"id": 2, "prompt": "instr", "response": "resp", "correction": ""}]
        exporter = al.DatasetExporter(self._store_with_rows(rows))
        out = tmp_path / "out.alpaca.jsonl"
        result = _run(exporter.export(str(out), fmt="alpaca"))
        assert result["count"] == 1
        line = json.loads(out.read_text())
        assert "instruction" in line

    def test_export_sharegpt_uses_correction_over_response(self, tmp_path):
        al = _get_al()
        rows = [{"id": 3, "prompt": "Q2", "response": "old", "correction": "new"}]
        exporter = al.DatasetExporter(self._store_with_rows(rows))
        out = tmp_path / "out.sharegpt.jsonl"
        result = _run(exporter.export(str(out), fmt="sharegpt"))
        assert result["count"] == 1
        line = json.loads(out.read_text())
        assert line["conversations"][1]["value"] == "new"

    def test_export_mark_done_false_skips_mark_exported(self, tmp_path):
        al = _get_al()
        marked = []

        class _Store:
            async def get_pending_export(self, min_rating=1):
                return [{"id": 5, "prompt": "p", "response": "r", "correction": ""}]

            async def mark_exported(self, ids):
                marked.extend(ids)

        out = tmp_path / "no_mark.jsonl"
        exporter = al.DatasetExporter(_Store())
        _run(exporter.export(str(out), fmt="jsonl", mark_done=False))
        assert marked == []

    def test_export_mark_done_true_calls_mark_exported(self, tmp_path):
        al = _get_al()
        marked = []

        class _Store:
            async def get_pending_export(self, min_rating=1):
                return [{"id": 7, "prompt": "p", "response": "r", "correction": ""}]

            async def mark_exported(self, ids):
                marked.extend(ids)

        out = tmp_path / "mark.jsonl"
        exporter = al.DatasetExporter(_Store())
        _run(exporter.export(str(out), fmt="jsonl", mark_done=True))
        assert 7 in marked


# ===========================================================================
# ContinuousLearningPipeline — _normalize_tags (lines 373-375)
# ===========================================================================

class Extra_TestNormalizeTagsExtra:
    def _norm(self, tags):
        al = _get_al()
        return al.ContinuousLearningPipeline._normalize_tags(tags)

    def test_json_string_with_non_list_returns_empty(self):
        # parsed is not a list → return []
        result = self._norm('"just_a_string"')
        assert result == []

    def test_json_object_returns_empty(self):
        result = self._norm('{"key": "value"}')
        assert result == []

    def test_none_returns_empty(self):
        result = self._norm(None)
        assert result == []


# ===========================================================================
# ContinuousLearningPipeline — _build_sft_examples (lines 382-408)
# ===========================================================================

class Extra_TestBuildSftExamples:
    def _make_pipeline(self, al_mod):
        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = False
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 0
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_ACTIVE_LEARNING = True
            DATABASE_URL = ""

        cfg = _Cfg()
        store = al_mod.FeedbackStore(config=cfg)
        return al_mod.ContinuousLearningPipeline(store, config=cfg)

    def test_skip_row_no_prompt(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "", "response": "r", "correction": "", "rating": 1, "tags": "[]"}]
        result = pipeline._build_sft_examples(rows)
        assert result == []

    def test_skip_row_below_min_rating(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "r", "correction": "", "rating": 0, "tags": "[]"}]
        result = pipeline._build_sft_examples(rows)
        assert result == []

    def test_skip_judge_reasoning_signal(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{
            "prompt": "p", "response": "r", "correction": "c", "rating": 1,
            "tags": '["judge_reasoning", "weak_response"]',
        }]
        result = pipeline._build_sft_examples(rows)
        assert result == []

    def test_skip_row_no_output(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "", "correction": "", "rating": 1, "tags": "[]"}]
        result = pipeline._build_sft_examples(rows)
        assert result == []

    def test_uses_correction_when_present(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "old", "correction": "new", "rating": 1, "tags": "[]", "id": 99}]
        result = pipeline._build_sft_examples(rows)
        assert len(result) == 1
        assert result[0]["output"] == "new"
        assert result[0]["source"] == "correction"

    def test_falls_back_to_response_when_no_correction(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "resp", "correction": "", "rating": 1, "tags": "[]", "id": 10}]
        result = pipeline._build_sft_examples(rows)
        assert len(result) == 1
        assert result[0]["output"] == "resp"
        assert result[0]["source"] == "response"


# ===========================================================================
# ContinuousLearningPipeline — _build_preference_examples (lines 410-432)
# ===========================================================================

class Extra_TestBuildPreferenceExamples:
    def _make_pipeline(self, al_mod):
        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = False
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 0
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_ACTIVE_LEARNING = True
            DATABASE_URL = ""

        cfg = _Cfg()
        store = al_mod.FeedbackStore(config=cfg)
        return al_mod.ContinuousLearningPipeline(store, config=cfg)

    def test_skip_row_no_correction(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "r", "correction": "", "rating": 1, "tags": "[]"}]
        result = pipeline._build_preference_examples(rows)
        assert result == []

    def test_skip_row_correction_equals_response(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "same", "correction": "same", "rating": 1, "tags": "[]"}]
        result = pipeline._build_preference_examples(rows)
        assert result == []

    def test_skip_judge_reasoning_signal(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{
            "prompt": "p", "response": "old", "correction": "new", "rating": 1,
            "tags": '["judge_reasoning", "weak_response"]',
        }]
        result = pipeline._build_preference_examples(rows)
        assert result == []

    def test_valid_row_produces_preference_pair(self):
        al = _get_al()
        pipeline = self._make_pipeline(al)
        rows = [{"prompt": "p", "response": "rejected", "correction": "chosen", "rating": 1, "tags": "[]", "id": 5}]
        result = pipeline._build_preference_examples(rows)
        assert len(result) == 1
        assert result[0]["chosen"] == "chosen"
        assert result[0]["rejected"] == "rejected"


# ===========================================================================
# ContinuousLearningPipeline — _serialize_sft_examples (lines 434-466)
# ===========================================================================

class Extra_TestSerializeSftExamples:
    def _serialize(self, rows, fmt):
        al = _get_al()
        return al.ContinuousLearningPipeline._serialize_sft_examples(rows, fmt)

    def test_jsonl_format(self):
        rows = [{"instruction": "q", "output": "a", "input": ""}]
        result = self._serialize(rows, "jsonl")
        assert result[0] == {"prompt": "q", "completion": "a"}

    def test_alpaca_format(self):
        rows = [{"instruction": "q", "output": "a", "input": "ctx"}]
        result = self._serialize(rows, "alpaca")
        assert result[0]["instruction"] == "q"
        assert result[0]["input"] == "ctx"

    def test_sharegpt_format(self):
        rows = [{"instruction": "q", "output": "a", "input": ""}]
        result = self._serialize(rows, "sharegpt")
        assert result[0]["conversations"][0]["from"] == "human"
        assert result[0]["conversations"][1]["value"] == "a"

    def test_skip_empty_prompt(self):
        rows = [{"instruction": "", "output": "a", "input": ""}]
        result = self._serialize(rows, "alpaca")
        assert result == []

    def test_skip_empty_output(self):
        rows = [{"instruction": "q", "output": "", "input": ""}]
        result = self._serialize(rows, "alpaca")
        assert result == []

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="Desteklenmeyen"):
            al = _get_al()
            al.ContinuousLearningPipeline._serialize_sft_examples([], "bad_format")


# ===========================================================================
# ContinuousLearningPipeline — run_cycle (lines 517-561)
# ===========================================================================

class Extra_TestRunCycle:
    def _make_pipeline(self, al_mod, enabled=True):
        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = enabled
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl_run"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 0
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_ACTIVE_LEARNING = True
            DATABASE_URL = ""

        cfg = _Cfg()
        store = al_mod.FeedbackStore(config=cfg)
        return al_mod.ContinuousLearningPipeline(store, config=cfg)

    def test_run_cycle_disabled_returns_early(self):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=False)
        result = _run(pipeline.run_cycle())
        assert result["success"] is False
        assert result["reason"] == "continuous_learning_disabled"

    def test_run_cycle_cooldown_active(self, tmp_path):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=True)
        pipeline.cooldown_seconds = 3600
        pipeline._last_run_at = time.time()
        result = _run(pipeline.run_cycle())
        assert result["reason"] == "cooldown_active"
        assert "retry_after" in result

    def test_run_cycle_insufficient_signals(self, tmp_path):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=True)
        pipeline.cooldown_seconds = 0

        async def _fake_build(output_dir=None):
            return {
                "counts": {"sft_examples": 0, "preference_examples": 0},
                "sft_path": str(tmp_path / "sft.alpaca.jsonl"),
                "sft_format": "alpaca",
                "training_ready": {"sft": False, "preference": False},
            }

        pipeline.build_dataset_bundle = _fake_build
        result = _run(pipeline.run_cycle())
        assert result["reason"] == "insufficient_signals"

    def test_run_cycle_success_no_training(self, tmp_path):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=True)
        pipeline.cooldown_seconds = 0
        sft_path = tmp_path / "sft.alpaca.jsonl"
        sft_path.write_text("{}\n")

        async def _fake_build(output_dir=None):
            return {
                "counts": {"sft_examples": 10, "preference_examples": 5},
                "sft_path": str(sft_path),
                "sft_format": "alpaca",
                "training_ready": {"sft": True, "preference": True},
            }

        pipeline.build_dataset_bundle = _fake_build
        result = _run(pipeline.run_cycle())
        assert result["success"] is True
        assert result["scheduled"] is True


# ===========================================================================
# ContinuousLearningPipeline — schedule_cycle (lines 563-581)
# ===========================================================================

class Extra_TestScheduleCycle:
    def _make_pipeline(self, al_mod, enabled=True):
        class _Cfg:
            ENABLE_CONTINUOUS_LEARNING = enabled
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl_sched"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 0
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_ACTIVE_LEARNING = True
            DATABASE_URL = ""

        cfg = _Cfg()
        store = al_mod.FeedbackStore(config=cfg)
        return al_mod.ContinuousLearningPipeline(store, config=cfg)

    def test_schedule_cycle_disabled_returns_false(self):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=False)
        result = pipeline.schedule_cycle()
        assert result is False

    def test_schedule_cycle_no_running_loop_returns_false(self):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=True)
        # Called outside of an event loop → RuntimeError → returns False
        result = pipeline.schedule_cycle()
        assert result is False

    def test_schedule_cycle_with_running_loop(self):
        al = _get_al()
        pipeline = self._make_pipeline(al, enabled=True)

        async def _run_test():
            # Inside an event loop; schedule_cycle should return True
            # and create a task.
            result = pipeline.schedule_cycle()
            assert result is True
            # Give the task a tick to run (it will try to run build_dataset_bundle)
            await asyncio.sleep(0)

        # Provide a fake build_dataset_bundle that doesn't fail
        async def _noop_build(output_dir=None):
            return {
                "counts": {"sft_examples": 0, "preference_examples": 0},
                "sft_path": "/tmp/sft.jsonl",
                "sft_format": "alpaca",
                "training_ready": {"sft": False, "preference": False},
            }

        pipeline.build_dataset_bundle = _noop_build
        asyncio.run(_run_test())


# ===========================================================================
# LoRATrainer (lines 600-639)
# ===========================================================================

class Extra_TestLoRATrainer:
    def _make_trainer(self, al_mod, **overrides):
        class _Cfg:
            ENABLE_LORA_TRAINING = overrides.get("enabled", False)
            LORA_BASE_MODEL = overrides.get("base_model", "")
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora_test"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False

        return al_mod.LoRATrainer(config=_Cfg())

    def test_trainer_init_defaults(self):
        al = _get_al()
        trainer = self._make_trainer(al)
        assert trainer.enabled is False
        assert trainer.lora_rank == 8
        assert trainer.lora_alpha == 16
        assert trainer._peft_available is None

    def test_train_disabled_returns_failure(self):
        al = _get_al()
        trainer = self._make_trainer(al, enabled=False)
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False
        assert "devre dışı" in result["reason"]

    def test_train_no_peft_returns_failure(self):
        al = _get_al()
        trainer = self._make_trainer(al, enabled=True)
        trainer._peft_available = False  # pre-set so _check_peft returns False
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False

    def test_train_no_base_model_returns_failure(self):
        al = _get_al()
        trainer = self._make_trainer(al, enabled=True, base_model="")
        # peft "available" but no model
        trainer._peft_available = True
        result = trainer.train("some/path.jsonl")
        assert result["success"] is False
        assert "LORA_BASE_MODEL" in result["reason"]

    def test_check_peft_returns_false_when_not_installed(self):
        al = _get_al()
        trainer = self._make_trainer(al, enabled=True)
        # peft is not installed in test env
        result = trainer._check_peft()
        assert result is False
        assert trainer._peft_available is False

    def test_check_peft_cached_result(self):
        al = _get_al()
        trainer = self._make_trainer(al)
        trainer._peft_available = True  # pre-cache
        assert trainer._check_peft() is True

    def test_train_exception_returns_failure(self):
        al = _get_al()
        trainer = self._make_trainer(al, enabled=True, base_model="some/model")
        trainer._peft_available = True

        def _raise(_path):
            raise RuntimeError("training error")

        trainer._run_training = _raise
        result = trainer.train("path.jsonl")
        assert result["success"] is False
        assert "training error" in result["reason"]


# ===========================================================================
# _chunked utility (lines 744-746)
# ===========================================================================

class Extra_TestChunked:
    def test_chunked_basic(self):
        al = _get_al()
        result = list(al._chunked([1, 2, 3, 4, 5], 2))
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunked_larger_size_than_list(self):
        al = _get_al()
        result = list(al._chunked([1, 2], 10))
        assert result == [[1, 2]]

    def test_chunked_empty_list(self):
        al = _get_al()
        result = list(al._chunked([], 5))
        assert result == []


# ===========================================================================
# Singleton functions (lines 759-793)
# ===========================================================================

class Extra_TestSingletons:
    def _reset_singletons(self, al_mod):
        al_mod._feedback_store = None
        al_mod._continuous_learning_pipeline = None

    def test_get_feedback_store_creates_instance(self):
        al = _get_al()
        self._reset_singletons(al)

        class _Cfg:
            DATABASE_URL = "sqlite+aiosqlite:///data/sidar.db"
            ENABLE_ACTIVE_LEARNING = True
            AL_MIN_RATING_FOR_TRAIN = 1

        # Patch Config so get_feedback_store can instantiate it
        import sys as _sys
        orig_config = _sys.modules.get("config")
        try:
            cfg_mod = types.ModuleType("config")
            cfg_mod.Config = _Cfg
            _sys.modules["config"] = cfg_mod

            store = al.get_feedback_store()
            assert isinstance(store, al.FeedbackStore)
            # second call returns same object
            store2 = al.get_feedback_store()
            assert store is store2
        finally:
            if orig_config is not None:
                _sys.modules["config"] = orig_config
            self._reset_singletons(al)

    def test_get_continuous_learning_pipeline_creates_instance(self):
        al = _get_al()
        self._reset_singletons(al)

        class _Cfg:
            DATABASE_URL = "sqlite+aiosqlite:///data/sidar.db"
            ENABLE_ACTIVE_LEARNING = True
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_CONTINUOUS_LEARNING = False
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 3600
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False

        import sys as _sys
        orig_config = _sys.modules.get("config")
        try:
            cfg_mod = types.ModuleType("config")
            cfg_mod.Config = _Cfg
            _sys.modules["config"] = cfg_mod

            pipeline = al.get_continuous_learning_pipeline()
            assert isinstance(pipeline, al.ContinuousLearningPipeline)
            # second call returns same object
            pipeline2 = al.get_continuous_learning_pipeline()
            assert pipeline is pipeline2
        finally:
            if orig_config is not None:
                _sys.modules["config"] = orig_config
            self._reset_singletons(al)

    def test_schedule_continuous_learning_cycle(self):
        al = _get_al()
        self._reset_singletons(al)

        class _Cfg:
            DATABASE_URL = ""
            ENABLE_ACTIVE_LEARNING = True
            AL_MIN_RATING_FOR_TRAIN = 1
            ENABLE_CONTINUOUS_LEARNING = False  # disabled → schedule_cycle returns False
            CONTINUOUS_LEARNING_OUTPUT_DIR = "/tmp/cl"
            CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES = 5
            CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES = 3
            CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS = 100
            CONTINUOUS_LEARNING_COOLDOWN_SECONDS = 3600
            CONTINUOUS_LEARNING_SFT_FORMAT = "alpaca"
            ENABLE_LORA_TRAINING = False
            LORA_BASE_MODEL = ""
            LORA_RANK = 8
            LORA_ALPHA = 16
            LORA_DROPOUT = 0.05
            LORA_OUTPUT_DIR = "/tmp/lora"
            LORA_EPOCHS = 3
            LORA_BATCH_SIZE = 4
            LORA_USE_4BIT = False

        import sys as _sys
        orig_config = _sys.modules.get("config")
        try:
            cfg_mod = types.ModuleType("config")
            cfg_mod.Config = _Cfg
            _sys.modules["config"] = cfg_mod

            result = al.schedule_continuous_learning_cycle()
            assert result is False
        finally:
            if orig_config is not None:
                _sys.modules["config"] = orig_config
            self._reset_singletons(al)


# ===========================================================================
# Module-level flag_weak_response (lines 796-820)
# ===========================================================================

class Extra_TestModuleLevelFlagWeakResponse:
    def _reset_singletons(self, al_mod):
        al_mod._feedback_store = None
        al_mod._continuous_learning_pipeline = None

    def test_flag_weak_response_disabled_store(self):
        al = _get_al()
        self._reset_singletons(al)

        class _Cfg:
            DATABASE_URL = ""
            ENABLE_ACTIVE_LEARNING = False
            AL_MIN_RATING_FOR_TRAIN = 1

        import sys as _sys
        orig_config = _sys.modules.get("config")
        try:
            cfg_mod = types.ModuleType("config")
            cfg_mod.Config = _Cfg
            _sys.modules["config"] = cfg_mod

            result = _run(al.flag_weak_response(
                prompt="p", response="r", score=3, reasoning="bad"
            ))
            assert result is False
        finally:
            if orig_config is not None:
                _sys.modules["config"] = orig_config
            self._reset_singletons(al)

    def test_flag_weak_response_passes_through(self):
        al = _get_al()
        self._reset_singletons(al)
        captured = {}

        class _FakeStore:
            enabled = True
            _engine = object()

            async def flag_weak_response(self, **kwargs):
                captured.update(kwargs)
                return True

        al._feedback_store = _FakeStore()
        result = _run(al.flag_weak_response(
            prompt="ppp", response="rrr", score=2, reasoning="ok",
            user_id="u1",
        ))
        assert result is True
        assert captured["prompt"] == "ppp"
        self._reset_singletons(al)
