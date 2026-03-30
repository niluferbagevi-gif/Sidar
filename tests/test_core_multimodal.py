"""
core/multimodal.py için birim testleri.
detect_media_kind, is_remote_media_source, detect_video_platform,
extract_youtube_video_id, _normalize_youtube_transcript_events,
_guess_suffix saf fonksiyonlarını kapsar.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock


def _get_mm():
    if "core.multimodal" in sys.modules:
        del sys.modules["core.multimodal"]
    import core.multimodal as mm
    return mm


# ══════════════════════════════════════════════════════════════
# detect_media_kind
# ══════════════════════════════════════════════════════════════

class TestDetectMediaKind:
    def test_video_mime_returns_video(self):
        mm = _get_mm()
        assert mm.detect_media_kind(mime_type="video/mp4") == "video"

    def test_audio_mime_returns_audio(self):
        mm = _get_mm()
        assert mm.detect_media_kind(mime_type="audio/mpeg") == "audio"

    def test_image_mime_returns_image(self):
        mm = _get_mm()
        assert mm.detect_media_kind(mime_type="image/png") == "image"

    def test_unknown_mime_returns_unknown(self):
        mm = _get_mm()
        assert mm.detect_media_kind(mime_type="application/pdf") == "unknown"

    def test_empty_mime_returns_unknown(self):
        mm = _get_mm()
        assert mm.detect_media_kind(mime_type="") == "unknown"

    def test_path_mp4_returns_video(self):
        mm = _get_mm()
        assert mm.detect_media_kind(path="video.mp4") == "video"

    def test_path_png_returns_image(self):
        mm = _get_mm()
        assert mm.detect_media_kind(path="photo.png") == "image"

    def test_path_mp3_returns_audio(self):
        mm = _get_mm()
        assert mm.detect_media_kind(path="song.mp3") == "audio"

    def test_mime_takes_precedence_over_path(self):
        mm = _get_mm()
        # mime says audio but path says video
        result = mm.detect_media_kind(mime_type="audio/mpeg", path="clip.mp4")
        assert result == "audio"


# ══════════════════════════════════════════════════════════════
# is_remote_media_source
# ══════════════════════════════════════════════════════════════

class TestIsRemoteMediaSource:
    def test_https_url_is_remote(self):
        mm = _get_mm()
        assert mm.is_remote_media_source("https://example.com/video.mp4") is True

    def test_http_url_is_remote(self):
        mm = _get_mm()
        assert mm.is_remote_media_source("http://example.com/audio.mp3") is True

    def test_local_path_not_remote(self):
        mm = _get_mm()
        assert mm.is_remote_media_source("/home/user/video.mp4") is False

    def test_relative_path_not_remote(self):
        mm = _get_mm()
        assert mm.is_remote_media_source("data/video.mp4") is False

    def test_empty_string_not_remote(self):
        mm = _get_mm()
        assert mm.is_remote_media_source("") is False


# ══════════════════════════════════════════════════════════════
# detect_video_platform
# ══════════════════════════════════════════════════════════════

class TestDetectVideoPlatform:
    def test_youtube_watch_url(self):
        mm = _get_mm()
        assert mm.detect_video_platform("https://www.youtube.com/watch?v=abc123") == "youtube"

    def test_youtu_be_url(self):
        mm = _get_mm()
        assert mm.detect_video_platform("https://youtu.be/abc1234567") == "youtube"

    def test_vimeo_url(self):
        mm = _get_mm()
        assert mm.detect_video_platform("https://vimeo.com/123456") == "vimeo"

    def test_loom_url(self):
        mm = _get_mm()
        assert mm.detect_video_platform("https://www.loom.com/share/abc") == "loom"

    def test_generic_url(self):
        mm = _get_mm()
        assert mm.detect_video_platform("https://example.com/video.mp4") == "generic"

    def test_empty_returns_generic(self):
        mm = _get_mm()
        assert mm.detect_video_platform("") == "generic"


# ══════════════════════════════════════════════════════════════
# extract_youtube_video_id
# ══════════════════════════════════════════════════════════════

class TestExtractYoutubeVideoId:
    def _extract(self, url):
        mm = _get_mm()
        return mm.extract_youtube_video_id(url)

    def test_watch_url(self):
        assert self._extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_url(self):
        assert self._extract("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert self._extract("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert self._extract("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_live_url(self):
        assert self._extract("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id_11_chars(self):
        assert self._extract("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_empty_returns_empty(self):
        assert self._extract("") == ""

    def test_non_youtube_returns_empty(self):
        assert self._extract("https://vimeo.com/123456") == ""

    def test_invalid_watch_url_returns_empty(self):
        assert self._extract("https://www.youtube.com/watch?v=tooshort") == ""


# ══════════════════════════════════════════════════════════════
# _normalize_youtube_transcript_events
# ══════════════════════════════════════════════════════════════

class TestNormalizeYoutubeTranscriptEvents:
    def _norm(self, events):
        mm = _get_mm()
        return mm._normalize_youtube_transcript_events(events)

    def test_empty_events_returns_empty_text(self):
        result = self._norm([])
        assert result["text"] == ""
        assert result["segments"] == []

    def test_single_event_with_text(self):
        events = [
            {"segs": [{"utf8": "Hello"}], "tStartMs": 1000, "dDurationMs": 2000}
        ]
        result = self._norm(events)
        assert "Hello" in result["text"]
        assert len(result["segments"]) == 1
        assert result["segments"][0]["start_seconds"] == 1.0

    def test_multiple_segments_joined(self):
        events = [
            {"segs": [{"utf8": "First"}], "tStartMs": 0, "dDurationMs": 1000},
            {"segs": [{"utf8": "Second"}], "tStartMs": 1000, "dDurationMs": 1000},
        ]
        result = self._norm(events)
        assert "First" in result["text"]
        assert "Second" in result["text"]
        assert len(result["segments"]) == 2

    def test_html_entities_unescaped(self):
        events = [{"segs": [{"utf8": "&amp;"}], "tStartMs": 0, "dDurationMs": 0}]
        result = self._norm(events)
        assert "&" in result["text"]

    def test_empty_segs_skipped(self):
        events = [
            {"segs": [], "tStartMs": 0, "dDurationMs": 0},
            {"segs": [{"utf8": "Hello"}], "tStartMs": 0, "dDurationMs": 0},
        ]
        result = self._norm(events)
        assert len(result["segments"]) == 1

    def test_non_dict_items_skipped(self):
        events = ["not_a_dict", {"segs": [{"utf8": "Valid"}], "tStartMs": 0, "dDurationMs": 0}]
        result = self._norm(events)
        assert len(result["segments"]) == 1

    def test_none_input_returns_empty(self):
        result = self._norm(None)
        assert result["text"] == ""


# ══════════════════════════════════════════════════════════════
# _guess_suffix
# ══════════════════════════════════════════════════════════════

class TestGuessSuffix:
    def test_mp4_returns_mp4(self):
        mm = _get_mm()
        assert mm._guess_suffix("video/mp4", ".bin") == ".mp4"

    def test_mp3_returns_mp3(self):
        mm = _get_mm()
        assert mm._guess_suffix("audio/mpeg", ".bin") == ".mp3"

    def test_wav_returns_wav(self):
        mm = _get_mm()
        assert mm._guess_suffix("audio/wav", ".bin") == ".wav"

    def test_unknown_mime_uses_fallback(self):
        mm = _get_mm()
        assert mm._guess_suffix("application/octet-stream", ".unknown") == ".unknown"

    def test_empty_mime_uses_fallback(self):
        mm = _get_mm()
        assert mm._guess_suffix("", ".fallback") == ".fallback"


class TestMultimodalRemoteAndTranscriptFlows:
    def test_fetch_youtube_transcript_returns_invalid_id_reason(self):
        mm = _get_mm()
        result = asyncio.run(mm.fetch_youtube_transcript("https://example.com/video"))
        assert result["success"] is False
        assert "video id" in result["reason"].lower()

    def test_fetch_youtube_transcript_handles_empty_events(self):
        mm = _get_mm()

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"events": []}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                return _Resp()

        result = asyncio.run(
            mm.fetch_youtube_transcript(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                http_client_factory=lambda **_kwargs: _Client(),
            )
        )
        assert result["success"] is False
        assert "bulunamadı" in result["reason"].lower()

    def test_download_remote_media_rejects_non_http_sources(self, tmp_path):
        mm = _get_mm()
        import pytest
        with pytest.raises(ValueError):
            asyncio.run(mm.download_remote_media("file:///tmp/a.mp4", output_dir=tmp_path))

    def test_download_remote_media_generic_http_success(self, tmp_path):
        mm = _get_mm()

        class _Resp:
            headers = {"content-type": "video/mp4"}
            content = b"dummy-bytes"

            def raise_for_status(self):
                return None

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                return _Resp()

        downloaded = asyncio.run(
            mm.download_remote_media(
                "https://cdn.example.com/video.mp4",
                output_dir=tmp_path,
                http_client_factory=lambda **_kwargs: _Client(),
            )
        )
        assert downloaded.platform == "generic"
        assert Path(downloaded.path).exists()
        assert downloaded.mime_type == "video/mp4"

    def test_resolve_remote_media_stream_non_remote_raises(self):
        mm = _get_mm()
        import pytest
        with pytest.raises(ValueError):
            asyncio.run(mm.resolve_remote_media_stream("/tmp/video.mp4"))

    def test_fetch_youtube_transcript_skips_invalid_json_payload(self):
        mm = _get_mm()

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return ["unexpected-list-payload"]

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, _url):
                return _Resp()

        result = asyncio.run(
            mm.fetch_youtube_transcript(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                http_client_factory=lambda **_kwargs: _Client(),
            )
        )
        assert result["success"] is False
        assert "bulunamadı" in result["reason"].lower()


class TestMultimodalPipelineEdgeCases:
    def test_analyze_media_source_empty_media_source_returns_error(self):
        mm = _get_mm()
        pipeline = mm.MultimodalPipeline(llm_client=AsyncMock(), config=type("Cfg", (), {"ENABLE_MULTIMODAL": True})())
        result = asyncio.run(pipeline.analyze_media_source(media_source="   "))
        assert result["success"] is False
        assert "media_source boş" in result["reason"]

    def test_analyze_media_source_youtube_remote_uses_transcript_override_and_ingests(self, monkeypatch, tmp_path):
        mm = _get_mm()
        media_file = tmp_path / "video.mp4"
        media_file.write_bytes(b"stub")

        async def _fake_download(*_args, **_kwargs):
            return mm.DownloadedMedia(
                path=str(media_file),
                source_url="https://youtu.be/dQw4w9WgXcQ",
                mime_type="video/mp4",
                platform="youtube",
                resolved_url="https://cdn.example.com/stream.mp4",
                title="Demo",
            )

        async def _fake_transcript(*_args, **_kwargs):
            return {"success": True, "text": "Merhaba dünya", "language": "tr", "segments": []}

        fake_analyze_local = AsyncMock(
            return_value={"success": True, "media_kind": "video", "analysis": "ok", "transcript": {}, "frame_analyses": []}
        )
        fake_ingest = AsyncMock(return_value={"success": True, "doc_id": "doc-42"})

        monkeypatch.setattr(mm, "_command_exists", lambda _name: False)
        monkeypatch.setattr(mm, "download_remote_media", _fake_download)
        monkeypatch.setattr(mm, "fetch_youtube_transcript", _fake_transcript)
        monkeypatch.setattr(mm.MultimodalPipeline, "_analyze_local_media", fake_analyze_local)
        monkeypatch.setattr(mm, "ingest_multimodal_analysis", fake_ingest)

        pipeline = mm.MultimodalPipeline(
            llm_client=AsyncMock(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True, "MULTIMODAL_REMOTE_DOWNLOAD_TIMEOUT": 5.0})(),
        )
        result = asyncio.run(
            pipeline.analyze_media_source(
                media_source="https://youtu.be/dQw4w9WgXcQ",
                ingest_document_store=object(),
                ingest_session_id="social",
                ingest_title="YouTube İçgörüsü",
                ingest_tags=["youtube", "campaign"],
            )
        )

        assert result["success"] is True
        assert result["download"]["platform"] == "youtube"
        assert result["document_ingest"]["doc_id"] == "doc-42"
        kwargs = fake_analyze_local.await_args.kwargs
        assert kwargs["transcript_override"]["text"] == "Merhaba dünya"
