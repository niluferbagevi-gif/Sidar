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
