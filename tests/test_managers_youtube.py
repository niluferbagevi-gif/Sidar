"""
managers/youtube_manager.py için birim testleri.
extract_video_id, _normalize_transcript_events, constructor.
"""
from __future__ import annotations

import sys
import types
import asyncio


def _get_yt():
    # Stub core.multimodal and core.vision to avoid heavy imports
    if "core.multimodal" not in sys.modules:
        mm_stub = types.ModuleType("core.multimodal")
        mm_stub.ExtractedFrame = object
        mm_stub.build_multimodal_context = None
        mm_stub.extract_video_frames = None
        sys.modules["core.multimodal"] = mm_stub
    if "core.vision" not in sys.modules:
        vis_stub = types.ModuleType("core.vision")
        vis_stub.VisionPipeline = object
        sys.modules["core.vision"] = vis_stub

    if "managers.youtube_manager" in sys.modules:
        del sys.modules["managers.youtube_manager"]
    import managers.youtube_manager as yt
    return yt


# ══════════════════════════════════════════════════════════════
# extract_video_id
# ══════════════════════════════════════════════════════════════

class TestExtractVideoId:
    def test_bare_11char_id(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_live_url(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_empty_string_returns_empty(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("") == ""

    def test_invalid_url_returns_empty(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("https://notYouTube.com/video/abc") == ""

    def test_too_short_id_returns_empty(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("short") == ""

    def test_too_long_id_returns_empty(self):
        yt = _get_yt()
        assert yt.YouTubeManager.extract_video_id("x" * 12) == ""


# ══════════════════════════════════════════════════════════════
# _normalize_transcript_events
# ══════════════════════════════════════════════════════════════

class TestNormalizeTranscriptEvents:
    def test_empty_list(self):
        yt = _get_yt()
        result = yt.YouTubeManager._normalize_transcript_events([])
        assert result["text"] == ""
        assert result["segments"] == []

    def test_none_input(self):
        yt = _get_yt()
        result = yt.YouTubeManager._normalize_transcript_events(None)  # type: ignore
        assert result["text"] == ""

    def test_basic_event(self):
        yt = _get_yt()
        events = [
            {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hello"}]},
        ]
        result = yt.YouTubeManager._normalize_transcript_events(events)
        assert "Hello" in result["text"]
        assert len(result["segments"]) == 1

    def test_segment_timing(self):
        yt = _get_yt()
        events = [
            {"tStartMs": 1500, "dDurationMs": 3000, "segs": [{"utf8": "world"}]},
        ]
        result = yt.YouTubeManager._normalize_transcript_events(events)
        seg = result["segments"][0]
        assert seg["start_seconds"] == 1.5
        assert seg["duration_seconds"] == 3.0

    def test_multiple_segs_joined(self):
        yt = _get_yt()
        events = [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "foo"}, {"utf8": "bar"}]},
        ]
        result = yt.YouTubeManager._normalize_transcript_events(events)
        assert "foobar" in result["text"]

    def test_html_entities_unescaped(self):
        yt = _get_yt()
        events = [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "1 &amp; 2"}]},
        ]
        result = yt.YouTubeManager._normalize_transcript_events(events)
        assert "&amp;" not in result["text"]
        assert "1 & 2" in result["text"]

    def test_empty_text_events_skipped(self):
        yt = _get_yt()
        events = [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "  "}]},
        ]
        result = yt.YouTubeManager._normalize_transcript_events(events)
        assert result["segments"] == []

    def test_non_dict_items_skipped(self):
        yt = _get_yt()
        result = yt.YouTubeManager._normalize_transcript_events(["bad", 42])  # type: ignore
        assert result["text"] == ""


# ══════════════════════════════════════════════════════════════
# YouTubeManager constructor
# ══════════════════════════════════════════════════════════════

class TestYouTubeManagerInit:
    def test_default_timeout(self):
        yt = _get_yt()
        mgr = yt.YouTubeManager()
        assert mgr.transcript_timeout == yt.YouTubeManager.TRANSCRIPT_TIMEOUT

    def test_config_sets_timeout(self):
        yt = _get_yt()

        class _Cfg:
            YOUTUBE_TRANSCRIPT_TIMEOUT = 30.0

        mgr = yt.YouTubeManager(config=_Cfg())
        assert mgr.transcript_timeout == 30.0

    def test_default_languages(self):
        yt = _get_yt()
        mgr = yt.YouTubeManager()
        assert "tr" in mgr.DEFAULT_LANGUAGES
        assert "en" in mgr.DEFAULT_LANGUAGES


class TestYouTubeApiMocking:
    def test_fetch_transcript_uses_mocked_http_client(self):
        yt = _get_yt()

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Merhaba"}]}]}

        class _FakeClient:
            async def get(self, url):
                return _Resp()

        class _FakeClientCM:
            async def __aenter__(self):
                return _FakeClient()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: _FakeClientCM())
        result = asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ"))

        assert result["success"] is True
        assert result["language"] in ("tr", "en")
        assert "Merhaba" in result["text"]
