"""Production cutover smoke tests for the active learning subsystem.

Referenced from `.github/workflows/migration-cutover-checks.yml`. The deeper
behavioural suite lives at `tests/unit/core/test_active_learning.py`; this
module is intentionally narrow so the migration job can prove that the active
learning store can be constructed and short-circuits cleanly when disabled,
without bringing up an aiosqlite engine for every CI run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.active_learning import (
    ContinuousLearningPipeline,
    DatasetExporter,
    FeedbackStore,
    get_continuous_learning_pipeline,
    get_feedback_store,
)


def _disabled_cfg() -> SimpleNamespace:
    return SimpleNamespace(ENABLE_ACTIVE_LEARNING=False, AL_MIN_RATING_FOR_TRAIN=2)


@pytest.mark.asyncio
async def test_feedback_store_disabled_short_circuits_record_and_export() -> None:
    store = FeedbackStore(database_url="sqlite+aiosqlite:///:memory:", config=_disabled_cfg())

    assert store.enabled is False
    assert store.min_rating_for_train == 2

    await store.initialize()  # disabled → no engine
    assert store._engine is None

    recorded = await store.record(prompt="p", response="r", rating=1)
    assert recorded is False

    pending = await store.get_pending_export()
    assert pending == []

    signals = await store.get_pending_signals()
    assert signals == []


@pytest.mark.asyncio
async def test_dataset_exporter_rejects_unsupported_format() -> None:
    store = FeedbackStore(config=_disabled_cfg())
    exporter = DatasetExporter(store)

    with pytest.raises(ValueError):
        await exporter.export(output_path="/tmp/should-not-write.jsonl", fmt="xml")


@pytest.mark.asyncio
async def test_dataset_exporter_returns_zero_count_when_disabled(tmp_path) -> None:
    store = FeedbackStore(config=_disabled_cfg())
    exporter = DatasetExporter(store)

    out_path = tmp_path / "dataset.jsonl"
    result = await exporter.export(output_path=str(out_path), fmt="jsonl")

    assert result["count"] == 0
    assert result["format"] == "jsonl"
    assert out_path.exists() is False  # nothing flushed for empty datasets


def test_module_factories_return_singletons() -> None:
    cfg = _disabled_cfg()

    store_a = get_feedback_store(cfg)
    store_b = get_feedback_store(cfg)
    assert isinstance(store_a, FeedbackStore)
    assert store_a is store_b

    pipeline = get_continuous_learning_pipeline(cfg)
    assert isinstance(pipeline, ContinuousLearningPipeline)
    assert pipeline.store is store_a


def test_continuous_learning_pipeline_disabled_by_default() -> None:
    cfg = SimpleNamespace(ENABLE_ACTIVE_LEARNING=False)
    store = FeedbackStore(config=cfg)
    pipeline = ContinuousLearningPipeline(store=store, config=cfg)

    assert pipeline.enabled is False
    assert pipeline.store is store
