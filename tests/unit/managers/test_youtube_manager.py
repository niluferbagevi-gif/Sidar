from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

if "httpx" not in sys.modules:
    sys.modules["httpx"] = SimpleNamespace(AsyncClient=object)

from managers.youtube_manager import YouTubeManager


class _DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, responses_by_language: dict[str, _DummyResponse]):
        self._responses = responses_by_language
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        self.calls.append(url)
        language = url.split("lang=")[1].split("&", 1)[0]
        return self._responses[language]


class _DummyClientFactory:
    def __init__(self, responses_by_language: dict[str, _DummyResponse]):
        self.responses_by_language = responses_by_language
        self.last_kwargs: dict[str, object] = {}
        self.client: _DummyClient | None = None

    def __call__(self, **kwargs):
        self.last_kwargs = kwargs
        self.client = _DummyClient(self.responses_by_language)
        return self.client


def test_extract_video_id_variants():
    video_id = "dQw4w9WgXcQ"
    manager = YouTubeManager()

    assert manager.extract_video_id(video_id) == video_id
    assert manager.extract_video_id(f"https://youtu.be/{video_id}") == video_id
    assert manager.extract_video_id(f"https://www.youtube.com/watch?v={video_id}") == video_id
    assert manager.extract_video_id(f"https://www.youtube.com/shorts/{video_id}") == video_id
    assert manager.extract_video_id(f"https://www.youtube.com/embed/{video_id}") == video_id
    assert manager.extract_video_id(f"https://www.youtube.com/live/{video_id}") == video_id


def test_extract_video_id_invalid_inputs_return_empty():
    manager = YouTubeManager()

    assert manager.extract_video_id("") == ""
    assert manager.extract_video_id("    ") == ""
    assert manager.extract_video_id("not-a-video-id") == ""
    assert manager.extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ") == ""
    assert manager.extract_video_id("https://www.youtube.com/watch?v=short") == ""
    assert manager.extract_video_id("https://www.youtube.com/channel/UC1234567890") == ""


def test_timedtext_url_and_normalize_transcript_events():
    url = YouTubeManager._timedtext_url("dQw4w9WgXcQ", "tr")
    assert url == "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=tr&fmt=json3"

    normalized = YouTubeManager._normalize_transcript_events(
        [
            {
                "tStartMs": 1500,
                "dDurationMs": 2500,
                "segs": [{"utf8": "Merhaba "}, {"utf8": "dünya&amp;evren"}],
            },
            {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "  ikinci satır "}]},
            {"segs": "invalid"},
            "invalid-item",
            {"tStartMs": 5000, "dDurationMs": 1000, "segs": [{"utf8": "   "}]},
        ]
    )

    assert normalized["text"] == "Merhaba dünya&evren ikinci satır"
    assert normalized["segments"] == [
        {"start_seconds": 1.5, "duration_seconds": 2.5, "text": "Merhaba dünya&evren"},
        {"start_seconds": 4.0, "duration_seconds": 1.0, "text": "ikinci satır"},
    ]


def test_fetch_transcript_invalid_video_id_short_circuit():
    manager = YouTubeManager()

    result = asyncio.run(manager.fetch_transcript("bad"))

    assert result == {
        "success": False,
        "reason": "Geçerli YouTube video id bulunamadı.",
        "video_id": "",
    }


def test_fetch_transcript_uses_language_fallback_and_custom_timeout():
    responses = {
        "tr": _DummyResponse(404, {}),
        "en": _DummyResponse(
            200, {"events": [{"tStartMs": 0, "dDurationMs": 1200, "segs": [{"utf8": "Hello"}]}]}
        ),
    }
    factory = _DummyClientFactory(responses)
    config = SimpleNamespace(YOUTUBE_TRANSCRIPT_TIMEOUT=33)
    manager = YouTubeManager(config=config, http_client_factory=factory)

    result = asyncio.run(manager.fetch_transcript("https://youtu.be/dQw4w9WgXcQ"))

    assert result["success"] is True
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["language"] == "en"
    assert result["text"] == "Hello"
    assert factory.last_kwargs == {"timeout": 33.0, "follow_redirects": True}
    assert factory.client is not None
    assert "lang=tr" in factory.client.calls[0]
    assert "lang=en" in factory.client.calls[1]


def test_fetch_transcript_returns_not_found_when_no_language_has_text():
    responses = {
        "tr": _DummyResponse(200, {"events": [{"segs": [{"utf8": "   "}]}]}),
        "en": _DummyResponse(200, {"events": "not-a-list"}),
    }
    manager = YouTubeManager(http_client_factory=_DummyClientFactory(responses))

    result = asyncio.run(manager.fetch_transcript("dQw4w9WgXcQ", languages=("tr", "en")))

    assert result == {
        "success": False,
        "video_id": "dQw4w9WgXcQ",
        "language": "",
        "text": "",
        "segments": [],
        "reason": "YouTube transcript bulunamadı veya boş döndü.",
    }


def test_analyze_video_file_errors_for_missing_path_and_missing_llm(tmp_path):
    manager_without_llm = YouTubeManager()

    missing_result = asyncio.run(manager_without_llm.analyze_video_file(tmp_path / "missing.mp4"))
    assert missing_result["success"] is False
    assert "Video dosyası bulunamadı" in missing_result["reason"]

    existing_file = tmp_path / "video.mp4"
    existing_file.write_bytes(b"fake")
    no_llm_result = asyncio.run(manager_without_llm.analyze_video_file(existing_file))

    assert no_llm_result == {"success": False, "reason": "Vision analizi için llm_client gerekli."}


def test_analyze_video_file_success_flow(monkeypatch, tmp_path):
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"fake")
    llm_client = object()
    manager = YouTubeManager(llm_client=llm_client, config=SimpleNamespace(ENABLE_VISION=True))

    extracted_frames = [
        SimpleNamespace(path=str(tmp_path / "f1.jpg"), timestamp_seconds=1.5),
        SimpleNamespace(path=str(tmp_path / "f2.jpg"), timestamp_seconds=3.0),
    ]

    captured_extract_kwargs: dict[str, object] = {}

    async def fake_extract_video_frames(source, *, interval_seconds, max_frames, output_dir):
        captured_extract_kwargs.update(
            {
                "source": source,
                "interval_seconds": interval_seconds,
                "max_frames": max_frames,
                "output_dir": output_dir,
            }
        )
        return extracted_frames

    class _FakeVisionPipeline:
        def __init__(self, llm, config):
            self.llm = llm
            self.config = config

        async def analyze(self, image_path, analysis_type):
            return {
                "success": image_path.endswith("f1.jpg"),
                "analysis": f"analysis-{Path(image_path).stem}",
            }

    def fake_context_builder(*, media_kind, transcript, frame_analyses, extra_notes):
        return {
            "media_kind": media_kind,
            "transcript": transcript,
            "count": len(frame_analyses),
            "notes": extra_notes,
        }

    monkeypatch.setattr("managers.youtube_manager.extract_video_frames", fake_extract_video_frames)
    monkeypatch.setattr("managers.youtube_manager.VisionPipeline", _FakeVisionPipeline)
    monkeypatch.setattr("managers.youtube_manager.build_multimodal_context", fake_context_builder)

    transcript = {"success": True, "text": "hello"}
    result = asyncio.run(
        manager.analyze_video_file(
            video_file,
            transcript=transcript,
            analysis_type="accessibility",
            frame_interval_seconds=2.0,
            max_frames=4,
            extra_notes="extra",
        )
    )

    assert result["success"] is True
    assert result["video_path"] == str(video_file)
    assert result["transcript"] == transcript
    assert result["frame_analyses"] == [
        {
            "timestamp_seconds": 1.5,
            "frame_path": str(tmp_path / "f1.jpg"),
            "analysis": "analysis-f1",
            "success": True,
        },
        {
            "timestamp_seconds": 3.0,
            "frame_path": str(tmp_path / "f2.jpg"),
            "analysis": "analysis-f2",
            "success": False,
        },
    ]
    assert result["context"] == {
        "media_kind": "video",
        "transcript": transcript,
        "count": 2,
        "notes": "extra",
    }
    assert captured_extract_kwargs == {
        "source": video_file,
        "interval_seconds": 2.0,
        "max_frames": 4,
        "output_dir": tmp_path / "clip_yt_frames",
    }


def test_build_video_analysis_propagates_failure(monkeypatch):
    manager = YouTubeManager()

    async def fake_fetch(video_url, *, languages=None):
        return {
            "success": False,
            "video_id": "x",
            "reason": "no transcript",
            "languages": languages,
        }

    async def fake_analyze(video_path, **kwargs):
        return {
            "success": False,
            "reason": f"cannot analyze {video_path}",
            "transcript": kwargs.get("transcript"),
        }

    monkeypatch.setattr(manager, "fetch_transcript", fake_fetch)
    monkeypatch.setattr(manager, "analyze_video_file", fake_analyze)

    result = asyncio.run(
        manager.build_video_analysis(
            video_url="https://youtu.be/dQw4w9WgXcQ", video_path="/tmp/v.mp4"
        )
    )

    assert result == {
        "success": False,
        "reason": "cannot analyze /tmp/v.mp4",
        "transcript": {
            "success": False,
            "video_id": "x",
            "reason": "no transcript",
            "languages": None,
        },
    }


def test_build_video_analysis_success_adds_video_identity(monkeypatch):
    manager = YouTubeManager()

    async def fake_fetch(video_url, *, languages=None):
        return {
            "success": True,
            "text": "ok",
            "language": "tr",
            "video_url": video_url,
            "languages": languages,
        }

    async def fake_analyze(video_path, **kwargs):
        return {
            "success": True,
            "video_path": str(video_path),
            "frame_analyses": [],
            "context": {"ok": True},
            "transcript": kwargs.get("transcript"),
        }

    monkeypatch.setattr(manager, "fetch_transcript", fake_fetch)
    monkeypatch.setattr(manager, "analyze_video_file", fake_analyze)

    result = asyncio.run(
        manager.build_video_analysis(
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_path="/tmp/v.mp4",
            languages=("en",),
        )
    )

    assert result["success"] is True
    assert result["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["transcript"]["languages"] == ("en",)


def test_youtube_manager_test_module_bootstrap_injects_httpx_stub_when_missing():
    actual_httpx = sys.modules["httpx"]
    sys.modules["httpx"] = None

    original_httpx = sys.modules.pop("httpx", None)
    try:
        module = sys.modules[__name__]
        importlib.reload(module)
        injected = sys.modules.get("httpx")
        assert injected is not None
        assert hasattr(injected, "AsyncClient")
    finally:
        assert original_httpx is None
        sys.modules["httpx"] = SimpleNamespace(AsyncClient=object)
        module = sys.modules[__name__]
        importlib.reload(module)
        sys.modules["httpx"] = actual_httpx


def test_youtube_manager_test_module_bootstrap_restores_original_httpx_module():
    actual_httpx = sys.modules["httpx"]
    original_httpx = SimpleNamespace(AsyncClient=object, marker="original")
    sys.modules["httpx"] = original_httpx

    captured_original = sys.modules.pop("httpx", None)
    try:
        module = sys.modules[__name__]
        importlib.reload(module)
        injected = sys.modules.get("httpx")
        assert injected is not None
        assert hasattr(injected, "AsyncClient")
    finally:
        sys.modules["httpx"] = captured_original
        module = sys.modules[__name__]
        importlib.reload(module)
        sys.modules["httpx"] = actual_httpx
