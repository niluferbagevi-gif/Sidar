from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

import core.multimodal as multimodal


class DummyLLM:
    def __init__(self, response: str = "analiz") -> None:
        self.response = response

    async def chat(self, **_kwargs):
        return self.response


class DummyConfig:
    ENABLE_MULTIMODAL = True
    MULTIMODAL_MAX_FILE_BYTES = 1024 * 1024
    MULTIMODAL_REMOTE_DOWNLOAD_TIMEOUT = 11.0
    YOUTUBE_TRANSCRIPT_TIMEOUT = 3.0
    MULTIMODAL_REMOTE_VIDEO_MAX_SECONDS = 33.0
    VOICE_STT_PROVIDER = "whisper"
    WHISPER_MODEL = "tiny"


class TinyLimitConfig(DummyConfig):
    MULTIMODAL_MAX_FILE_BYTES = 2


class AsyncClientStub:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url):
        return self._responses.pop(0)


class ResponseStub:
    def __init__(
        self, *, status_code=200, payload=None, headers=None, content=b"", raise_error=None
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = content
        self._raise_error = raise_error

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error


def run(coro):
    return asyncio.run(coro)


def test_response_stub_raise_for_status_raises_configured_error():
    stub = ResponseStub(raise_error=RuntimeError("http failure"))

    with pytest.raises(RuntimeError, match="http failure"):
        stub.raise_for_status()


def test_detect_media_kind_and_sources():
    assert multimodal.detect_media_kind(mime_type="video/mp4") == "video"
    assert multimodal.detect_media_kind(path="sound.mp3") == "audio"
    assert multimodal.detect_media_kind(path="photo.png") == "image"
    assert multimodal.detect_media_kind(path="unknown.xyz") == "unknown"
    assert multimodal.is_remote_media_source("https://example.com/a.mp4") is True
    assert multimodal.is_remote_media_source("/tmp/local.mp4") is False


def test_detect_platform_and_youtube_id_extractors():
    assert multimodal.detect_video_platform("https://youtu.be/abcdefghijk") == "youtube"
    assert multimodal.detect_video_platform("https://vimeo.com/123") == "vimeo"
    assert multimodal.detect_video_platform("https://loom.com/share/1") == "loom"
    assert multimodal.detect_video_platform("https://example.com/file") == "generic"

    assert multimodal.extract_youtube_video_id("abcdefghijk") == "abcdefghijk"
    assert (
        multimodal.extract_youtube_video_id("https://www.youtube.com/watch?v=abcdefghijk")
        == "abcdefghijk"
    )
    assert multimodal.extract_youtube_video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert (
        multimodal.extract_youtube_video_id("https://www.youtube.com/shorts/abcdefghijk")
        == "abcdefghijk"
    )
    assert multimodal.extract_youtube_video_id("https://www.youtube.com/channel/abc") == ""
    assert multimodal.extract_youtube_video_id("https://example.com/nope") == ""


def test_normalize_youtube_events_skips_invalid_items():
    payload = [
        {"segs": [{"utf8": "Merhaba"}], "tStartMs": 1000, "dDurationMs": 500},
        {"segs": "invalid"},
        "not-dict",
        {"segs": [{"utf8": "&amp; dunya"}], "tStartMs": 2000, "dDurationMs": 750},
    ]
    normalized = multimodal._normalize_youtube_transcript_events(payload)
    assert normalized["text"] == "Merhaba & dunya"
    assert normalized["segments"][0]["start_seconds"] == 1.0
    assert normalized["segments"][1]["duration_seconds"] == 0.75


def test_fetch_youtube_transcript_success_after_language_fallback():
    responses = [
        ResponseStub(status_code=404),
        ResponseStub(
            payload={"events": [{"segs": [{"utf8": "Selam"}], "tStartMs": 0, "dDurationMs": 1000}]}
        ),
    ]

    def factory(**_kwargs):
        return AsyncClientStub(responses)

    result = run(
        multimodal.fetch_youtube_transcript(
            "https://youtube.com/watch?v=abcdefghijk",
            languages=("tr", "en"),
            http_client_factory=factory,
        )
    )
    assert result["success"] is True
    assert result["language"] == "en"
    assert result["text"] == "Selam"


def test_fetch_youtube_transcript_invalid_id_returns_failure():
    result = run(multimodal.fetch_youtube_transcript("https://example.com/video"))
    assert result["success"] is False


def test_fetch_youtube_transcript_not_found_when_empty_payload():
    responses = [ResponseStub(payload={"events": [{"segs": []}]})]

    def factory(**_kwargs):
        return AsyncClientStub(responses)

    result = run(
        multimodal.fetch_youtube_transcript(
            "https://youtube.com/watch?v=abcdefghijk",
            languages=("tr",),
            http_client_factory=factory,
        )
    )
    assert result["success"] is False
    assert "bulunamadı" in result["reason"]


def test_download_remote_media_http_flow(tmp_path):
    def factory(**_kwargs):
        return AsyncClientStub(
            [
                ResponseStub(
                    headers={"content-type": "video/mp4; charset=UTF-8"}, content=b"video-data"
                )
            ]
        )

    downloaded = run(
        multimodal.download_remote_media(
            "https://example.com/media/test.mp4", output_dir=tmp_path, http_client_factory=factory
        )
    )
    assert Path(downloaded.path).read_bytes() == b"video-data"
    assert downloaded.mime_type == "video/mp4"


def test_download_remote_media_requires_remote_source(tmp_path):
    with pytest.raises(ValueError):
        run(multimodal.download_remote_media("/tmp/local.mp4", output_dir=tmp_path))


def test_download_remote_media_ytdlp_without_output_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "yt-dlp")
    monkeypatch.setattr(multimodal.asyncio, "to_thread", lambda _fn, _cmd: asyncio.sleep(0))
    with pytest.raises(RuntimeError):
        run(
            multimodal.download_remote_media(
                "https://youtube.com/watch?v=abcdefghijk", output_dir=tmp_path
            )
        )


def test_resolve_remote_media_stream_ytdlp_path(monkeypatch):
    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "yt-dlp")

    async def fake_to_thread(_fn, command):
        if "--dump-single-json" in command:
            return '{"title":"Demo Video"}'
        return "https://cdn.example.com/stream.mp4\n"

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_to_thread)
    result = run(multimodal.resolve_remote_media_stream("https://youtube.com/watch?v=abcdefghijk"))
    assert result["resolved_url"] == "https://cdn.example.com/stream.mp4"


def test_resolve_remote_media_stream_validates_url_and_generic_fallback():
    with pytest.raises(ValueError):
        run(multimodal.resolve_remote_media_stream("/tmp/local.mp4"))

    result = run(
        multimodal.resolve_remote_media_stream("https://example.com/a.mp4", prefer_video=False)
    )
    assert result["mime_type"] == ""


def test_materialize_remote_media_for_ffmpeg_fallbacks_to_download(monkeypatch, tmp_path):
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)

    async def fake_download(source_url, *, output_dir, **_kwargs):
        return multimodal.DownloadedMedia(
            path=str(Path(output_dir) / "x.mp4"),
            source_url=source_url,
            mime_type="video/mp4",
            platform="generic",
        )

    monkeypatch.setattr(multimodal, "download_remote_media", fake_download)
    result = run(
        multimodal.materialize_remote_media_for_ffmpeg(
            "https://example.com/v.mp4", output_dir=tmp_path
        )
    )
    assert result.path.endswith("x.mp4")


def test_materialize_remote_media_for_ffmpeg_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fake_resolve(_src, **_kwargs):
        return {
            "resolved_url": "https://cdn.example.com/video",
            "platform": "youtube",
            "mime_type": "video/webm",
            "title": "A/B: Demo",
        }

    async def fake_to_thread(_fn, command):
        Path(command[-1]).write_bytes(b"x")

    monkeypatch.setattr(multimodal, "resolve_remote_media_stream", fake_resolve)
    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_to_thread)
    result = run(
        multimodal.materialize_remote_media_for_ffmpeg(
            "https://youtube.com/watch?v=abcdefghijk", output_dir=tmp_path
        )
    )
    assert Path(result.path).name == "A_B_Demo.webm"
    assert result.platform == "youtube"


def test_extract_video_frames_generates_frame_metadata(monkeypatch, tmp_path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"x")
    frames_dir = tmp_path / "frames"
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fake_to_thread(_fn, _command):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_001.jpg").write_bytes(b"a")
        (frames_dir / "frame_002.jpg").write_bytes(b"b")

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_to_thread)
    frames = run(
        multimodal.extract_video_frames(
            video, interval_seconds=2.5, max_frames=2, output_dir=frames_dir
        )
    )
    assert [Path(f.path).name for f in frames] == ["frame_001.jpg", "frame_002.jpg"]


def test_extract_video_frames_validation_and_edge_cases(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        run(multimodal.extract_video_frames(tmp_path / "x.mp4", strategy="keyframes"))
    assert run(multimodal.extract_video_frames(tmp_path / "x.mp4", max_frames=0)) == []
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)
    with pytest.raises(RuntimeError):
        run(multimodal.extract_video_frames(tmp_path / "x.mp4"))


def test_extract_audio_track_and_transcribe_audio_paths(monkeypatch, tmp_path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"x")
    output = tmp_path / "audio.wav"
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fake_audio(_fn, _command):
        output.write_bytes(b"wav")

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_audio)
    audio_path = run(multimodal.extract_audio_track(source, output_path=output))
    assert Path(audio_path).exists()

    async def fake_whisper(_fn, command):
        out = Path(command[command.index("--output_dir") + 1])
        (out / f"{source.stem}.json").write_text(
            '{"text":" tx ","segments":[1],"language":"tr"}', encoding="utf-8"
        )

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_whisper)
    result = run(multimodal.transcribe_audio(source, language="tr"))
    assert result["success"] is True
    assert result["text"] == "tx"


def test_extract_audio_track_validation(monkeypatch, tmp_path):
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)
    with pytest.raises(RuntimeError):
        run(multimodal.extract_audio_track(tmp_path / "none.mp4"))


def test_transcribe_audio_failure_modes(monkeypatch, tmp_path):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"a")
    with pytest.raises(ValueError):
        run(multimodal.transcribe_audio(audio, provider="other"))

    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)
    missing_cli = run(multimodal.transcribe_audio(audio))
    assert missing_cli["success"] is False

    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def raise_called_process_error(_fn, _command):
        raise multimodal.subprocess.CalledProcessError(
            returncode=1,
            cmd="whisper",
            stderr=b"boom",
        )

    monkeypatch.setattr(multimodal.asyncio, "to_thread", raise_called_process_error)
    errored = run(multimodal.transcribe_audio(audio))
    assert errored["success"] is False
    assert "boom" in errored["reason"]

    with pytest.raises(FileNotFoundError):
        run(multimodal.transcribe_audio(tmp_path / "not-found.wav"))


def test_build_context_scene_summary_and_render_document():
    transcript = {"text": "metin", "language": "tr"}
    frames = [{"timestamp_seconds": 1.2, "analysis": "sahne-1"}]
    context = multimodal.build_multimodal_context(
        media_kind="video", transcript=transcript, frame_analyses=frames
    )
    assert "Transkript" in context
    title, body = multimodal.render_multimodal_document(
        {
            "media_kind": "video",
            "transcript": transcript,
            "frame_analyses": frames,
            "analysis": "öngörü",
            "context": "bağlam",
        },
        source="demo.mp4",
    )
    assert "Video İçgörü Özeti" in title
    assert "LLM İçgörüsü" in body


def test_build_context_reason_path_and_render_download_details():
    context = multimodal.build_multimodal_context(
        media_kind="audio",
        transcript={"reason": "yok", "language": "tr"},
        frame_analyses=[{"timestamp_seconds": 0, "summary": "kare"}],
        extra_notes=" not ",
    )
    assert "Transkript Durumu: yok" in context
    assert "Ek Notlar" in context

    _, body = multimodal.render_multimodal_document(
        {
            "media_kind": "audio",
            "download": {"platform": "youtube", "resolved_url": "https://stream"},
            "frame_analyses": [],
        },
        source="https://youtube.com/watch?v=abcdefghijk",
    )
    assert "Platform: youtube" in body
    assert "Çözümlenen Akış" in body

    reason_only = multimodal.build_multimodal_context(
        media_kind="audio",
        transcript={"reason": "yok"},
        frame_analyses=[],
    )
    assert "Transkript Durumu: yok" in reason_only
    assert "Transkript Dili" not in reason_only


def test_ingest_multimodal_analysis_success_and_failure():
    class Store:
        async def add_document(self, **kwargs):
            self.last = kwargs
            return "doc-1"

    store = Store()
    failed = run(multimodal.ingest_multimodal_analysis(store, {"success": False}, source="x"))
    assert failed["success"] is False
    ok = run(
        multimodal.ingest_multimodal_analysis(
            store,
            {
                "success": True,
                "media_kind": "audio",
                "transcript": {"text": "x"},
                "frame_analyses": [],
            },
            source="src",
        )
    )
    assert ok["doc_id"] == "doc-1"


def test_pipeline_transcribe_bytes_and_analyze_media_shortcuts(monkeypatch, tmp_path):
    pipeline = multimodal.MultimodalPipeline(DummyLLM(), DummyConfig())

    async def fake_transcribe(path, **_kwargs):
        assert Path(path).exists()
        return {"success": True, "text": "ses"}

    monkeypatch.setattr(multimodal, "transcribe_audio", fake_transcribe)
    result = run(pipeline.transcribe_bytes(b"abc"))
    assert result["success"] is True

    pipeline.enabled = False
    disabled = run(pipeline.analyze_media(media_path=str(tmp_path / "none")))
    assert disabled["success"] is False
    assert run(pipeline.transcribe_bytes(b"abc"))["success"] is False


def test_pipeline_transcribe_bytes_limits():
    pipeline = multimodal.MultimodalPipeline(DummyLLM(), TinyLimitConfig())
    assert run(pipeline.transcribe_bytes(b""))["success"] is False
    assert run(pipeline.transcribe_bytes(b"123"))["success"] is False


def test_pipeline_analyze_local_media_video_happy_path(monkeypatch, tmp_path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"abc")
    pipeline = multimodal.MultimodalPipeline(DummyLLM("sonuc"), DummyConfig())

    async def fake_extract_audio(_path, **_kwargs):
        wav = tmp_path / "out.wav"
        wav.write_bytes(b"w")
        return str(wav)

    async def fake_transcribe(_path, **_kwargs):
        return {"success": True, "text": "trans", "language": "tr"}

    async def fake_extract_frames(_path, **_kwargs):
        return [multimodal.ExtractedFrame(path=str(tmp_path / "f.jpg"), timestamp_seconds=0.0)]

    class VisionPipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, **_kwargs):
            return {"analysis": "frame-analiz"}

    monkeypatch.setitem(
        sys.modules, "core.vision", types.SimpleNamespace(VisionPipeline=VisionPipeline)
    )
    monkeypatch.setattr(multimodal, "extract_audio_track", fake_extract_audio)
    monkeypatch.setattr(multimodal, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(multimodal, "extract_video_frames", fake_extract_frames)

    result = run(pipeline._analyze_local_media(media_path=media, mime_type="video/mp4", prompt="p"))
    assert result["success"] is True
    assert result["analysis"] == "sonuc"


def test_pipeline_analyze_local_media_guards_and_image(monkeypatch, tmp_path):
    pipeline = multimodal.MultimodalPipeline(DummyLLM("x"), TinyLimitConfig())
    assert run(pipeline._analyze_local_media(media_path=tmp_path / "none"))["success"] is False

    big = tmp_path / "big.mp4"
    big.write_bytes(b"1234")
    too_big = run(pipeline._analyze_local_media(media_path=big, mime_type="video/mp4"))
    assert too_big["success"] is False

    img = tmp_path / "img.png"
    img.write_bytes(b"i")

    class VisionPipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, **_kwargs):
            return {"success": True, "analysis": "img"}

    monkeypatch.setitem(
        sys.modules, "core.vision", types.SimpleNamespace(VisionPipeline=VisionPipeline)
    )
    image_result = run(
        multimodal.MultimodalPipeline(DummyLLM(), DummyConfig())._analyze_local_media(
            media_path=img
        )
    )
    assert image_result["analysis"] == "img"


def test_pipeline_analyze_local_media_unsupported_kind(tmp_path):
    file = tmp_path / "file.bin"
    file.write_bytes(b"x")
    pipeline = multimodal.MultimodalPipeline(DummyLLM(), DummyConfig())
    result = run(
        pipeline._analyze_local_media(media_path=file, mime_type="application/octet-stream")
    )
    assert result["success"] is False


def test_pipeline_analyze_media_source_remote_with_ingest(monkeypatch):
    pipeline = multimodal.MultimodalPipeline(DummyLLM("A"), DummyConfig())
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: False)

    async def fake_download(_source, *, output_dir, **_kwargs):
        media = Path(output_dir) / "remote.mp4"
        media.write_bytes(b"x")
        return multimodal.DownloadedMedia(
            path=str(media),
            source_url="https://youtube.com/watch?v=abcdefghijk",
            mime_type="video/mp4",
            platform="youtube",
            resolved_url="https://cdn",
            title="yt",
        )

    async def fake_fetch(_source, **_kwargs):
        return {"success": True, "text": "yt transcript", "language": "tr", "segments": []}

    async def fake_analyze_local(**_kwargs):
        return {
            "success": True,
            "media_kind": "video",
            "transcript": {"text": "x"},
            "frame_analyses": [],
        }

    class Store:
        async def add_document(self, **_kwargs):
            return "doc-9"

    monkeypatch.setattr(multimodal, "download_remote_media", fake_download)
    monkeypatch.setattr(multimodal, "fetch_youtube_transcript", fake_fetch)
    monkeypatch.setattr(pipeline, "_analyze_local_media", fake_analyze_local)

    result = run(
        pipeline.analyze_media_source(
            media_source="https://youtube.com/watch?v=abcdefghijk",
            ingest_document_store=Store(),
        )
    )
    assert result["success"] is True
    assert result["document_ingest"]["doc_id"] == "doc-9"


def test_pipeline_analyze_media_source_validations_and_non_remote(monkeypatch, tmp_path):
    pipeline = multimodal.MultimodalPipeline(DummyLLM("A"), DummyConfig())
    pipeline.enabled = False
    assert run(pipeline.analyze_media_source(media_source="x"))["success"] is False

    pipeline.enabled = True
    assert run(pipeline.analyze_media_source(media_source=" "))["success"] is False

    media = tmp_path / "local.mp3"
    media.write_bytes(b"x")

    async def fake_local(**_kwargs):
        return {"success": True}

    monkeypatch.setattr(pipeline, "_analyze_local_media", fake_local)
    local_result = run(pipeline.analyze_media_source(media_source=str(media)))
    assert local_result["media_source"] == str(media)


def test_low_level_helpers_and_youtube_id_empty(monkeypatch):
    monkeypatch.setattr(
        multimodal.shutil, "which", lambda name: "/usr/bin/x" if name == "ffmpeg" else None
    )
    assert multimodal._command_exists("ffmpeg") is True
    assert multimodal._command_exists("missing") is False

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return types.SimpleNamespace(stdout="captured")

    monkeypatch.setattr(multimodal.subprocess, "run", fake_run)
    multimodal._run_subprocess(["echo", "ok"])
    assert calls[0][1]["check"] is True
    assert calls[0][1]["capture_output"] is True
    assert multimodal._run_subprocess_capture(["echo", "x"]) == "captured"

    assert multimodal.extract_youtube_video_id("") == ""


def test_download_remote_media_ytdlp_success_returns_downloaded_media(monkeypatch, tmp_path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"x")
    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "yt-dlp")
    monkeypatch.setattr(multimodal.asyncio, "to_thread", lambda _fn, _cmd: asyncio.sleep(0))
    result = run(
        multimodal.download_remote_media(
            "https://youtube.com/watch?v=abcdefghijk", output_dir=tmp_path
        )
    )
    assert result.path.endswith("video.mp4")
    assert result.mime_type == "video/mp4"
    assert result.title == "video"


def test_resolve_remote_media_stream_ignores_non_dict_metadata(monkeypatch):
    monkeypatch.setattr(multimodal, "_command_exists", lambda name: name == "yt-dlp")

    async def fake_to_thread(_fn, command):
        if "--dump-single-json" in command:
            return "[]"
        return "https://cdn.example.com/audio.webm\n"

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_to_thread)
    result = run(
        multimodal.resolve_remote_media_stream(
            "https://youtube.com/watch?v=abcdefghijk", prefer_video=False
        )
    )
    assert result["metadata"] == {}
    assert result["mime_type"] == "audio/webm"


def test_extract_video_frames_and_audio_track_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)
    with pytest.raises(FileNotFoundError):
        run(multimodal.extract_video_frames(tmp_path / "missing.mp4"))
    with pytest.raises(FileNotFoundError):
        run(multimodal.extract_audio_track(tmp_path / "missing.mp4"))


def test_transcribe_audio_prompt_and_missing_output_json(monkeypatch, tmp_path):
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"a")
    captured = {}
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fake_to_thread(_fn, command):
        captured["command"] = command
        # intentionally do not create output json
        return None

    monkeypatch.setattr(multimodal.asyncio, "to_thread", fake_to_thread)
    result = run(multimodal.transcribe_audio(audio, language="tr", prompt="ilk komut"))
    assert "--initial_prompt" in captured["command"]
    assert result["success"] is False
    assert "çıktı dosyası üretmedi" in result["reason"]


def test_build_context_scene_summary_and_render_additional_branches():
    context = multimodal.build_multimodal_context(
        media_kind="video",
        transcript=None,
        frame_analyses=[{"timestamp_seconds": 2.0, "analysis": ""}],
    )
    assert "Transkript" not in context
    assert "Frame Bulguları" in context

    assert multimodal.build_scene_summary([{"timestamp_seconds": 1.0, "analysis": ""}]) == ""

    title, body = multimodal.render_multimodal_document(
        {"media_kind": "video", "download": {"platform": "", "resolved_url": "src"}},
        source="src",
        title="Özel Başlık",
    )
    assert title == "Özel Başlık"
    assert "Platform:" not in body
    assert "Çözümlenen Akış:" not in body

    no_text_no_reason = multimodal.build_multimodal_context(
        media_kind="audio",
        transcript={},
        frame_analyses=[],
    )
    assert "Transkript Durumu" not in no_text_no_reason


def test_pipeline_additional_branches_audio_and_remote_fallback(monkeypatch, tmp_path):
    pipeline = multimodal.MultimodalPipeline(DummyLLM("ok"), DummyConfig())
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"abc")

    async def fake_transcribe(_path, **_kwargs):
        return {"success": True, "text": "ses"}

    monkeypatch.setattr(multimodal, "transcribe_audio", fake_transcribe)
    audio_result = run(pipeline._analyze_local_media(media_path=audio, mime_type="audio/mpeg"))
    assert audio_result["success"] is True
    assert audio_result["media_kind"] == "audio"

    async def fake_local(**kwargs):
        return {"success": True, "transcript_override_seen": kwargs.get("transcript_override")}

    monkeypatch.setattr(pipeline, "_analyze_local_media", fake_local)
    analyzed = run(pipeline.analyze_media(media_path=str(audio)))
    assert analyzed["success"] is True

    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fail_materialize(*_args, **_kwargs):
        raise RuntimeError("ffmpeg fail")

    async def fake_download(_source, *, output_dir, **_kwargs):
        local = Path(output_dir) / "fallback.mp4"
        local.write_bytes(b"x")
        return multimodal.DownloadedMedia(
            path=str(local),
            source_url=_source,
            mime_type="video/mp4",
            platform="generic",
            resolved_url=_source,
            title="fallback",
        )

    monkeypatch.setattr(multimodal, "materialize_remote_media_for_ffmpeg", fail_materialize)
    monkeypatch.setattr(multimodal, "download_remote_media", fake_download)
    remote = run(pipeline.analyze_media_source(media_source="https://example.com/video.mp4"))
    assert remote["success"] is True
    assert remote["download"]["platform"] == "generic"


def test_pipeline_video_transcript_override_skips_audio_extraction(monkeypatch, tmp_path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"abc")
    pipeline = multimodal.MultimodalPipeline(DummyLLM("ok"), DummyConfig())

    async def fail_extract_audio(*_args, **_kwargs):
        raise AssertionError(
            "extract_audio_track should not be called when transcript_override has text"
        )

    class VisionPipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyze(self, **_kwargs):
            return {"analysis": "frame-analiz"}

    async def fake_extract_frames(_path, **_kwargs):
        return [multimodal.ExtractedFrame(path=str(tmp_path / "f.jpg"), timestamp_seconds=1.0)]

    monkeypatch.setitem(
        sys.modules, "core.vision", types.SimpleNamespace(VisionPipeline=VisionPipeline)
    )
    monkeypatch.setattr(multimodal, "extract_audio_track", fail_extract_audio)
    monkeypatch.setattr(multimodal, "extract_video_frames", fake_extract_frames)
    result = run(
        pipeline._analyze_local_media(
            media_path=media,
            mime_type="video/mp4",
            transcript_override={"text": "hazır transkript", "language": "tr"},
        )
    )
    assert result["success"] is True
    assert result["transcript"]["text"] == "hazır transkript"


def test_pipeline_remote_ffmpeg_materialize_success_skips_download_fallback(monkeypatch, tmp_path):
    pipeline = multimodal.MultimodalPipeline(DummyLLM("ok"), DummyConfig())
    monkeypatch.setattr(multimodal, "_command_exists", lambda _name: True)

    async def fake_materialize(_source, *, output_dir, **_kwargs):
        media = Path(output_dir) / "resolved.mp4"
        media.write_bytes(b"x")
        return multimodal.DownloadedMedia(
            path=str(media),
            source_url=_source,
            mime_type="video/mp4",
            platform="generic",
            resolved_url="https://cdn.example.com/resolved.mp4",
            title="resolved",
        )

    async def fail_download(*_args, **_kwargs):
        raise AssertionError("download_remote_media should not be called when materialize succeeds")

    async def fake_analyze_local(**kwargs):
        return {
            "success": True,
            "seen_path": kwargs["media_path"],
            "frame_analyses": [],
            "transcript": {},
        }

    monkeypatch.setattr(multimodal, "materialize_remote_media_for_ffmpeg", fake_materialize)
    monkeypatch.setattr(multimodal, "download_remote_media", fail_download)
    monkeypatch.setattr(pipeline, "_analyze_local_media", fake_analyze_local)
    result = run(pipeline.analyze_media_source(media_source="https://example.com/video.mp4"))
    assert result["success"] is True
    assert result["download"]["resolved_url"] == "https://cdn.example.com/resolved.mp4"


def test_transcribe_webrtc_audio_chunk_empty_bytes_returns_failure():
    result = run(multimodal.transcribe_webrtc_audio_chunk(b"", mime_type="audio/webm"))
    assert result["success"] is False
    assert "Boş WebRTC ses paketi" in result["reason"]


def test_transcribe_webrtc_audio_chunk_uses_temp_file_and_adds_transport(monkeypatch):
    captured = {}

    async def fake_transcribe(path, **kwargs):
        captured["path"] = Path(path)
        captured["kwargs"] = kwargs
        return {
            "success": True,
            "provider": "whisper",
            "model": "tiny",
            "text": "ok",
            "segments": [],
        }

    monkeypatch.setattr(multimodal, "transcribe_audio", fake_transcribe)
    payload = b"webrtc-blob"
    result = run(
        multimodal.transcribe_webrtc_audio_chunk(
            payload,
            mime_type="audio/webm",
            model="tiny",
            language="tr",
            prompt="selam",
        )
    )
    assert result["success"] is True
    assert result["transport"] == "webrtc"
    assert result["mime_type"] == "audio/webm"
    assert result["bytes"] == len(payload)
    assert captured["path"].suffix == ".webm"
    assert captured["kwargs"]["language"] == "tr"
