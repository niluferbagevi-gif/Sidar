from __future__ import annotations

import asyncio
from pathlib import Path
import importlib.machinery
import sys
import types

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.AsyncClient = AsyncClient
    fake_httpx.__spec__ = importlib.machinery.ModuleSpec("httpx", loader=None)
    sys.modules["httpx"] = fake_httpx

from core.multimodal import ExtractedFrame
from managers.youtube_manager import YouTubeManager


def test_extract_video_id_supports_multiple_youtube_url_patterns() -> None:
    assert YouTubeManager.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://example.com/nope") == ""


def test_normalize_transcript_events_decodes_html_and_timestamps() -> None:
    payload = [
        {"tStartMs": 1200, "dDurationMs": 800, "segs": [{"utf8": "Merhaba &amp; dünya"}]},
        {"tStartMs": 2200, "dDurationMs": 1000, "segs": [{"utf8": "!"}]},
    ]

    normalized = YouTubeManager._normalize_transcript_events(payload)

    assert normalized["text"] == "Merhaba & dünya !"
    assert normalized["segments"][0]["start_seconds"] == 1.2
    assert normalized["segments"][0]["duration_seconds"] == 0.8


def test_analyze_video_file_returns_error_when_file_or_llm_missing(tmp_path: Path) -> None:
    manager = YouTubeManager(llm_client=None, config=None)

    missing = asyncio.run(manager.analyze_video_file(tmp_path / "missing.mp4"))
    assert missing["success"] is False
    assert "bulunamadı" in missing["reason"]

    sample = tmp_path / "sample.mp4"
    sample.write_text("dummy")
    no_llm = asyncio.run(manager.analyze_video_file(sample))
    assert no_llm["success"] is False
    assert "llm_client" in no_llm["reason"]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses: list[_FakeResponse], *args, **kwargs) -> None:
        self.responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url: str):
        return self.responses.pop(0)


def test_fetch_transcript_tries_fallback_language_and_succeeds() -> None:
    responses = [
        _FakeResponse(404, {}),
        _FakeResponse(200, {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Merhaba"}]}]}),
    ]
    manager = YouTubeManager(http_client_factory=lambda **kwargs: _FakeAsyncClient(responses, **kwargs))

    result = asyncio.run(manager.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr", "en")))

    assert result["success"] is True
    assert result["language"] == "en"
    assert result["text"] == "Merhaba"


def test_fetch_transcript_returns_error_for_quota_or_private_like_statuses() -> None:
    responses = [_FakeResponse(429, {}), _FakeResponse(403, {})]
    manager = YouTubeManager(http_client_factory=lambda **kwargs: _FakeAsyncClient(responses, **kwargs))

    result = asyncio.run(manager.fetch_transcript("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    assert result["success"] is False
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert "bulunamadı" in result["reason"]


def test_analyze_video_file_success_builds_context(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"binary")

    manager = YouTubeManager(llm_client=object(), config=None)

    async def _fake_extract_video_frames(*_args, **_kwargs):
        return [ExtractedFrame(path="frame-1.jpg", timestamp_seconds=1.5)]

    class _FakeVision:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def analyze(self, **_kwargs):
            return {"success": True, "analysis": "ürün logosu görünür"}

    monkeypatch.setattr("managers.youtube_manager.extract_video_frames", _fake_extract_video_frames)
    monkeypatch.setattr("managers.youtube_manager.VisionPipeline", _FakeVision)
    monkeypatch.setattr("managers.youtube_manager.build_multimodal_context", lambda **_kwargs: "özet bağlam")

    result = asyncio.run(manager.analyze_video_file(video_path=video, transcript={"text": "merhaba"}))

    assert result["success"] is True
    assert result["context"] == "özet bağlam"
    assert result["frame_analyses"][0]["success"] is True


def test_build_video_analysis_returns_analyze_error(monkeypatch, tmp_path: Path) -> None:
    manager = YouTubeManager(llm_client=object(), config=None)

    async def _fake_fetch(*_args, **_kwargs):
        return {"success": False, "reason": "transcript yok"}

    async def _fake_analyze(*_args, **_kwargs):
        return {"success": False, "reason": "video parse edilemedi"}

    monkeypatch.setattr(manager, "fetch_transcript", _fake_fetch)
    monkeypatch.setattr(manager, "analyze_video_file", _fake_analyze)

    result = asyncio.run(
        manager.build_video_analysis(video_url="https://youtu.be/dQw4w9WgXcQ", video_path=tmp_path / "missing.mp4")
    )

    assert result["success"] is False
    assert "parse" in result["reason"]


def test_fetch_transcript_invalid_video_id_short_circuit() -> None:
    manager = YouTubeManager()
    result = asyncio.run(manager.fetch_transcript("bad"))
    assert result["success"] is False
    assert result["video_id"] == ""


def test_build_video_analysis_success_includes_video_metadata(monkeypatch, tmp_path: Path) -> None:
    manager = YouTubeManager(llm_client=object(), config=None)

    async def _fake_fetch(*_args, **_kwargs):
        return {"success": True, "text": "ok"}

    async def _fake_analyze(*_args, **_kwargs):
        return {"success": True, "context": "ctx", "frame_analyses": []}

    monkeypatch.setattr(manager, "fetch_transcript", _fake_fetch)
    monkeypatch.setattr(manager, "analyze_video_file", _fake_analyze)

    result = asyncio.run(
        manager.build_video_analysis(
            video_url="https://youtu.be/dQw4w9WgXcQ",
            video_path=tmp_path / "demo.mp4",
        )
    )

    assert result["success"] is True
    assert result["video_url"].startswith("https://")
    assert result["video_id"] == "dQw4w9WgXcQ"
