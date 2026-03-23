import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import ci_remediation as ci_mod
from core.llm_metrics import LLMMetricsCollector
from core.voice import VoicePipeline
from tests.test_llm_client_critical_gap_closers import _collect
from tests.test_llm_client_critical_gap_closers import _load_llm_module
from tests.test_rag_runtime_extended import _load_rag_module, _new_store

multimodal_mod = importlib.import_module("core.multimodal")


def test_track_stream_completion_records_failure_after_partial_disconnect(monkeypatch):
    llm_mod = _load_llm_module()
    recorded = []

    async def _broken_stream():
        yield "ilk"
        raise RuntimeError("stream dropped")

    monkeypatch.setattr(llm_mod, "_record_llm_metric", lambda **kwargs: recorded.append(kwargs))

    with pytest.raises(RuntimeError, match="stream dropped"):
        asyncio.run(
            _collect(
                llm_mod._track_stream_completion(
                    _broken_stream(),
                    provider="openai",
                    model="gpt-test",
                    started_at=0.0,
                )
            )
        )

    assert recorded == [
        {
            "provider": "openai",
            "model": "gpt-test",
            "started_at": 0.0,
            "success": False,
            "error": "stream dropped",
        }
    ]


def test_rag_add_document_sync_survives_chromadb_disconnect_and_keeps_index(tmp_path, monkeypatch):
    rag_mod = _load_rag_module(tmp_path)
    store = _new_store(rag_mod, tmp_path)
    errors = []

    class _BrokenCollection:
        def delete(self, **_kwargs):
            raise ConnectionError("chroma disconnected")

    store._chroma_available = True
    store.collection = _BrokenCollection()
    store._pgvector_available = False
    monkeypatch.setattr(rag_mod.logger, "error", lambda msg, *args: errors.append(msg % args if args else msg))

    doc_id = store._add_document_sync("Bağlantı koptu", "içerik " * 20, source="src://demo", session_id="s1")

    assert doc_id in store._index
    assert (store.store_dir / f"{doc_id}.txt").exists()
    assert any("ChromaDB belge ekleme hatası" in msg and "chroma disconnected" in msg for msg in errors)


def test_rag_add_document_from_file_reports_unicode_read_error(tmp_path, monkeypatch):
    rag_mod = _load_rag_module(tmp_path)
    store = _new_store(rag_mod, tmp_path)
    target = tmp_path / "broken.txt"
    target.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(rag_mod.Config, "BASE_DIR", tmp_path, raising=False)

    original_read_text = Path.read_text

    def _broken_read_text(self, *args, **kwargs):
        if self == target.resolve():
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _broken_read_text)

    ok, message = store.add_document_from_file(str(target))

    assert ok is False
    assert "[HATA] Dosya eklenemedi" in message
    assert "invalid start byte" in message


def test_render_multimodal_document_includes_reason_and_skips_duplicate_stream_url():
    title, content = multimodal_mod.render_multimodal_document(
        {
            "success": True,
            "media_kind": "video",
            "transcript": {"reason": "ses çözülemedi", "language": "tr"},
            "frame_analyses": [{"timestamp_seconds": 1.5, "analysis": "   "}],
            "analysis": "Özet hazır",
            "context": "Ham bağlam",
            "download": {"platform": "", "resolved_url": "https://example.com/video.mp4"},
        },
        source="https://example.com/video.mp4",
    )

    assert "Video İçgörü Özeti" in title
    assert "Transkript Özeti:" not in content
    assert "Sahne Özeti:" not in content
    assert "Çözümlenen Akış:" not in content
    assert "LLM İçgörüsü:\nÖzet hazır" in content
    assert "Multimodal Bağlam:\nHam bağlam" in content


def test_ci_remediation_extract_failed_job_names_returns_empty_for_empty_payload():
    assert ci_mod._extract_failed_job_names({}) == []
    assert ci_mod._extract_failed_job_names({"jobs": [None, "", {}]}) == []


def test_voice_pipeline_extract_ready_segments_preserves_remainder_when_only_blank_boundaries_exist():
    pipeline = VoicePipeline(SimpleNamespace(VOICE_TTS_PROVIDER="mock", VOICE_TTS_SEGMENT_CHARS=20))

    ready, remainder = pipeline.extract_ready_segments("\n\n  Devam", flush=False)

    assert ready == []
    assert remainder == "Devam"


def test_llm_metrics_snapshot_returns_empty_buckets_without_events():
    collector = LLMMetricsCollector(max_events=3)

    snapshot = collector.snapshot()

    assert snapshot["window_events"] == 0
    assert snapshot["totals"]["calls"] == 0
    assert snapshot["by_provider"] == {}
    assert snapshot["by_user"] == {}
    assert snapshot["recent"] == []
