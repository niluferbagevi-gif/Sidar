from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = type("AsyncClient", (), {})
    sys.modules["httpx"] = fake_httpx

import core.multimodal as multimodal


class _Resp:
    def __init__(self, status_code: int = 200, payload=None, content: bytes = b"data", headers=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")


class _Client:
    def __init__(self, responses, *args, **kwargs) -> None:
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url: str):
        return self._responses.pop(0)


class _Store:
    async def add_document(self, **kwargs):
        self.last = kwargs
        return "doc-1"


def test_basic_media_helpers_variants(tmp_path: Path) -> None:
    f = tmp_path / "a.unknown"
    f.write_bytes(b"x")
    assert multimodal.detect_media_kind(mime_type="image/png") == "image"
    assert multimodal.detect_media_kind(path=f) == "unknown"
    assert multimodal.is_remote_media_source("https://a") is True
    assert multimodal.detect_video_platform("https://vimeo.com/1") == "vimeo"
    assert multimodal.detect_video_platform("https://loom.com/share/x") == "loom"
    assert multimodal.extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert multimodal.extract_youtube_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert multimodal.extract_youtube_video_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert multimodal.extract_youtube_video_id("https://youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_normalize_events_skips_invalid_items() -> None:
    out = multimodal._normalize_youtube_transcript_events(
        [None, {"segs": "bad"}, {"segs": [{"utf8": "A"}], "tStartMs": 10, "dDurationMs": 20}]
    )
    assert out["text"] == "A"
    assert out["segments"][0]["duration_seconds"] == 0.02


def test_fetch_youtube_transcript_success_second_language() -> None:
    responses = [
        _Resp(200, {"events": []}),
        _Resp(200, {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "ok"}]}]}),
    ]
    result = asyncio.run(
        multimodal.fetch_youtube_transcript(
            "https://youtu.be/dQw4w9WgXcQ",
            languages=("tr", "en"),
            http_client_factory=lambda **kwargs: _Client(responses, **kwargs),
        )
    )
    assert result["success"] is True
    assert result["language"] == "en"


def test_download_remote_media_variants(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError):
        asyncio.run(multimodal.download_remote_media("file:///tmp/x", output_dir=tmp_path))

    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "yt-dlp")

    async def _touch_file(fn, command):
        _ = fn, command
        (tmp_path / "abc.mp4").write_bytes(b"x")
        return None

    monkeypatch.setattr(multimodal.asyncio, "to_thread", _touch_file)
    yt = asyncio.run(multimodal.download_remote_media("https://youtu.be/dQw4w9WgXcQ", output_dir=tmp_path))
    assert yt.platform == "youtube"

    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)
    plain = asyncio.run(
        multimodal.download_remote_media(
            "https://example.com/file.mp3",
            output_dir=tmp_path,
            http_client_factory=lambda **kwargs: _Client(
                [_Resp(200, payload={}, content=b"abc", headers={"content-type": "audio/mpeg"})], **kwargs
            ),
        )
    )
    assert plain.mime_type == "audio/mpeg"


def test_resolve_and_materialize_remote_media(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError):
        asyncio.run(multimodal.resolve_remote_media_stream("x"))

    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name in {"yt-dlp", "ffmpeg"})

    async def _fake_to_thread(fn, command):
        _ = fn
        if "--dump-single-json" in command:
            return "{bad-json"
        if "-g" in command:
            return "https://cdn.example/stream\n"
        (tmp_path / "youtube_stream.mp4").write_bytes(b"x")
        return ""

    monkeypatch.setattr(multimodal.asyncio, "to_thread", _fake_to_thread)
    stream = asyncio.run(multimodal.resolve_remote_media_stream("https://youtu.be/dQw4w9WgXcQ"))
    assert stream["resolved_url"].startswith("https://cdn")

    built = asyncio.run(
        multimodal.materialize_remote_media_for_ffmpeg(
            "https://youtu.be/dQw4w9WgXcQ", output_dir=tmp_path, mime_type="video/mp4", max_duration_seconds=3
        )
    )
    assert built.platform == "youtube"


def test_extract_video_and_audio_and_transcribe(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")

    with pytest.raises(ValueError):
        asyncio.run(multimodal.extract_video_frames(src, strategy="other"))

    assert asyncio.run(multimodal.extract_video_frames(src, max_frames=0)) == []

    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "ffmpeg")

    async def _to_thread_frames(fn, command):
        _ = fn, command
        outdir = tmp_path / "frames"
        outdir.mkdir(exist_ok=True)
        (outdir / "frame_001.jpg").write_bytes(b"1")
        (outdir / "frame_002.jpg").write_bytes(b"2")

    monkeypatch.setattr(multimodal.asyncio, "to_thread", _to_thread_frames)
    frames = asyncio.run(multimodal.extract_video_frames(src, output_dir=tmp_path / "frames", interval_seconds=2.0))
    assert len(frames) == 2
    assert frames[1].timestamp_seconds == 2.0

    audio = asyncio.run(multimodal.extract_audio_track(src, output_path=tmp_path / "a.wav"))
    assert audio.endswith("a.wav")

    with pytest.raises(FileNotFoundError):
        asyncio.run(multimodal.transcribe_audio(tmp_path / "none.wav"))

    wav = tmp_path / "input.wav"
    wav.write_bytes(b"x")
    with pytest.raises(ValueError):
        asyncio.run(multimodal.transcribe_audio(wav, provider="other"))

    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)
    missing = asyncio.run(multimodal.transcribe_audio(wav))
    assert missing["success"] is False


def test_transcribe_audio_error_and_success(tmp_path: Path, monkeypatch) -> None:
    wav = tmp_path / "input.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def _fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["whisper"], stderr=b"boom")

    monkeypatch.setattr(multimodal.asyncio, "to_thread", _fail)
    fail = asyncio.run(multimodal.transcribe_audio(wav))
    assert fail["success"] is False

    async def _ok(fn, command):
        _ = fn, command
        out_dir = Path(command[command.index("--output_dir") + 1])
        (out_dir / "input.json").write_text('{"text":" hello ","segments":"bad","language":"tr"}', encoding="utf-8")

    monkeypatch.setattr(multimodal.asyncio, "to_thread", _ok)
    ok = asyncio.run(multimodal.transcribe_audio(wav, language="en", prompt="p"))
    assert ok["success"] is True
    assert ok["segments"] == []


def test_context_document_ingest_and_scene_summary() -> None:
    ctx = multimodal.build_multimodal_context(
        media_kind="video",
        transcript={"reason": "none", "language": "tr"},
        frame_analyses=[{"timestamp_seconds": 1, "summary": "s1"}],
    )
    assert "Transkript Durumu" in ctx
    assert "1.0s" in multimodal.build_scene_summary([{"timestamp_seconds": 1, "analysis": "x"}])

    title, body = multimodal.render_multimodal_document(
        {"media_kind": "audio", "transcript": {}, "frame_analyses": [], "analysis": "", "context": ""},
        source="/tmp/a.mp3",
        title="Özel",
    )
    assert title == "Özel"
    assert "Medya Türü: audio" in body

    bad = asyncio.run(multimodal.ingest_multimodal_analysis(_Store(), {"success": False}, source="s"))
    assert bad["success"] is False
    good = asyncio.run(multimodal.ingest_multimodal_analysis(_Store(), {"success": True, "media_kind": "video"}, source="s"))
    assert good["success"] is True


def test_pipeline_local_and_remote_paths(tmp_path: Path, monkeypatch) -> None:
    class _LLM:
        async def chat(self, **kwargs):
            _ = kwargs
            return "analysis"

    pipe = multimodal.MultimodalPipeline(_LLM(), config=SimpleNamespace(ENABLE_MULTIMODAL=True, MULTIMODAL_MAX_FILE_BYTES=999999))
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    async def _fake_transcribe(*_args, **_kwargs):
        return {"text": "txt", "language": "tr", "success": True, "segments": []}

    monkeypatch.setattr(multimodal, "transcribe_audio", _fake_transcribe)
    res_audio = asyncio.run(pipe.analyze_media(media_path=str(audio), mime_type="audio/wav", prompt="note"))
    assert res_audio["success"] is True

    local = asyncio.run(pipe.analyze_media_source(media_source=str(audio), mime_type="audio/wav"))
    assert local["media_source"] == str(audio)

    async def _fake_materialize(*_args, **_kwargs):
        p = tmp_path / "r.wav"
        p.write_bytes(b"x")
        return multimodal.DownloadedMedia(
            path=str(p), source_url="u", mime_type="audio/wav", platform="youtube", resolved_url="https://cdn", title="t"
        )

    async def _fake_fetch(*_args, **_kwargs):
        return {"text": "yt", "success": True, "language": "tr", "segments": []}

    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "ffmpeg")
    monkeypatch.setattr(multimodal, "materialize_remote_media_for_ffmpeg", _fake_materialize)
    monkeypatch.setattr(multimodal, "fetch_youtube_transcript", _fake_fetch)

    store = _Store()
    remote = asyncio.run(
        pipe.analyze_media_source(
            media_source="https://youtu.be/dQw4w9WgXcQ",
            mime_type="audio/wav",
            ingest_document_store=store,
            ingest_tags=["x"],
        )
    )
    assert remote["success"] is True
    assert remote["download"]["platform"] == "youtube"
    assert remote["document_ingest"]["success"] is True


def test_pipeline_image_branch_and_transcribe_bytes(tmp_path: Path, monkeypatch) -> None:
    class _LLM:
        async def chat(self, **kwargs):
            _ = kwargs
            return "analysis"

    class _VisionPipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, image_path: str):
            return {"success": True, "analysis": f"vision:{Path(image_path).name}"}

    monkeypatch.setitem(__import__("sys").modules, "core.vision", SimpleNamespace(VisionPipeline=_VisionPipeline))
    pipe = multimodal.MultimodalPipeline(_LLM(), config=SimpleNamespace(ENABLE_MULTIMODAL=True))
    image = tmp_path / "i.png"
    image.write_bytes(b"x")

    out = asyncio.run(pipe.analyze_media(media_path=str(image), mime_type="image/png"))
    assert out["success"] is True

    async def _tx(path, **kwargs):
        _ = path, kwargs
        return {"success": True, "text": "ok", "segments": [], "language": "tr"}

    monkeypatch.setattr(multimodal, "transcribe_audio", _tx)
    b = asyncio.run(pipe.transcribe_bytes(b"abc", mime_type="audio/ogg"))
    assert b["success"] is True

    disabled = multimodal.MultimodalPipeline(_LLM(), config=SimpleNamespace(ENABLE_MULTIMODAL=False))
    assert asyncio.run(disabled.analyze_media(media_path=str(image)))["success"] is False
    assert asyncio.run(disabled.analyze_media_source(media_source="https://example.com"))["success"] is False
