"""
core/active_learning.py için birim testleri.
FeedbackStore (disabled path, config), DatasetExporter format sabitleri,
ContinuousLearningPipeline static yardımcıları kapsar.
SQLAlchemy gerektiren entegrasyon testleri skip'lenebilir.
"""
from __future__ import annotations

import asyncio
import sys

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


class TestIsJudgeReasoningSignal:
    def _check(self, row):
        al = _get_al()
        return al.ContinuousLearningPipeline._is_judge_reasoning_signal(row)

    def test_both_required_tags_detected(self):
        assert self._check({"tags": '["judge_reasoning", "weak_response"]'}) is True

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
