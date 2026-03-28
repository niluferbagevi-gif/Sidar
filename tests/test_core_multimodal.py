"""
core/multimodal.py için birim testleri.
detect_media_kind, is_remote_media_source, detect_video_platform,
extract_youtube_video_id, _normalize_youtube_transcript_events,
_guess_suffix saf fonksiyonlarını kapsar.
"""
from __future__ import annotations

import sys


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
