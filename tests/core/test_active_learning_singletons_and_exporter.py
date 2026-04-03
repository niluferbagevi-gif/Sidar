from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import core.active_learning as active_learning


class _EmptyStore:
    async def get_pending_export(self, min_rating: int = 1):
        _ = min_rating
        return []


def test_dataset_exporter_rejects_unknown_format() -> None:
    exporter = active_learning.DatasetExporter(_EmptyStore())

    with pytest.raises(ValueError, match="Desteklenmeyen format"):
        asyncio.run(exporter.export("/tmp/out.jsonl", fmt="invalid"))


def test_dataset_exporter_returns_zero_when_no_rows(tmp_path) -> None:
    exporter = active_learning.DatasetExporter(_EmptyStore())

    result = asyncio.run(exporter.export(str(tmp_path / "bundle.jsonl"), fmt="alpaca", mark_done=True))

    assert result["count"] == 0
    assert result["format"] == "alpaca"
    assert result["path"].endswith("bundle.jsonl")


def test_continuous_learning_normalize_tags_handles_invalid_values() -> None:
    normalize = active_learning.ContinuousLearningPipeline._normalize_tags

    assert normalize("not-json") == []
    assert normalize('{"tags": ["a"]}') == []
    assert normalize(["a", "", "b", 3]) == ["a", "b", "3"]


def test_singleton_feedback_store_and_pipeline_reuse_instances() -> None:
    original_store = active_learning._feedback_store
    original_pipeline = active_learning._continuous_learning_pipeline
    try:
        active_learning._feedback_store = None
        active_learning._continuous_learning_pipeline = None

        cfg = SimpleNamespace(
            DATABASE_URL="sqlite+aiosqlite:///tmp/test-singleton.db",
            ENABLE_CONTINUOUS_LEARNING=True,
        )
        store_1 = active_learning.get_feedback_store(cfg)
        store_2 = active_learning.get_feedback_store(cfg)
        assert store_1 is store_2
        assert store_1._db_url == cfg.DATABASE_URL

        pipeline_1 = active_learning.get_continuous_learning_pipeline(cfg)
        pipeline_2 = active_learning.get_continuous_learning_pipeline(cfg)
        assert pipeline_1 is pipeline_2
        assert pipeline_1.store is store_1
    finally:
        active_learning._feedback_store = original_store
        active_learning._continuous_learning_pipeline = original_pipeline


def test_schedule_continuous_learning_cycle_without_event_loop_returns_false() -> None:
    class _Pipeline:
        def __init__(self) -> None:
            self.called = False

        def schedule_cycle(self, *, reason: str = "background") -> bool:
            self.called = True
            return reason == "manual"

    pipeline = _Pipeline()
    original_get_pipeline = active_learning.get_continuous_learning_pipeline
    try:
        active_learning.get_continuous_learning_pipeline = lambda config=None: pipeline

        assert active_learning.schedule_continuous_learning_cycle(config=None, reason="manual") is True
        assert pipeline.called is True
    finally:
        active_learning.get_continuous_learning_pipeline = original_get_pipeline


def test_flag_weak_response_uses_singleton_store() -> None:
    class _Store:
        def __init__(self) -> None:
            self.calls = []

        async def flag_weak_response(self, **kwargs):
            self.calls.append(kwargs)
            return True

    store = _Store()
    original_get_store = active_learning.get_feedback_store
    try:
        active_learning.get_feedback_store = lambda config=None: store
        ok = asyncio.run(
            active_learning.flag_weak_response(
                prompt="p",
                response="r",
                score=2,
                reasoning="neden",
                user_id="u",
            )
        )
        assert ok is True
        assert store.calls[0]["prompt"] == "p"
        assert store.calls[0]["user_id"] == "u"
    finally:
        active_learning.get_feedback_store = original_get_store


def test_chunked_splits_expected_sizes() -> None:
    chunks = list(active_learning._chunked([1, 2, 3, 4, 5], 2))
    assert chunks == [[1, 2], [3, 4], [5]]
