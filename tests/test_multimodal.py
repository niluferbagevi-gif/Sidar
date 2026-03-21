import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from core import multimodal as multimodal_mod
from core.multimodal import (
    ExtractedFrame,
    MultimodalPipeline,
    _command_exists,
    _guess_suffix,
    _run_subprocess,
    build_multimodal_context,
    download_remote_media,
    detect_media_kind,
    extract_youtube_video_id,
    extract_audio_track,
    extract_video_frames,
    fetch_youtube_transcript,
    ingest_multimodal_analysis,
    is_remote_media_source,
    materialize_remote_media_for_ffmpeg,
    resolve_remote_media_stream,
    render_multimodal_document,
    transcribe_audio,
)


def test_detect_media_kind_uses_mime_or_path_suffix():
    assert detect_media_kind(mime_type="audio/webm") == "audio"
    assert detect_media_kind(path="demo.mp4") == "video"
    assert detect_media_kind(path="frame.png") == "image"
    assert detect_media_kind(mime_type="application/octet-stream") == "unknown"


def test_build_multimodal_context_includes_transcript_frames_and_notes():
    context = build_multimodal_context(
        media_kind="video",
        transcript={"text": "Login ekranında spinner takılıyor.", "language": "tr"},
        frame_analyses=[
            {"timestamp_seconds": 0.0, "analysis": "Ana sayfa yükleniyor."},
            {"timestamp_seconds": 5.0, "summary": "Spinner görünür halde takılı kalıyor."},
        ],
        extra_notes="Kullanıcı Loom kaydı paylaştı.",
    )

    assert "Medya Türü: video" in context
    assert "Login ekranında spinner takılıyor." in context
    assert "- 0.0s: Ana sayfa yükleniyor." in context
    assert "- 5.0s: Spinner görünür halde takılı kalıyor." in context
    assert "Kullanıcı Loom kaydı paylaştı." in context


def test_build_multimodal_context_uses_reason_and_skips_blank_frame_summary():
    context = build_multimodal_context(
        media_kind="audio",
        transcript={"reason": "Whisper CLI bulunamadı.", "language": "en"},
        frame_analyses=[{"timestamp_seconds": 1.5, "analysis": "   "}],
    )

    assert "Transkript Durumu: Whisper CLI bulunamadı." in context
    assert "Transkript Dili: en" in context
    assert "Frame Bulguları:" in context
    assert "1.5s" not in context


def test_command_exists_and_guess_suffix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(multimodal_mod.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    assert _command_exists("ffmpeg") is True
    assert _command_exists("whisper") is False
    assert _guess_suffix("audio/webm", ".bin") == ".webm"
    assert _guess_suffix("APPLICATION/UNKNOWN", ".bin") == ".bin"


def test_run_subprocess_passes_expected_flags(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(multimodal_mod.subprocess, "run", _fake_run)
    _run_subprocess(["ffmpeg", "-version"])

    assert captured["command"] == ["ffmpeg", "-version"]
    assert captured["kwargs"] == {"check": True, "capture_output": True}


def test_extract_video_frames_validates_strategy_and_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"video")

    with pytest.raises(ValueError, match="fixed-interval"):
        asyncio.run(extract_video_frames(media, strategy="scene-detect"))

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: False)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        asyncio.run(extract_video_frames(media))


def test_extract_video_frames_handles_zero_missing_file_and_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert asyncio.run(extract_video_frames(tmp_path / "none.mp4", max_frames=0)) == []

    media = tmp_path / "demo.mp4"
    media.write_bytes(b"video")
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: True)

    with pytest.raises(FileNotFoundError, match="Medya dosyası bulunamadı"):
        asyncio.run(extract_video_frames(tmp_path / "absent.mp4"))

    captured = {}

    def _fake_run(command):
        captured["command"] = command
        frames_dir = tmp_path / "frames"
        (frames_dir / "frame_002.jpg").write_bytes(b"2")
        (frames_dir / "frame_001.jpg").write_bytes(b"1")

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _fake_run)
    frames = asyncio.run(
        extract_video_frames(
            media,
            interval_seconds=0.05,
            max_frames=2,
            output_dir=tmp_path / "frames",
        )
    )

    assert captured["command"][0] == "ffmpeg"
    assert "fps=10.0" in captured["command"]
    assert [frame.path for frame in frames] == [
        str(tmp_path / "frames" / "frame_001.jpg"),
        str(tmp_path / "frames" / "frame_002.jpg"),
    ]
    assert [frame.timestamp_seconds for frame in frames] == [0.0, 0.05]


def test_extract_video_frames_propagates_subprocess_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media = tmp_path / "broken.mp4"
    media.write_bytes(b"broken")
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: True)

    def _boom(_command):
        raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"decode failed")

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _boom)

    with pytest.raises(subprocess.CalledProcessError):
        asyncio.run(extract_video_frames(media))


def test_extract_audio_track_validates_binary_missing_file_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"video")

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: False)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        asyncio.run(extract_audio_track(media))

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: True)
    with pytest.raises(FileNotFoundError, match="Medya dosyası bulunamadı"):
        asyncio.run(extract_audio_track(tmp_path / "missing.mp4"))

    captured = {}

    def _ok(command):
        captured["command"] = command

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _ok)
    output = asyncio.run(extract_audio_track(media, output_path=tmp_path / "nested" / "audio.wav", sample_rate=22_050))

    assert output == str(tmp_path / "nested" / "audio.wav")
    assert captured["command"] == [
        "ffmpeg",
        "-y",
        "-i",
        str(media),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "22050",
        str(tmp_path / "nested" / "audio.wav"),
    ]

    def _boom(_command):
        raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"invalid data")

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _boom)
    with pytest.raises(subprocess.CalledProcessError):
        asyncio.run(extract_audio_track(media))


class _TrackingTempDir:
    created_paths: list[Path] = []
    cleaned_paths: list[Path] = []
    base_dir: Path | None = None
    counter = 0

    def __init__(self, prefix: str = "tmp-"):
        self.prefix = prefix
        self.path: Path | None = None

    def __enter__(self) -> str:
        assert self.base_dir is not None
        path = self.base_dir / f"{self.prefix}{type(self).counter}"
        type(self).counter += 1
        path.mkdir(parents=True, exist_ok=False)
        self.path = path
        type(self).created_paths.append(path)
        return str(path)

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self.path is not None
        if self.path.exists():
            for child in sorted(self.path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.path.rmdir()
        type(self).cleaned_paths.append(self.path)
        return False


@pytest.fixture
def tracking_tempdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _TrackingTempDir.created_paths = []
    _TrackingTempDir.cleaned_paths = []
    _TrackingTempDir.base_dir = tmp_path / "tempdirs"
    _TrackingTempDir.base_dir.mkdir()
    _TrackingTempDir.counter = 0
    monkeypatch.setattr(multimodal_mod.tempfile, "TemporaryDirectory", _TrackingTempDir)
    return _TrackingTempDir


def test_transcribe_audio_validates_provider_binary_error_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracking_tempdir
):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")

    with pytest.raises(FileNotFoundError, match="Ses dosyası bulunamadı"):
        asyncio.run(transcribe_audio(tmp_path / "missing.wav"))

    with pytest.raises(ValueError, match="yalnızca whisper"):
        asyncio.run(transcribe_audio(audio, provider="azure"))

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: False)
    unavailable = asyncio.run(transcribe_audio(audio, language="tr"))
    assert unavailable == {
        "success": False,
        "provider": "whisper",
        "model": "base",
        "text": "",
        "segments": [],
        "language": "tr",
        "reason": "Whisper CLI bulunamadı.",
    }

    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: True)

    def _boom(_command):
        raise subprocess.CalledProcessError(returncode=2, cmd=["whisper"], stderr=b"decoder crashed")

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _boom)
    failed = asyncio.run(transcribe_audio(audio, language="tr", prompt="ilk ipucu"))
    assert failed["success"] is False
    assert failed["reason"] == "decoder crashed"
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths
    assert not tracking_tempdir.created_paths[0].exists()


def test_transcribe_audio_handles_missing_output_and_success_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracking_tempdir
):
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda _name: True)
    commands = []

    def _no_output(command):
        commands.append(command)

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _no_output)
    missing = asyncio.run(transcribe_audio(audio, model="small", language="en", prompt="hello"))
    assert missing["reason"] == "Whisper çıktı dosyası üretmedi."
    assert commands[0][:6] == ["whisper", str(audio), "--model", "small", "--output_format", "json"]
    assert "--language" in commands[0]
    assert "--initial_prompt" in commands[0]
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths

    def _write_output(command):
        tmpdir = Path(command[command.index("--output_dir") + 1])
        payload = {"text": "  Merhaba dünya  ", "segments": {"bad": True}, "language": "tr"}
        (tmpdir / f"{audio.stem}.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _write_output)
    success = asyncio.run(transcribe_audio(audio))
    assert success == {
        "success": True,
        "provider": "whisper",
        "model": "base",
        "text": "Merhaba dünya",
        "segments": [],
        "language": "tr",
    }
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths


class _DummyLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return "- özet"


class _Config:
    ENABLE_MULTIMODAL = True
    MULTIMODAL_MAX_FILE_BYTES = 1024
    VOICE_STT_PROVIDER = "whisper"
    WHISPER_MODEL = "tiny"


def test_multimodal_pipeline_transcribe_bytes_validates_limits_and_writes_suffix(
    monkeypatch: pytest.MonkeyPatch, tracking_tempdir
):
    llm = _DummyLLM()
    pipeline = MultimodalPipeline(llm, _Config())

    pipeline.enabled = False
    assert asyncio.run(pipeline.transcribe_bytes(b"abc")) == {"success": False, "reason": "ENABLE_MULTIMODAL devre dışı"}
    pipeline.enabled = True

    assert asyncio.run(pipeline.transcribe_bytes(b"")) == {"success": False, "reason": "Ses verisi boş"}
    assert asyncio.run(pipeline.transcribe_bytes(b"x" * 2048)) == {
        "success": False,
        "reason": "Ses verisi boyut limitini aşıyor",
    }

    captured = {}

    async def _fake_transcribe(path, **kwargs):
        captured["path"] = Path(path)
        captured["kwargs"] = kwargs
        captured["bytes"] = Path(path).read_bytes()
        return {"success": True, "text": "ok"}

    monkeypatch.setattr(multimodal_mod, "transcribe_audio", _fake_transcribe)
    result = asyncio.run(pipeline.transcribe_bytes(b"voice-bytes", mime_type="audio/mp4", language="tr", prompt="ipuçları"))

    assert result == {"success": True, "text": "ok"}
    assert captured["path"].name == "voice_input.m4a"
    assert captured["bytes"] == b"voice-bytes"
    assert captured["kwargs"] == {"provider": "whisper", "model": "tiny", "language": "tr", "prompt": "ipuçları"}
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths


def test_multimodal_pipeline_analyze_media_handles_disabled_missing_size_and_unknown(tmp_path: Path):
    llm = _DummyLLM()
    pipeline = MultimodalPipeline(llm, _Config())

    pipeline.enabled = False
    assert asyncio.run(pipeline.analyze_media(media_path=str(tmp_path / "x.wav"))) == {
        "success": False,
        "reason": "ENABLE_MULTIMODAL devre dışı",
    }
    pipeline.enabled = True

    missing = asyncio.run(pipeline.analyze_media(media_path=str(tmp_path / "missing.wav")))
    assert missing["success"] is False
    assert "Medya dosyası bulunamadı" in missing["reason"]

    oversized = tmp_path / "big.wav"
    oversized.write_bytes(b"x" * 2048)
    too_big = asyncio.run(pipeline.analyze_media(media_path=str(oversized), mime_type="audio/wav"))
    assert too_big == {"success": False, "reason": "Medya dosyası boyut limitini aşıyor"}

    unknown = tmp_path / "blob.bin"
    unknown.write_bytes(b"123")
    unsupported = asyncio.run(pipeline.analyze_media(media_path=str(unknown), mime_type="application/octet-stream"))
    assert unsupported == {"success": False, "reason": "Desteklenmeyen medya türü: unknown"}


def test_multimodal_pipeline_analyze_media_uses_vision_for_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image = tmp_path / "frame.png"
    image.write_bytes(b"png")
    llm = _DummyLLM()
    pipeline = MultimodalPipeline(llm, _Config())

    class _VisionPipeline:
        def __init__(self, llm_client, config):
            assert llm_client is llm
            assert isinstance(config, _Config)

        async def analyze(self, *, image_path: str):
            return {"success": True, "analysis": f"vision:{Path(image_path).name}"}

    fake_module = types.ModuleType("core.vision")
    fake_module.VisionPipeline = _VisionPipeline
    monkeypatch.setitem(sys.modules, "core.vision", fake_module)

    result = asyncio.run(pipeline.analyze_media(media_path=str(image), mime_type="image/png"))
    assert result == {"success": True, "analysis": "vision:frame.png"}


def test_multimodal_pipeline_analyze_media_audio_branch_builds_context_and_calls_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracking_tempdir
):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"audio")
    llm = _DummyLLM()
    pipeline = MultimodalPipeline(llm, _Config())

    async def _fake_transcribe(path, **kwargs):
        assert Path(path) == audio
        assert kwargs["model"] == "tiny"
        return {"success": True, "text": "Merhaba", "language": "tr", "segments": [{"id": 1}]}

    monkeypatch.setattr(multimodal_mod, "transcribe_audio", _fake_transcribe)
    result = asyncio.run(
        pipeline.analyze_media(media_path=str(audio), mime_type="audio/wav", prompt="müşteri çağrısı", language="tr")
    )

    assert result["success"] is True
    assert result["media_kind"] == "audio"
    assert result["transcript"]["text"] == "Merhaba"
    assert result["frame_analyses"] == []
    assert "Ek Notlar:\nmüşteri çağrısı" in result["context"]
    assert llm.calls[0]["messages"][0]["role"] == "user"
    assert "Merhaba" in llm.calls[0]["messages"][0]["content"]
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths


def test_multimodal_pipeline_analyze_media_video_branch_collects_frames_and_suppresses_vision_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracking_tempdir
):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    llm = _DummyLLM()
    pipeline = MultimodalPipeline(llm, _Config())

    async def _fake_extract_audio(path, *, output_path, sample_rate=16_000):
        assert Path(path) == video
        Path(output_path).write_bytes(b"wav")
        return str(output_path)

    async def _fake_transcribe(path, **kwargs):
        assert Path(path).name == "audio.wav"
        return {"success": True, "text": "Video transkript", "language": "tr", "segments": []}

    async def _fake_extract_frames(path, *, interval_seconds, max_frames, output_dir):
        assert Path(path) == video
        frames_dir = Path(output_dir)
        frames_dir.mkdir(parents=True, exist_ok=True)
        first = frames_dir / "frame_001.jpg"
        second = frames_dir / "frame_002.jpg"
        first.write_bytes(b"1")
        second.write_bytes(b"2")
        return [
            ExtractedFrame(path=str(first), timestamp_seconds=0.0),
            ExtractedFrame(path=str(second), timestamp_seconds=3.0),
        ]

    class _VisionPipeline:
        async def analyze(self, *, image_path: str):
            if image_path.endswith("frame_001.jpg"):
                return {"analysis": "İlk kare"}
            raise RuntimeError("bozuk kare")

    fake_module = types.ModuleType("core.vision")
    fake_module.VisionPipeline = lambda *_args, **_kwargs: _VisionPipeline()
    monkeypatch.setitem(sys.modules, "core.vision", fake_module)
    monkeypatch.setattr(multimodal_mod, "extract_audio_track", _fake_extract_audio)
    monkeypatch.setattr(multimodal_mod, "transcribe_audio", _fake_transcribe)
    monkeypatch.setattr(multimodal_mod, "extract_video_frames", _fake_extract_frames)

    result = asyncio.run(
        pipeline.analyze_media(
            media_path=str(video),
            mime_type="video/mp4",
            prompt="olay özeti",
            frame_interval_seconds=3.0,
            max_frames=2,
            language="tr",
        )
    )

    assert result["success"] is True
    assert result["media_kind"] == "video"
    assert result["transcript"]["text"] == "Video transkript"
    assert result["frame_analyses"] == [{"timestamp_seconds": 0.0, "analysis": "İlk kare", "frame_path": result["frame_analyses"][0]["frame_path"]}]
    assert "Video transkript" in result["context"]
    assert "olay özeti" in result["context"]
    assert tracking_tempdir.created_paths == tracking_tempdir.cleaned_paths


def test_remote_media_helpers_cover_url_detection_and_youtube_transcript():
    assert is_remote_media_source("https://example.com/video.mp4") is True
    assert is_remote_media_source("/tmp/video.mp4") is False
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    class _Response:
        status_code = 200

        def json(self):
            return {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Merhaba"}]}]}

    class _Client:
        def __init__(self):
            self.urls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url):
            self.urls.append(url)
            return _Response()

    client = _Client()
    transcript = asyncio.run(
        fetch_youtube_transcript(
            "https://youtu.be/dQw4w9WgXcQ",
            languages=("tr",),
            http_client_factory=lambda **_kwargs: client,
        )
    )
    assert transcript["success"] is True
    assert transcript["text"] == "Merhaba"
    assert "lang=tr" in client.urls[0]


def test_resolve_remote_media_stream_uses_ytdlp_for_youtube(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda name: name == "yt-dlp")
    calls = []

    def _fake_capture(command):
        calls.append(command)
        if "--dump-single-json" in command:
            return json.dumps({"title": "Demo Video"})
        return "https://stream.example.com/video.mp4\nhttps://stream.example.com/audio.webm\n"

    monkeypatch.setattr(multimodal_mod, "_run_subprocess_capture", _fake_capture)

    resolved = asyncio.run(resolve_remote_media_stream("https://youtu.be/dQw4w9WgXcQ"))

    assert resolved["platform"] == "youtube"
    assert resolved["resolved_url"] == "https://stream.example.com/video.mp4"
    assert resolved["title"] == "Demo Video"
    assert any("--dump-single-json" in command for command in calls)
    assert any("-g" in command for command in calls)


def test_materialize_remote_media_for_ffmpeg_uses_resolved_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda name: name == "ffmpeg")

    async def _fake_resolve(*_args, **_kwargs):
        return {
            "source_url": "https://youtu.be/dQw4w9WgXcQ",
            "resolved_url": "https://stream.example.com/video.mp4",
            "platform": "youtube",
            "mime_type": "video/mp4",
            "title": "Launch Video",
            "metadata": {"duration": 45},
        }

    captured = {}

    def _fake_run(command):
        captured["command"] = command
        Path(command[-1]).write_bytes(b"video")

    monkeypatch.setattr(multimodal_mod, "resolve_remote_media_stream", _fake_resolve)
    monkeypatch.setattr(multimodal_mod, "_run_subprocess", _fake_run)

    downloaded = asyncio.run(
        materialize_remote_media_for_ffmpeg(
            "https://youtu.be/dQw4w9WgXcQ",
            output_dir=tmp_path,
            max_duration_seconds=30,
        )
    )

    assert downloaded.platform == "youtube"
    assert downloaded.resolved_url == "https://stream.example.com/video.mp4"
    assert Path(downloaded.path).exists()
    assert captured["command"][:5] == ["ffmpeg", "-y", "-i", "https://stream.example.com/video.mp4", "-t"]


def test_download_remote_media_http_and_ingest_document(tmp_path: Path):
    class _Response:
        headers = {"content-type": "video/mp4"}
        content = b"video-bytes"

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            return _Response()

    downloaded = asyncio.run(
        download_remote_media(
            "https://cdn.example.com/demo.mp4",
            output_dir=tmp_path,
            http_client_factory=lambda **_kwargs: _Client(),
        )
    )
    assert Path(downloaded.path).exists()
    assert downloaded.platform == "generic"
    assert downloaded.resolved_url == "https://cdn.example.com/demo.mp4"

    title, content = render_multimodal_document(
        {
            "success": True,
            "media_kind": "video",
            "transcript": {"text": "Transkript"},
            "frame_analyses": [{"timestamp_seconds": 0.0, "analysis": "Hero sahnesi"}],
            "analysis": "CTA güçlü",
            "context": "bağlam",
        },
        source="https://cdn.example.com/demo.mp4",
    )
    assert "Video İçgörü Özeti" in title
    assert "Hero sahnesi" in content

    class _Store:
        async def add_document(self, **kwargs):
            self.kwargs = kwargs
            return "doc-1"

    store = _Store()
    ingest = asyncio.run(
        ingest_multimodal_analysis(
            store,
            {
                "success": True,
                "media_kind": "video",
                "transcript": {"text": "Transkript"},
                "frame_analyses": [{"timestamp_seconds": 0.0, "analysis": "Hero sahnesi"}],
                "analysis": "CTA güçlü",
                "context": "bağlam",
            },
            source="https://cdn.example.com/demo.mp4",
            session_id="marketing",
            tags=["video"],
        )
    )
    assert ingest["doc_id"] == "doc-1"
    assert store.kwargs["session_id"] == "marketing"


def test_multimodal_pipeline_analyze_media_source_downloads_youtube_and_ingests(monkeypatch: pytest.MonkeyPatch):
    class _LLM:
        async def chat(self, **_kwargs):
            return "unused"

    pipeline = MultimodalPipeline(
        _LLM(),
        types.SimpleNamespace(ENABLE_MULTIMODAL=True, MULTIMODAL_MAX_FILE_BYTES=1024 * 1024),
    )

    async def _fake_download(*_args, **_kwargs):
        return multimodal_mod.DownloadedMedia(
            path="/tmp/fake.mp4",
            source_url="https://youtu.be/dQw4w9WgXcQ",
            mime_type="video/mp4",
            platform="youtube",
            resolved_url="https://stream.example.com/video.mp4",
            title="Demo Video",
        )

    async def _fake_transcript(*_args, **_kwargs):
        return {"success": True, "text": "Video özeti", "segments": [], "language": "tr"}

    async def _fake_local(**kwargs):
        assert kwargs["transcript_override"]["text"] == "Video özeti"
        return {
            "success": True,
            "media_kind": "video",
            "transcript": {"text": "Video özeti"},
            "frame_analyses": [{"timestamp_seconds": 0.0, "analysis": "Hero"}],
            "scene_summary": "0.0s → Hero",
            "analysis": "Kampanya açılışı güçlü",
            "context": "ctx",
        }

    class _Store:
        async def add_document(self, **kwargs):
            self.kwargs = kwargs
            return "doc-55"

    monkeypatch.setattr(multimodal_mod, "download_remote_media", _fake_download)
    monkeypatch.setattr(multimodal_mod, "materialize_remote_media_for_ffmpeg", _fake_download)
    monkeypatch.setattr(multimodal_mod, "fetch_youtube_transcript", _fake_transcript)
    monkeypatch.setattr(pipeline, "_analyze_local_media", _fake_local)
    monkeypatch.setattr(multimodal_mod, "_command_exists", lambda name: name == "ffmpeg")
    store = _Store()

    result = asyncio.run(
        pipeline.analyze_media_source(
            media_source="https://youtu.be/dQw4w9WgXcQ",
            prompt="hook çıkar",
            ingest_document_store=store,
            ingest_session_id="marketing",
            ingest_tags=["video", "marketing"],
        )
    )

    assert result["success"] is True
    assert result["document_ingest"]["doc_id"] == "doc-55"
    assert result["download"]["platform"] == "youtube"
    assert result["download"]["resolved_url"] == "https://stream.example.com/video.mp4"
