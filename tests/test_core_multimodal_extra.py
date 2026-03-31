"""
core/multimodal.py için ek testler — eksik satırları kapsar.
"""
from __future__ import annotations

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

class TestHelperFunctions:
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

class TestDetectMediaKind:
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

class TestIsRemoteMediaSource:
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

class TestDetectVideoPlatform:
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

class TestExtractYoutubeVideoId:
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

class TestNormalizeYoutubeTranscriptEvents:
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

class TestFetchYoutubeTranscript:
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

class TestDownloadRemoteMedia:
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

class TestExtractVideoFrames:
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

class TestExtractAudioTrack:
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

class TestTranscribeAudio:
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

class TestBuildMultimodalContext:
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

class TestBuildSceneSummary:
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

class TestRenderMultimodalDocument:
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

class TestIngestMultimodalAnalysis:
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
