import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_youtube_manager_module():
    saved = {name: sys.modules.get(name) for name in (
        "core", "core.multimodal", "core.vision", "managers.youtube_manager",
    )}

    core_pkg = types.ModuleType("core")
    multimodal_mod = types.ModuleType("core.multimodal")
    vision_mod = types.ModuleType("core.vision")

    class ExtractedFrame:
        def __init__(self, path: str, timestamp_seconds: float):
            self.path = path
            self.timestamp_seconds = timestamp_seconds

    async def _extract_video_frames(path, *, interval_seconds, max_frames, output_dir):
        return [
            ExtractedFrame(str(Path(output_dir) / "frame_001.jpg"), 0.0),
            ExtractedFrame(str(Path(output_dir) / "frame_002.jpg"), interval_seconds),
        ][:max_frames]

    def _build_multimodal_context(*, media_kind, transcript=None, frame_analyses=None, extra_notes=""):
        return f"kind={media_kind}; transcript={bool((transcript or {}).get('text'))}; frames={len(frame_analyses or [])}; notes={extra_notes}"

    class VisionPipeline:
        def __init__(self, llm_client, config=None):
            self.llm_client = llm_client
            self.config = config

        async def analyze(self, *, image_path=None, analysis_type="general", **_kwargs):
            return {"success": True, "analysis": f"{analysis_type}:{Path(image_path).name}"}

    multimodal_mod.ExtractedFrame = ExtractedFrame
    multimodal_mod.extract_video_frames = _extract_video_frames
    multimodal_mod.build_multimodal_context = _build_multimodal_context
    vision_mod.VisionPipeline = VisionPipeline
    core_pkg.multimodal = multimodal_mod
    core_pkg.vision = vision_mod

    sys.modules.update({
        "core": core_pkg,
        "core.multimodal": multimodal_mod,
        "core.vision": vision_mod,
    })

    try:
        spec = importlib.util.spec_from_file_location("managers.youtube_manager", ROOT / "managers" / "youtube_manager.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["managers.youtube_manager"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


yt_mod = _load_youtube_manager_module()
YouTubeManager = yt_mod.YouTubeManager


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url):
        self.requested.append(url)
        return self.responses.pop(0)


def test_extract_video_id_supports_watch_short_and_direct_id():
    assert YouTubeManager.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeManager.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_returns_empty_for_blank_and_invalid_inputs():
    assert YouTubeManager.extract_video_id("") == ""
    assert YouTubeManager.extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ") == ""
    assert YouTubeManager.extract_video_id("https://www.youtube.com/watch?v=short") == ""


def test_normalize_transcript_events_skips_invalid_pieces_and_empty_text():
    normalized = YouTubeManager._normalize_transcript_events(
        [
            "invalid-item",
            {"tStartMs": 0, "dDurationMs": 1000, "segs": "not-a-list"},
            {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "   "}]},
            {
                "tStartMs": 2000,
                "dDurationMs": 1500,
                "segs": [
                    {"utf8": "Merhaba &amp;"},
                    {"utf8": " dünya"},
                    "ignored-piece",
                ],
            },
        ]
    )

    assert normalized == {
        "text": "Merhaba & dünya",
        "segments": [
            {
                "start_seconds": 2.0,
                "duration_seconds": 1.5,
                "text": "Merhaba & dünya",
            }
        ],
    }


def test_fetch_transcript_returns_normalized_segments():
    client = _FakeClient([
        _Response(200, {
            "events": [
                {"tStartMs": 0, "dDurationMs": 1200, "segs": [{"utf8": "Merhaba "}]},
                {"tStartMs": 1200, "dDurationMs": 800, "segs": [{"utf8": "dünya"}]},
            ]
        })
    ])
    manager = YouTubeManager(http_client_factory=lambda **_kwargs: client)

    result = asyncio.run(manager.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr",)))

    assert result["success"] is True
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["language"] == "tr"
    assert result["text"] == "Merhaba dünya"
    assert result["segments"][0]["start_seconds"] == 0.0
    assert "lang=tr" in client.requested[0]


def test_fetch_transcript_returns_failure_when_no_caption_found():
    client = _FakeClient([
        _Response(404, {}),
        _Response(200, {"events": []}),
    ])
    manager = YouTubeManager(http_client_factory=lambda **_kwargs: client)

    result = asyncio.run(manager.fetch_transcript("https://youtu.be/dQw4w9WgXcQ", languages=("tr", "en")))

    assert result["success"] is False
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert "bulunamadı" in result["reason"]


def test_fetch_transcript_returns_failure_for_invalid_video_id():
    manager = YouTubeManager(http_client_factory=lambda **_kwargs: _FakeClient([]))

    result = asyncio.run(manager.fetch_transcript("not-a-valid-youtube-id"))

    assert result == {
        "success": False,
        "reason": "Geçerli YouTube video id bulunamadı.",
        "video_id": "",
    }


def test_analyze_video_file_uses_vision_pipeline_for_frames(tmp_path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    manager = YouTubeManager(llm_client=SimpleNamespace(provider="test"), config=SimpleNamespace())

    result = asyncio.run(
        manager.analyze_video_file(
            video_path,
            transcript={"text": "Video transkripti", "language": "tr"},
            analysis_type="ux_review",
            frame_interval_seconds=2.5,
            max_frames=2,
            extra_notes="cta analizi",
        )
    )

    assert result["success"] is True
    assert len(result["frame_analyses"]) == 2
    assert result["frame_analyses"][0]["analysis"] == "ux_review:frame_001.jpg"
    assert "frames=2" in result["context"]
    assert "cta analizi" in result["context"]


def test_analyze_video_file_returns_validation_failures(tmp_path):
    missing_file = tmp_path / "missing.mp4"
    manager_without_llm = YouTubeManager(config=SimpleNamespace())

    missing_file_result = asyncio.run(manager_without_llm.analyze_video_file(missing_file))
    assert missing_file_result == {
        "success": False,
        "reason": f"Video dosyası bulunamadı: {missing_file}",
    }

    existing_file = tmp_path / "sample.mp4"
    existing_file.write_bytes(b"video")

    missing_llm_result = asyncio.run(manager_without_llm.analyze_video_file(existing_file))
    assert missing_llm_result == {
        "success": False,
        "reason": "Vision analizi için llm_client gerekli.",
    }


def test_build_video_analysis_combines_transcript_and_frame_pipeline(tmp_path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    client = _FakeClient([
        _Response(200, {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Selam"}]}]})
    ])
    manager = YouTubeManager(
        llm_client=SimpleNamespace(provider="test"),
        config=SimpleNamespace(),
        http_client_factory=lambda **_kwargs: client,
    )

    result = asyncio.run(
        manager.build_video_analysis(
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_path=video_path,
            max_frames=1,
        )
    )

    assert result["success"] is True
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["transcript"]["text"] == "Selam"
    assert len(result["frame_analyses"]) == 1


def test_build_video_analysis_returns_underlying_analysis_failure(tmp_path):
    manager = YouTubeManager(llm_client=SimpleNamespace(provider="test"), config=SimpleNamespace())

    async def _fake_transcript(*_args, **_kwargs):
        return {"success": False, "video_id": "dQw4w9WgXcQ", "reason": "transcript disabled"}

    async def _fake_analyze(*_args, **_kwargs):
        return {"success": False, "reason": "Video dosyası bulunamadı: missing.mp4"}

    manager.fetch_transcript = _fake_transcript
    manager.analyze_video_file = _fake_analyze

    result = asyncio.run(
        manager.build_video_analysis(
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_path=tmp_path / "missing.mp4",
        )
    )

    assert result == {"success": False, "reason": "Video dosyası bulunamadı: missing.mp4"}
