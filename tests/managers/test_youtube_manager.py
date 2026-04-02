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
