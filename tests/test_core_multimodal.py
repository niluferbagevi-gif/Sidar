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

import pytest


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

    def test_analyze_local_media_rejects_oversized_file(self, tmp_path):
        mm = _get_mm()
        media_file = tmp_path / "huge.mp4"
        media_file.write_bytes(b"0123456789")
        pipeline = mm.MultimodalPipeline(
            llm_client=AsyncMock(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True, "MULTIMODAL_MAX_FILE_BYTES": 4})(),
        )

        result = asyncio.run(pipeline._analyze_local_media(media_path=str(media_file)))
        assert result["success"] is False
        assert "boyut limitini" in result["reason"]

    def test_analyze_local_media_rejects_unsupported_media_kind(self, tmp_path, monkeypatch):
        mm = _get_mm()
        media_file = tmp_path / "archive.bin"
        media_file.write_bytes(b"abc")
        pipeline = mm.MultimodalPipeline(
            llm_client=AsyncMock(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True})(),
        )
        monkeypatch.setattr(mm, "detect_media_kind", lambda **_kwargs: "unknown")

        result = asyncio.run(pipeline._analyze_local_media(media_path=str(media_file)))
        assert result["success"] is False
        assert "Desteklenmeyen medya türü" in result["reason"]

    def test_analyze_local_image_unsupported_format_from_vision_pipeline_raises(self, tmp_path, monkeypatch):
        mm = _get_mm()
        media_file = tmp_path / "photo.heic"
        media_file.write_bytes(b"heic-dummy")

        class _BrokenVisionPipeline:
            def __init__(self, *_args, **_kwargs):
                pass

            async def analyze(self, **_kwargs):
                raise ValueError("unsupported image format: image/heic")

        monkeypatch.setattr(mm, "detect_media_kind", lambda **_kwargs: "image")
        monkeypatch.setitem(sys.modules, "core.vision", type("VMod", (), {"VisionPipeline": _BrokenVisionPipeline}))

        pipeline = mm.MultimodalPipeline(
            llm_client=AsyncMock(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True})(),
        )

        with pytest.raises(ValueError, match="unsupported image format"):
            asyncio.run(pipeline._analyze_local_media(media_path=str(media_file), mime_type="image/heic"))

    def test_analyze_media_source_ffmpeg_fallback_to_download_remote(self, monkeypatch, tmp_path):
        mm = _get_mm()
        media_file = tmp_path / "fallback.mp4"
        media_file.write_bytes(b"stub")

        async def _broken_materialize(*_args, **_kwargs):
            raise RuntimeError("ffmpeg pipeline crashed")

        async def _fake_download(*_args, **_kwargs):
            return mm.DownloadedMedia(
                path=str(media_file),
                source_url="https://example.com/video.mp4",
                mime_type="video/mp4",
                platform="generic",
                resolved_url="https://example.com/video.mp4",
                title="Fallback",
            )

        fake_analyze_local = AsyncMock(return_value={"success": True, "media_kind": "video", "analysis": "ok"})
        monkeypatch.setattr(mm, "_command_exists", lambda _name: True)
        monkeypatch.setattr(mm, "materialize_remote_media_for_ffmpeg", _broken_materialize)
        monkeypatch.setattr(mm, "download_remote_media", _fake_download)
        monkeypatch.setattr(mm.MultimodalPipeline, "_analyze_local_media", fake_analyze_local)

        pipeline = mm.MultimodalPipeline(llm_client=AsyncMock(), config=type("Cfg", (), {"ENABLE_MULTIMODAL": True})())
        result = asyncio.run(pipeline.analyze_media_source(media_source="https://example.com/video.mp4"))
        assert result["success"] is True
        assert result["download"]["path"] == str(media_file)

    def test_analyze_local_video_with_dummy_frame_metadata_and_mocked_vision(self, monkeypatch, tmp_path):
        mm = _get_mm()
        media_file = tmp_path / "campaign.mp4"
        media_file.write_bytes(b"video-dummy")

        async def _fake_extract_audio_track(_source, output_path):
            Path(output_path).write_bytes(b"audio-dummy")
            return output_path

        async def _fake_transcribe_audio(*_args, **_kwargs):
            return {
                "success": True,
                "text": "Video içeriği: ürün tanıtımı ve kampanya mesajı.",
                "language": "tr",
                "segments": [{"start_seconds": 0.0, "duration_seconds": 3.0, "text": "ürün tanıtımı"}],
            }

        async def _fake_extract_video_frames(*_args, **_kwargs):
            frame1 = tmp_path / "frame_001.jpg"
            frame2 = tmp_path / "frame_002.jpg"
            frame1.write_bytes(b"jpg1")
            frame2.write_bytes(b"jpg2")
            return [
                mm.ExtractedFrame(path=str(frame1), timestamp_seconds=0.0),
                mm.ExtractedFrame(path=str(frame2), timestamp_seconds=5.0),
            ]

        class _FakeVisionPipeline:
            def __init__(self, *_args, **_kwargs):
                pass

            async def analyze(self, image_path=None, **_kwargs):
                return {"success": True, "analysis": f"Frame analiz edildi: {Path(image_path).name}"}

        class _FakeLLM:
            async def chat(self, **_kwargs):
                return "Özet: Kampanya videosu analiz edildi."

        monkeypatch.setattr(mm, "extract_audio_track", _fake_extract_audio_track)
        monkeypatch.setattr(mm, "transcribe_audio", _fake_transcribe_audio)
        monkeypatch.setattr(mm, "extract_video_frames", _fake_extract_video_frames)
        monkeypatch.setitem(sys.modules, "core.vision", type("VMod", (), {"VisionPipeline": _FakeVisionPipeline}))

        pipeline = mm.MultimodalPipeline(
            llm_client=_FakeLLM(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True, "MULTIMODAL_MAX_FILE_BYTES": 1024 * 1024})(),
        )
        result = asyncio.run(
            pipeline._analyze_local_media(
                media_path=str(media_file),
                mime_type="video/mp4",
                frame_interval_seconds=5.0,
                max_frames=2,
            )
        )

        assert result["success"] is True
        assert result["media_kind"] == "video"
        assert len(result["frame_analyses"]) == 2
        assert result["frame_analyses"][0]["timestamp_seconds"] == 0.0
        assert "Frame analiz edildi" in result["frame_analyses"][1]["analysis"]
        assert "ürün tanıtımı" in result["transcript"]["text"]

    def test_transcribe_bytes_broken_audio_decoder_error_is_propagated(self, monkeypatch):
        mm = _get_mm()

        async def _broken_transcribe(*_args, **_kwargs):
            raise RuntimeError("audio decode failed: invalid header")

        monkeypatch.setattr(mm, "transcribe_audio", _broken_transcribe)

        pipeline = mm.MultimodalPipeline(
            llm_client=AsyncMock(),
            config=type("Cfg", (), {"ENABLE_MULTIMODAL": True, "MULTIMODAL_MAX_FILE_BYTES": 1024 * 1024})(),
        )

        with pytest.raises(RuntimeError, match="audio decode failed"):
            asyncio.run(
                pipeline.transcribe_bytes(
                    b"broken-audio-bytes",
                    mime_type="audio/wav",
                    language="tr",
                )
            )

# ===== MERGED FROM tests/test_core_multimodal_extra.py =====

import asyncio
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _get_multimodal():
    # httpx stub
    if "httpx" not in sys.modules:
        httpx_stub = types.ModuleType("httpx")
        httpx_stub.AsyncClient = MagicMock
        sys.modules["httpx"] = httpx_stub

    if "core.multimodal" in sys.modules:
        del sys.modules["core.multimodal"]
    import core.multimodal as mm
    return mm


# ══════════════════════════════════════════════════════════════
# _command_exists() (86), _run_subprocess() (90), _run_subprocess_capture() (94-95)
# ══════════════════════════════════════════════════════════════

class Extra_TestHelperFunctions:
    def test_command_exists_true(self):
        mm = _get_multimodal()
        with patch("shutil.which", return_value="/usr/bin/python3"):
            assert mm._command_exists("python3") is True

    def test_command_exists_false(self):
        mm = _get_multimodal()
        with patch("shutil.which", return_value=None):
            assert mm._command_exists("nonexistent_cmd") is False

    def test_run_subprocess(self):
        mm = _get_multimodal()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            mm._run_subprocess(["echo", "test"])
            mock_run.assert_called_once()

    def test_run_subprocess_capture(self):
        mm = _get_multimodal()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="output", returncode=0)
            result = mm._run_subprocess_capture(["echo", "hello"])
            assert result == "output"

    def test_guess_suffix_known_mime(self):
        mm = _get_multimodal()
        assert mm._guess_suffix("audio/wav", ".bin") == ".wav"

    def test_guess_suffix_unknown_mime(self):
        mm = _get_multimodal()
        assert mm._guess_suffix("application/octet-stream", ".bin") == ".bin"


# ══════════════════════════════════════════════════════════════
# detect_media_kind() (70-82)
# ══════════════════════════════════════════════════════════════

class Extra_TestDetectMediaKind:
    def test_video_mime(self):
        mm = _get_multimodal()
        assert mm.detect_media_kind(mime_type="video/mp4") == "video"

    def test_audio_mime(self):
        mm = _get_multimodal()
        assert mm.detect_media_kind(mime_type="audio/mpeg") == "audio"

    def test_image_mime(self):
        mm = _get_multimodal()
        assert mm.detect_media_kind(mime_type="image/jpeg") == "image"

    def test_unknown_mime(self):
        mm = _get_multimodal()
        assert mm.detect_media_kind(mime_type="text/plain") == "unknown"

    def test_from_path(self):
        mm = _get_multimodal()
        result = mm.detect_media_kind(path="video.mp4")
        assert result in ("video", "unknown")  # depends on mimetypes


# ══════════════════════════════════════════════════════════════
# is_remote_media_source() (102-104)
# ══════════════════════════════════════════════════════════════

class Extra_TestIsRemoteMediaSource:
    def test_http_url(self):
        mm = _get_multimodal()
        assert mm.is_remote_media_source("http://example.com/video.mp4") is True

    def test_https_url(self):
        mm = _get_multimodal()
        assert mm.is_remote_media_source("https://example.com/video.mp4") is True

    def test_local_path(self):
        mm = _get_multimodal()
        assert mm.is_remote_media_source("/local/file.mp4") is False


# ══════════════════════════════════════════════════════════════
# detect_video_platform() (107-115)
# ══════════════════════════════════════════════════════════════

class Extra_TestDetectVideoPlatform:
    def test_youtube(self):
        mm = _get_multimodal()
        assert mm.detect_video_platform("https://www.youtube.com/watch?v=abc") == "youtube"

    def test_youtu_be(self):
        mm = _get_multimodal()
        assert mm.detect_video_platform("https://youtu.be/abc123") == "youtube"

    def test_vimeo(self):
        mm = _get_multimodal()
        assert mm.detect_video_platform("https://vimeo.com/12345") == "vimeo"

    def test_loom(self):
        mm = _get_multimodal()
        assert mm.detect_video_platform("https://www.loom.com/share/abc") == "loom"

    def test_generic(self):
        mm = _get_multimodal()
        assert mm.detect_video_platform("https://example.com/video.mp4") == "generic"


# ══════════════════════════════════════════════════════════════
# extract_youtube_video_id() (118-137)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractYoutubeVideoId:
    def test_direct_id(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_url(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_empty_string(self):
        mm = _get_multimodal()
        assert mm.extract_youtube_video_id("") == ""

    def test_invalid_url(self):
        mm = _get_multimodal()
        result = mm.extract_youtube_video_id("https://example.com/not-youtube")
        assert result == ""


# ══════════════════════════════════════════════════════════════
# _normalize_youtube_transcript_events() (140-162)
# ══════════════════════════════════════════════════════════════

class Extra_TestNormalizeYoutubeTranscriptEvents:
    def test_basic_events(self):
        mm = _get_multimodal()
        events = [
            {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hello"}]},
            {"tStartMs": 2000, "dDurationMs": 2000, "segs": [{"utf8": " World"}]},
        ]
        result = mm._normalize_youtube_transcript_events(events)
        assert result["text"] == "Hello World"
        assert len(result["segments"]) == 2

    def test_empty_events(self):
        mm = _get_multimodal()
        result = mm._normalize_youtube_transcript_events([])
        assert result["text"] == ""
        assert result["segments"] == []

    def test_non_dict_items_skipped(self):
        mm = _get_multimodal()
        result = mm._normalize_youtube_transcript_events([None, "string", {"segs": []}])
        assert result["text"] == ""

    def test_empty_text_segments_skipped(self):
        mm = _get_multimodal()
        events = [{"segs": [{"utf8": "  "}]}]  # whitespace only
        result = mm._normalize_youtube_transcript_events(events)
        assert result["text"] == ""


# ══════════════════════════════════════════════════════════════
# fetch_youtube_transcript() (165-204)
# ══════════════════════════════════════════════════════════════

class Extra_TestFetchYoutubeTranscript:
    def test_invalid_video_id(self):
        mm = _get_multimodal()
        result = asyncio.run(mm.fetch_youtube_transcript("not-a-valid-id"))
        assert result["success"] is False

    def test_success_transcript(self):
        mm = _get_multimodal()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {
            "events": [
                {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Merhaba"}]}
            ]
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_resp)
        ))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = asyncio.run(mm.fetch_youtube_transcript("dQw4w9WgXcQ", http_client_factory=lambda **kw: mock_client))
        assert result["success"] is True
        assert result["text"] == "Merhaba"

    def test_http_error_response(self):
        mm = _get_multimodal()

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_resp)
        ))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = asyncio.run(mm.fetch_youtube_transcript("dQw4w9WgXcQ", http_client_factory=lambda **kw: mock_client))
        assert result["success"] is False


# ══════════════════════════════════════════════════════════════
# download_remote_media() (207-255)
# ══════════════════════════════════════════════════════════════

class Extra_TestDownloadRemoteMedia:
    def test_non_remote_raises(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="http/https"):
                asyncio.run(mm.download_remote_media("/local/file.mp4", output_dir=tmpdir))

    def test_http_download(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.headers = {"content-type": "video/mp4"}
            mock_resp.content = b"fake video data"

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=mock_resp)
            ))
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch.object(mm, "_command_exists", return_value=False):
                result = asyncio.run(mm.download_remote_media(
                    "https://example.com/video.mp4",
                    output_dir=tmpdir,
                    http_client_factory=lambda **kw: mock_client
                ))
            assert result.mime_type == "video/mp4"

    def test_youtube_with_ytdlp(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake output file
            fake_file = Path(tmpdir) / "video123.mp4"
            fake_file.write_bytes(b"fake data")

            with patch.object(mm, "_command_exists", return_value=True), \
                 patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
                result = asyncio.run(mm.download_remote_media(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    output_dir=tmpdir
                ))
            assert result.platform == "youtube"


# ══════════════════════════════════════════════════════════════
# extract_video_frames() (343-384)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractVideoFrames:
    def test_unsupported_strategy(self):
        mm = _get_multimodal()
        with pytest.raises(ValueError, match="fixed-interval"):
            asyncio.run(mm.extract_video_frames("/tmp/video.mp4", strategy="key-frames"))

    def test_zero_max_frames(self):
        mm = _get_multimodal()
        result = asyncio.run(mm.extract_video_frames("/tmp/video.mp4", max_frames=0))
        assert result == []

    def test_ffmpeg_not_found(self):
        mm = _get_multimodal()
        with patch.object(mm, "_command_exists", return_value=False):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                asyncio.run(mm.extract_video_frames("/tmp/video.mp4"))

    def test_file_not_found(self):
        mm = _get_multimodal()
        with patch.object(mm, "_command_exists", return_value=True):
            with pytest.raises(FileNotFoundError):
                asyncio.run(mm.extract_video_frames("/nonexistent/video.mp4"))

    def test_successful_extraction(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = Path(tmpdir) / "video.mp4"
            video_file.write_bytes(b"fake video")
            frames_dir = Path(tmpdir) / "video_frames"
            frames_dir.mkdir()
            # Create fake frame files
            (frames_dir / "frame_001.jpg").write_bytes(b"frame1")
            (frames_dir / "frame_002.jpg").write_bytes(b"frame2")

            with patch.object(mm, "_command_exists", return_value=True), \
                 patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
                result = asyncio.run(mm.extract_video_frames(
                    str(video_file),
                    output_dir=str(frames_dir),
                    interval_seconds=5.0,
                    max_frames=2
                ))
            assert len(result) == 2


# ══════════════════════════════════════════════════════════════
# extract_audio_track() (387-417)
# ══════════════════════════════════════════════════════════════

class Extra_TestExtractAudioTrack:
    def test_ffmpeg_not_found(self):
        mm = _get_multimodal()
        with patch.object(mm, "_command_exists", return_value=False):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                asyncio.run(mm.extract_audio_track("/tmp/video.mp4"))

    def test_file_not_found(self):
        mm = _get_multimodal()
        with patch.object(mm, "_command_exists", return_value=True):
            with pytest.raises(FileNotFoundError):
                asyncio.run(mm.extract_audio_track("/nonexistent/file.mp4"))

    def test_successful_extraction(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = Path(tmpdir) / "video.mp4"
            video_file.write_bytes(b"fake video")
            expected_output = str(video_file.with_suffix(".wav"))

            with patch.object(mm, "_command_exists", return_value=True), \
                 patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
                result = asyncio.run(mm.extract_audio_track(str(video_file)))
            assert result == expected_output


# ══════════════════════════════════════════════════════════════
# transcribe_audio() (420-499)
# ══════════════════════════════════════════════════════════════

class Extra_TestTranscribeAudio:
    def test_file_not_found(self):
        mm = _get_multimodal()
        with pytest.raises(FileNotFoundError):
            asyncio.run(mm.transcribe_audio("/nonexistent/audio.wav"))

    def test_unsupported_provider(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = Path(tmpdir) / "audio.wav"
            audio_file.write_bytes(b"fake audio")
            with pytest.raises(ValueError, match="whisper"):
                asyncio.run(mm.transcribe_audio(str(audio_file), provider="openai_api"))

    def test_whisper_not_found(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = Path(tmpdir) / "audio.wav"
            audio_file.write_bytes(b"fake audio")
            with patch.object(mm, "_command_exists", return_value=False):
                result = asyncio.run(mm.transcribe_audio(str(audio_file)))
            assert result["success"] is False
            assert "Whisper CLI" in result["reason"]

    def test_whisper_success(self):
        mm = _get_multimodal()
        import json as _json
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = Path(tmpdir) / "audio.wav"
            audio_file.write_bytes(b"fake audio")

            # Mock whisper to create output JSON
            async def _fake_to_thread(func, *args):
                # Find the temp dir and create the output file
                pass

            with patch.object(mm, "_command_exists", return_value=True):
                with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
                    with patch("tempfile.TemporaryDirectory") as mock_tmpdir:
                        fake_tmpdir = Path(tmpdir) / "whisper_tmp"
                        fake_tmpdir.mkdir()
                        output_json = fake_tmpdir / "audio.json"
                        output_json.write_text(_json.dumps({
                            "text": "Merhaba dünya",
                            "language": "tr",
                            "segments": []
                        }), encoding="utf-8")
                        mock_tmpdir.return_value.__enter__ = MagicMock(return_value=str(fake_tmpdir))
                        mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
                        result = asyncio.run(mm.transcribe_audio(str(audio_file)))
            assert result["success"] is True
            assert result["text"] == "Merhaba dünya"

    def test_whisper_subprocess_error(self):
        mm = _get_multimodal()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = Path(tmpdir) / "audio.wav"
            audio_file.write_bytes(b"fake audio")

            error = subprocess.CalledProcessError(1, "whisper", stderr=b"error output")

            with patch.object(mm, "_command_exists", return_value=True):
                with patch("asyncio.to_thread", side_effect=error):
                    result = asyncio.run(mm.transcribe_audio(str(audio_file)))
            assert result["success"] is False


# ══════════════════════════════════════════════════════════════
# build_multimodal_context() (503-537)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildMultimodalContext:
    def test_basic_context(self):
        mm = _get_multimodal()
        result = mm.build_multimodal_context(
            media_kind="video",
            transcript={"text": "Merhaba", "language": "tr"},
        )
        assert "Merhaba" in result
        assert "tr" in result

    def test_transcript_with_reason(self):
        mm = _get_multimodal()
        result = mm.build_multimodal_context(
            media_kind="video",
            transcript={"text": "", "reason": "Bulunamadı"},
        )
        assert "Bulunamadı" in result

    def test_with_frame_analyses(self):
        mm = _get_multimodal()
        frames = [
            {"timestamp_seconds": 5.0, "analysis": "Bir kişi var"},
            {"timestamp_seconds": 10.0, "summary": "Sahne değişti"},
        ]
        result = mm.build_multimodal_context(media_kind="video", frame_analyses=frames)
        assert "5.0s" in result

    def test_with_extra_notes(self):
        mm = _get_multimodal()
        result = mm.build_multimodal_context(
            media_kind="audio",
            extra_notes="Önemli not"
        )
        assert "Önemli not" in result

    def test_no_transcript(self):
        mm = _get_multimodal()
        result = mm.build_multimodal_context(media_kind="image")
        assert "image" in result


# ══════════════════════════════════════════════════════════════
# build_scene_summary() (540-548)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildSceneSummary:
    def test_basic_summary(self):
        mm = _get_multimodal()
        frames = [
            {"timestamp_seconds": 0.0, "analysis": "Intro sahne"},
            {"timestamp_seconds": 5.0, "summary": "Diyalog başlıyor"},
        ]
        result = mm.build_scene_summary(frames)
        assert "Intro sahne" in result
        assert "Diyalog" in result

    def test_empty_frames(self):
        mm = _get_multimodal()
        result = mm.build_scene_summary([])
        assert result == ""

    def test_frames_without_summary(self):
        mm = _get_multimodal()
        result = mm.build_scene_summary([{"timestamp_seconds": 1.0}])
        assert result == ""


# ══════════════════════════════════════════════════════════════
# render_multimodal_document() (551-584)
# ══════════════════════════════════════════════════════════════

class Extra_TestRenderMultimodalDocument:
    def test_basic_render(self):
        mm = _get_multimodal()
        analysis = {
            "media_kind": "video",
            "transcript": {"text": "Merhaba"},
            "frame_analyses": [],
        }
        title, body = mm.render_multimodal_document(analysis, source="video.mp4")
        assert "video.mp4" in title or "Video" in title
        assert "Merhaba" in body

    def test_with_download_info(self):
        mm = _get_multimodal()
        analysis = {
            "media_kind": "video",
            "download": {"platform": "youtube", "resolved_url": "https://cdn.youtube.com/stream"},
        }
        title, body = mm.render_multimodal_document(
            analysis, source="https://youtube.com/watch?v=abc", title="Test Video"
        )
        assert "youtube" in body

    def test_with_analysis_text(self):
        mm = _get_multimodal()
        analysis = {
            "media_kind": "video",
            "analysis": "LLM analiz metni",
            "context": "Bağlam metni",
        }
        title, body = mm.render_multimodal_document(analysis, source="video.mp4")
        assert "LLM analiz" in body
        assert "Bağlam metni" in body


# ══════════════════════════════════════════════════════════════
# ingest_multimodal_analysis() (587-612)
# ══════════════════════════════════════════════════════════════

class Extra_TestIngestMultimodalAnalysis:
    def test_failed_analysis_not_ingested(self):
        mm = _get_multimodal()
        document_store = MagicMock()
        analysis = {"success": False}
        result = asyncio.run(mm.ingest_multimodal_analysis(
            document_store, analysis, source="video.mp4"
        ))
        assert result["success"] is False

    def test_successful_ingest(self):
        mm = _get_multimodal()
        document_store = MagicMock()
        document_store.add_document = AsyncMock(return_value="doc123")
        analysis = {
            "success": True,
            "media_kind": "video",
            "transcript": {"text": "Içerik"},
        }
        result = asyncio.run(mm.ingest_multimodal_analysis(
            document_store, analysis, source="video.mp4", title="Test"
        ))
        assert result["success"] is True
