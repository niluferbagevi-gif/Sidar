import asyncio
from pathlib import Path
from types import SimpleNamespace

from core import multimodal as multimodal_mod
from core.multimodal import MultimodalPipeline, build_multimodal_context, render_multimodal_document

def test_build_multimodal_context_handles_missing_transcript_payload_cleanly():
    context = build_multimodal_context(media_kind="image", transcript=None, frame_analyses=None, extra_notes="")

    assert context == "Medya Türü: image"

def test_render_multimodal_document_skips_blank_transcript_but_keeps_download_metadata():
    title, content = render_multimodal_document(
        {
            "success": True,
            "media_kind": "audio",
            "transcript": {"text": "   "},
            "frame_analyses": [],
            "analysis": "",
            "context": "",
            "download": {
                "platform": "youtube",
                "resolved_url": "https://cdn.example.com/audio.webm",
            },
        },
        source="https://youtu.be/demo",
    )

    assert "Video İçgörü Özeti" in title
    assert "Platform: youtube" in content
    assert "Çözümlenen Akış: https://cdn.example.com/audio.webm" in content
    assert "Transkript Özeti:" not in content

def test_multimodal_pipeline_transcribe_bytes_uses_bin_suffix_for_unknown_mime(monkeypatch):
    captured = {}
    pipeline = MultimodalPipeline(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(ENABLE_MULTIMODAL=True, MULTIMODAL_MAX_FILE_BYTES=1024, VOICE_STT_PROVIDER="whisper", WHISPER_MODEL="base"),
    )

    async def _fake_transcribe(path, **kwargs):
        captured["path"] = Path(path)
        captured["bytes"] = Path(path).read_bytes()
        captured["kwargs"] = kwargs
        return {"success": False, "reason": "invalid audio bytes"}

    monkeypatch.setattr(multimodal_mod, "transcribe_audio", _fake_transcribe)

    result = asyncio.run(
        pipeline.transcribe_bytes(
            b"\xff\x00\xfebroken",
            mime_type="application/x-custom-audio",
            language="tr",
            prompt="bozuk veri",
        )
    )

    assert result == {"success": False, "reason": "invalid audio bytes"}
    assert captured["path"].suffix == ".bin"
    assert captured["bytes"] == b"\xff\x00\xfebroken"
    assert captured["kwargs"]["language"] == "tr"

def test_multimodal_pipeline_analyze_media_source_reports_downloaded_unsupported_format(tmp_path, monkeypatch):
    pipeline = MultimodalPipeline(
        llm_client=SimpleNamespace(chat=lambda **_kwargs: "unused"),
        config=SimpleNamespace(
            ENABLE_MULTIMODAL=True,
            MULTIMODAL_MAX_FILE_BYTES=2048,
            MULTIMODAL_REMOTE_DOWNLOAD_TIMEOUT=5.0,
            MULTIMODAL_REMOTE_VIDEO_MAX_SECONDS=30.0,
            YOUTUBE_TRANSCRIPT_TIMEOUT=5.0,
        ),
    )

    downloaded = tmp_path / "payload.bin"
    downloaded.write_bytes(b"\x00\x01garbage")

    async def _fake_download(*_args, **_kwargs):
        return multimodal_mod.DownloadedMedia(
            path=str(downloaded),
            mime_type="application/octet-stream",
            source_url="https://cdn.example.com/payload.bin",
            resolved_url="https://cdn.example.com/payload.bin",
            title="payload",
            platform="generic",
        )

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: False)
    monkeypatch.setattr(multimodal_mod, "download_remote_media", _fake_download)

    result = asyncio.run(
        pipeline.analyze_media_source(
            media_source="https://cdn.example.com/payload.bin",
            prompt="incele",
        )
    )

    assert result["success"] is False
    assert result["reason"] == "Desteklenmeyen medya türü: unknown"
    assert result["download"]["mime_type"] == "application/octet-stream"
    assert result["media_source"] == "https://cdn.example.com/payload.bin"