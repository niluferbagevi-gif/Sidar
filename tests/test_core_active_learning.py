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
