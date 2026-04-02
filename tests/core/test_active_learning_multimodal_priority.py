from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from core.active_learning import ContinuousLearningPipeline, DatasetExporter

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = type("AsyncClient", (), {})
    sys.modules["httpx"] = fake_httpx

import core.multimodal as multimodal


class _StoreStub:
    min_rating_for_train = 1

    async def get_pending_signals(self, limit: int = 10000):
        _ = limit
        return [
            {"id": 1, "prompt": "p1", "response": "r1", "correction": "", "rating": 1, "tags": "[]"},
            {"id": 2, "prompt": "p2", "response": "weak", "correction": "better", "rating": -1, "tags": ["manual"]},
            {"id": 3, "prompt": "p3", "response": "r3", "correction": "", "rating": 1, "tags": ["judge_reasoning", "weak_response"]},
        ]


def test_continuous_learning_example_builders_filter_expected_rows() -> None:
    pipeline = ContinuousLearningPipeline(
        _StoreStub(),
        trainer=SimpleNamespace(enabled=False),
        config=SimpleNamespace(ENABLE_CONTINUOUS_LEARNING=True),
    )

    rows = asyncio.run(pipeline.store.get_pending_signals())
    sft = pipeline._build_sft_examples(rows)
    pref = pipeline._build_preference_examples(rows)

    assert len(sft) == 1
    assert sft[0]["feedback_id"] == 1
    assert len(pref) == 1
    assert pref[0]["feedback_id"] == 2


def test_continuous_learning_bundle_and_cycle(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        ENABLE_CONTINUOUS_LEARNING=True,
        CONTINUOUS_LEARNING_OUTPUT_DIR=str(tmp_path),
        CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES=1,
        CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES=10,
        CONTINUOUS_LEARNING_SFT_FORMAT="alpaca",
        CONTINUOUS_LEARNING_COOLDOWN_SECONDS=0,
    )
    trainer = SimpleNamespace(enabled=True, train=lambda _path: {"success": True, "adapter": "ok"})
    pipeline = ContinuousLearningPipeline(_StoreStub(), trainer=trainer, config=cfg)

    manifest = asyncio.run(pipeline.build_dataset_bundle())
    assert manifest["counts"]["sft_examples"] == 1
    assert Path(manifest["sft_path"]).exists()
    assert Path(manifest["preference_path"]).exists()

    result = asyncio.run(pipeline.run_cycle(reason="test"))
    assert result["scheduled"] is True
    assert result["training_result"]["success"] is True


def test_dataset_exporter_serialization_and_multimodal_helpers(tmp_path: Path) -> None:
    rows = [{"instruction": "i", "input": "", "output": "o"}]
    as_jsonl = ContinuousLearningPipeline._serialize_sft_examples(rows, "jsonl")
    assert as_jsonl == [{"prompt": "i", "completion": "o"}]

    assert multimodal.detect_media_kind(mime_type="video/mp4") == "video"
    assert multimodal.extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    normalized = multimodal._normalize_youtube_transcript_events(
        [{"tStartMs": 1000, "dDurationMs": 500, "segs": [{"utf8": "Merhaba"}]}]
    )
    assert normalized["text"] == "Merhaba"
    assert normalized["segments"][0]["start_seconds"] == 1.0

    context = multimodal.build_multimodal_context(
        media_kind="video",
        transcript={"text": "konuşma", "language": "tr"},
        frame_analyses=[{"timestamp_seconds": 1.5, "analysis": "sahne"}],
        extra_notes="not",
    )
    assert "Transkript" in context
    assert "Frame Bulguları" in context

    title, content = multimodal.render_multimodal_document(
        {
            "media_kind": "video",
            "transcript": {"text": "özet"},
            "frame_analyses": [{"timestamp_seconds": 1.0, "analysis": "ekran"}],
            "analysis": "aksiyon",
            "context": "bağlam",
            "download": {"platform": "youtube", "resolved_url": "https://cdn"},
        },
        source="https://youtube.com/watch?v=dQw4w9WgXcQ",
    )
    assert "Video İçgörü Özeti" in title
    assert "Platform: youtube" in content

    pipeline = multimodal.MultimodalPipeline(llm_client=SimpleNamespace(), config=SimpleNamespace(ENABLE_MULTIMODAL=False))
    transcribed = asyncio.run(pipeline.transcribe_bytes(b"abc"))
    assert transcribed["success"] is False
