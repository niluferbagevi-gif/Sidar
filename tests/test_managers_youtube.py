"""
managers/youtube_manager.py için birim testleri.
extract_video_id, _normalize_transcript_events, constructor.
"""
from __future__ import annotations

import sys
import types
import asyncio
from unittest.mock import AsyncMock, patch


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

    def test_non_list_segs_skipped(self):
        yt = _get_yt()
        events = [{"tStartMs": 0, "dDurationMs": 1000, "segs": "invalid"}]
        result = yt.YouTubeManager._normalize_transcript_events(events)  # type: ignore[arg-type]
        assert result["text"] == ""
        assert result["segments"] == []


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

    def test_fetch_transcript_invalid_video_id_returns_failure(self):
        yt = _get_yt()
        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: None)

        result = asyncio.run(mgr.fetch_transcript("not-a-youtube-id"))

        assert result["success"] is False
        assert "video id" in result["reason"].lower()

    def test_fetch_transcript_all_languages_empty_returns_failure_reason(self):
        yt = _get_yt()

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "   "}]}]}

        class _FakeClient:
            async def get(self, url):
                return _Resp()

        class _FakeClientCM:
            async def __aenter__(self):
                return _FakeClient()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: _FakeClientCM())
        result = asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr",)))

        assert result["success"] is False
        assert "bulunamadı" in result["reason"].lower()

    def test_fetch_transcript_404_then_200_falls_back_to_next_language(self):
        yt = _get_yt()

        class _Resp404:
            status_code = 404

            @staticmethod
            def json():
                return {}

        class _Resp200:
            status_code = 200

            @staticmethod
            def json():
                return {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello"}]}]}

        responses = [_Resp404(), _Resp200()]

        class _FakeClient:
            async def get(self, url):
                return responses.pop(0)

        class _FakeClientCM:
            async def __aenter__(self):
                return _FakeClient()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: _FakeClientCM())
        result = asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr", "en")))

        assert result["success"] is True
        assert result["language"] == "en"
        assert "Hello" in result["text"]

    def test_fetch_transcript_500_returns_failure(self):
        yt = _get_yt()

        class _Resp500:
            status_code = 500

            @staticmethod
            def json():
                return {"error": "server error"}

        class _FakeClient:
            async def get(self, url):
                return _Resp500()

        class _FakeClientCM:
            async def __aenter__(self):
                return _FakeClient()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: _FakeClientCM())
        result = asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr",)))

        assert result["success"] is False
        assert "bulunamadı" in result["reason"].lower()

    def test_fetch_transcript_timeout_exception_propagates(self):
        yt = _get_yt()
        httpx = __import__("httpx")

        class _FakeClient:
            async def get(self, _url):
                raise httpx.TimeoutException("timed out")

        class _FakeClientCM:
            async def __aenter__(self):
                return _FakeClient()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mgr = yt.YouTubeManager(http_client_factory=lambda **kwargs: _FakeClientCM())
        import pytest
        with pytest.raises(httpx.TimeoutException):
            asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ"))

    def test_fetch_transcript_uses_patch_with_httpx_client(self):
        yt = _get_yt()

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"events": [{"tStartMs": 0, "dDurationMs": 700, "segs": [{"utf8": "Patch test"}]}]}

        get_mock = AsyncMock(return_value=_Resp())
        client_mock = AsyncMock()
        client_mock.get = get_mock

        cm_mock = AsyncMock()
        cm_mock.__aenter__.return_value = client_mock
        cm_mock.__aexit__.return_value = False

        with patch.object(yt.httpx, "AsyncClient", return_value=cm_mock):
            mgr = yt.YouTubeManager(http_client_factory=yt.httpx.AsyncClient)
            result = asyncio.run(mgr.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr",)))

        assert result["success"] is True
        assert result["language"] == "tr"
        assert "Patch test" in result["text"]
        get_mock.assert_awaited_once()


class TestYouTubeVideoAnalysisBranches:
    def test_analyze_video_file_missing_path_returns_failure(self, tmp_path):
        yt = _get_yt()
        mgr = yt.YouTubeManager(llm_client=object())
        missing = tmp_path / "missing.mp4"

        result = asyncio.run(mgr.analyze_video_file(missing))

        assert result["success"] is False
        assert "bulunamadı" in result["reason"].lower()

    def test_analyze_video_file_without_llm_client_returns_failure(self, tmp_path):
        yt = _get_yt()
        video = tmp_path / "sample.mp4"
        video.write_bytes(b"fake")
        mgr = yt.YouTubeManager(llm_client=None)

        result = asyncio.run(mgr.analyze_video_file(video))

        assert result["success"] is False
        assert "llm_client gerekli" in result["reason"].lower()

    def test_analyze_video_file_success_builds_context(self, tmp_path, monkeypatch):
        yt = _get_yt()
        video = tmp_path / "sample.mp4"
        video.write_bytes(b"fake")

        class _Frame:
            def __init__(self, path: str, ts: float):
                self.path = path
                self.timestamp_seconds = ts

        async def _fake_extract(*args, **kwargs):
            return [_Frame("f1.png", 1.0), _Frame("f2.png", 2.5)]

        class _FakeVision:
            def __init__(self, llm, cfg):
                self.llm = llm
                self.cfg = cfg

            async def analyze(self, image_path, analysis_type="general"):
                return {"success": True, "analysis": f"{analysis_type}:{image_path}"}

        def _fake_context(**kwargs):
            return {"kind": kwargs["media_kind"], "count": len(kwargs["frame_analyses"])}

        monkeypatch.setattr(yt, "extract_video_frames", _fake_extract)
        monkeypatch.setattr(yt, "VisionPipeline", _FakeVision)
        monkeypatch.setattr(yt, "build_multimodal_context", _fake_context)

        mgr = yt.YouTubeManager(llm_client=object())
        result = asyncio.run(
            mgr.analyze_video_file(
                video,
                analysis_type="marketing",
                frame_interval_seconds=3.0,
                max_frames=2,
                extra_notes="not",
            )
        )

        assert result["success"] is True
        assert result["video_path"] == str(video)
        assert len(result["frame_analyses"]) == 2
        assert result["context"]["count"] == 2

    def test_build_video_analysis_returns_failure_when_file_analysis_fails(self, tmp_path, monkeypatch):
        yt = _get_yt()
        video = tmp_path / "sample.mp4"
        video.write_bytes(b"fake")
        mgr = yt.YouTubeManager(llm_client=object())

        monkeypatch.setattr(
            mgr,
            "fetch_transcript",
            types.MethodType(lambda self, *a, **k: asyncio.sleep(0, result={"success": True, "text": "ok"}), mgr),
        )
        monkeypatch.setattr(
            mgr,
            "analyze_video_file",
            types.MethodType(lambda self, *a, **k: asyncio.sleep(0, result={"success": False, "reason": "boom"}), mgr),
        )

        result = asyncio.run(mgr.build_video_analysis(video_url="https://youtu.be/dQw4w9WgXcQ", video_path=video))
        assert result["success"] is False
        assert result["reason"] == "boom"

    def test_build_video_analysis_success_includes_video_metadata(self, tmp_path, monkeypatch):
        yt = _get_yt()
        video = tmp_path / "sample.mp4"
        video.write_bytes(b"fake")
        mgr = yt.YouTubeManager(llm_client=object())

        monkeypatch.setattr(
            mgr,
            "fetch_transcript",
            types.MethodType(
                lambda self, *a, **k: asyncio.sleep(0, result={"success": True, "video_id": "dQw4w9WgXcQ", "text": "t"}),
                mgr,
            ),
        )
        monkeypatch.setattr(
            mgr,
            "analyze_video_file",
            types.MethodType(lambda self, *a, **k: asyncio.sleep(0, result={"success": True, "frame_analyses": [], "context": {}}), mgr),
        )

        result = asyncio.run(mgr.build_video_analysis(video_url="https://youtu.be/dQw4w9WgXcQ", video_path=video))
        assert result["success"] is True
        assert result["video_url"] == "https://youtu.be/dQw4w9WgXcQ"
        assert result["video_id"] == "dQw4w9WgXcQ"

    def test_analyze_video_file_with_patch_mocks_external_dependencies(self, tmp_path):
        yt = _get_yt()
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")

        class _Frame:
            def __init__(self, path: str, ts: float):
                self.path = path
                self.timestamp_seconds = ts

        fake_frames = [_Frame("f1.png", 1.2)]

        vision_instance = AsyncMock()
        vision_instance.analyze = AsyncMock(return_value={"success": True, "analysis": "ok"})

        with (
            patch.object(yt, "extract_video_frames", AsyncMock(return_value=fake_frames)),
            patch.object(yt, "VisionPipeline", return_value=vision_instance),
            patch.object(yt, "build_multimodal_context", return_value={"kind": "video", "count": 1}),
        ):
            mgr = yt.YouTubeManager(llm_client=object())
            result = asyncio.run(mgr.analyze_video_file(video, analysis_type="general"))

        assert result["success"] is True
        assert result["frame_analyses"][0]["analysis"] == "ok"
        assert result["context"]["count"] == 1
