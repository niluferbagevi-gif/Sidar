"""Sidar Project — Multimodal medya işleme yardımcıları.

Bu modül, v5.0 yol haritasındaki video/ses algı katmanının MVP temelini
oluşturur. Amaç; video dosyalarından frame çıkarmak, ses kanalını ayırmak,
Whisper benzeri bir STT akışıyla transkript üretmek ve bunları ortak bir
LLM bağlamına dönüştürmektir.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import mimetypes
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from core.vision import VisionPipeline

logger = logging.getLogger(__name__)

_VIDEO_MIME_PREFIXES = ("video/",)
_AUDIO_MIME_PREFIXES = ("audio/",)
_IMAGE_MIME_PREFIXES = ("image/",)
_DEFAULT_MAX_MEDIA_BYTES = 50 * 1024 * 1024
_DEFAULT_REMOTE_DOWNLOAD_TIMEOUT = 120.0
_DEFAULT_YOUTUBE_TRANSCRIPT_TIMEOUT = 15.0

_MIME_SUFFIX_MAP = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


@dataclass(frozen=True)
class ExtractedFrame:
    """Videodan çıkarılan tekil frame bilgisi."""

    path: str
    timestamp_seconds: float


@dataclass(frozen=True)
class DownloadedMedia:
    path: str
    source_url: str
    mime_type: str
    platform: str
    resolved_url: str = ""
    title: str = ""


def detect_media_kind(*, mime_type: str | None = None, path: str | Path | None = None) -> str:
    """MIME tipi veya dosya yolundan medya türünü tahmin eder."""
    guessed_mime = (mime_type or "").strip().lower()
    if not guessed_mime and path is not None:
        guessed_mime = (mimetypes.guess_type(str(path))[0] or "").lower()

    if guessed_mime.startswith(_VIDEO_MIME_PREFIXES):
        return "video"
    if guessed_mime.startswith(_AUDIO_MIME_PREFIXES):
        return "audio"
    if guessed_mime.startswith(_IMAGE_MIME_PREFIXES):
        return "image"
    return "unknown"


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_subprocess(command: Sequence[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


def _run_subprocess_capture(command: Sequence[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return str(result.stdout or "")


def _guess_suffix(mime_type: str, fallback: str) -> str:
    return _MIME_SUFFIX_MAP.get((mime_type or "").lower(), fallback)


def is_remote_media_source(value: str | Path) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"}


def detect_video_platform(value: str) -> str:
    host = (urlparse(str(value or "")).netloc or "").lower()
    if host.endswith("youtu.be") or "youtube.com" in host:
        return "youtube"
    if "vimeo.com" in host:
        return "vimeo"
    if "loom.com" in host:
        return "loom"
    return "generic"


def extract_youtube_video_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text

    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""
    if "youtube.com" in host:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""
        match = re.match(r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})", parsed.path or "")
        if match:
            return match.group(1)
    return ""


def _normalize_youtube_transcript_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    lines: list[str] = []
    segments: list[dict[str, Any]] = []
    for item in events or []:
        if not isinstance(item, dict):
            continue
        pieces = item.get("segs") or []
        if not isinstance(pieces, list):
            continue
        text = "".join(html.unescape(str(piece.get("utf8") or "")) for piece in pieces if isinstance(piece, dict)).strip()
        if not text:
            continue
        start_ms = int(item.get("tStartMs") or 0)
        duration_ms = int(item.get("dDurationMs") or 0)
        lines.append(text)
        segments.append(
            {
                "start_seconds": round(start_ms / 1000, 3),
                "duration_seconds": round(duration_ms / 1000, 3),
                "text": text,
            }
        )
    return {"text": " ".join(lines).strip(), "segments": segments}


async def fetch_youtube_transcript(
    video_url_or_id: str,
    *,
    languages: tuple[str, ...] | None = None,
    timeout: float = _DEFAULT_YOUTUBE_TRANSCRIPT_TIMEOUT,
    http_client_factory: Any = None,
) -> dict[str, Any]:
    video_id = extract_youtube_video_id(video_url_or_id)
    if not video_id:
        return {"success": False, "reason": "Geçerli YouTube video id bulunamadı.", "video_id": ""}

    client_factory = http_client_factory or httpx.AsyncClient
    langs = tuple(languages or ("tr", "en"))
    async with client_factory(timeout=timeout, follow_redirects=True) as client:
        for language in langs:
            response = await client.get(
                f"https://www.youtube.com/api/timedtext?v={video_id}&lang={language}&fmt=json3"
            )
            if response.status_code >= 400:
                continue
            payload = response.json() if hasattr(response, "json") else {}
            events = payload.get("events") if isinstance(payload, dict) else []
            normalized = _normalize_youtube_transcript_events(events if isinstance(events, list) else [])
            if normalized["text"]:
                return {
                    "success": True,
                    "video_id": video_id,
                    "language": language,
                    "text": normalized["text"],
                    "segments": normalized["segments"],
                }

    return {
        "success": False,
        "video_id": video_id,
        "language": "",
        "text": "",
        "segments": [],
        "reason": "YouTube transcript bulunamadı veya boş döndü.",
    }


async def download_remote_media(
    source_url: str,
    *,
    output_dir: str | Path,
    http_client_factory: Any = None,
    timeout: float = _DEFAULT_REMOTE_DOWNLOAD_TIMEOUT,
) -> DownloadedMedia:
    if not is_remote_media_source(source_url):
        raise ValueError("Yalnızca http/https medya kaynakları destekleniyor.")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    platform = detect_video_platform(source_url)
    if platform == "youtube" and _command_exists("yt-dlp"):
        template = target_dir / "%(id)s.%(ext)s"
        command = ["yt-dlp", "--no-playlist", "-o", str(template), source_url]
        await asyncio.to_thread(_run_subprocess, command)
        files = sorted(path for path in target_dir.iterdir() if path.is_file())
        if not files:
            raise RuntimeError("yt-dlp çıktı dosyası üretmedi.")
        media_path = files[0]
        mime_type = mimetypes.guess_type(str(media_path))[0] or "video/mp4"
        return DownloadedMedia(
            path=str(media_path),
            source_url=source_url,
            mime_type=mime_type,
            platform=platform,
            resolved_url=source_url,
            title=media_path.stem,
        )

    client_factory = http_client_factory or httpx.AsyncClient
    async with client_factory(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(source_url)
        response.raise_for_status()
        mime_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
        parsed = urlparse(source_url)
        suffix = _guess_suffix(mime_type, Path(parsed.path).suffix or ".bin")
        file_name = Path(parsed.path).name or f"remote_media{suffix}"
        target_path = target_dir / file_name
        target_path.write_bytes(response.content)
        return DownloadedMedia(
            path=str(target_path),
            source_url=source_url,
            mime_type=mime_type or (mimetypes.guess_type(str(target_path))[0] or ""),
            platform=platform,
            resolved_url=source_url,
            title=Path(file_name).stem,
        )


async def resolve_remote_media_stream(
    source_url: str,
    *,
    prefer_video: bool = True,
) -> dict[str, Any]:
    """Uzak medya için FFmpeg'e verilebilecek çözülmüş stream URL bilgisini döndürür."""
    if not is_remote_media_source(source_url):
        raise ValueError("Yalnızca http/https medya kaynakları destekleniyor.")

    platform = detect_video_platform(source_url)
    if platform == "youtube" and _command_exists("yt-dlp"):
        info_command = ["yt-dlp", "--no-playlist", "--dump-single-json", source_url]
        metadata: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            raw = await asyncio.to_thread(_run_subprocess_capture, info_command)
            parsed = json.loads(raw or "{}")
            if isinstance(parsed, dict):
                metadata = parsed
        stream_command = ["yt-dlp", "--no-playlist", "-g", source_url]
        raw_streams = await asyncio.to_thread(_run_subprocess_capture, stream_command)
        stream_urls = [line.strip() for line in raw_streams.splitlines() if line.strip()]
        resolved_url = stream_urls[0] if stream_urls else source_url
        title = str(metadata.get("title") or "")
        mime_type = "video/mp4" if prefer_video else "audio/webm"
        return {
            "source_url": source_url,
            "resolved_url": resolved_url,
            "platform": platform,
            "mime_type": mime_type,
            "title": title,
            "metadata": metadata,
        }

    return {
        "source_url": source_url,
        "resolved_url": source_url,
        "platform": platform,
        "mime_type": "video/mp4" if prefer_video else "",
        "title": "",
        "metadata": {},
    }


async def materialize_remote_media_for_ffmpeg(
    source_url: str,
    *,
    output_dir: str | Path,
    mime_type: str | None = None,
    max_duration_seconds: float = 120.0,
) -> DownloadedMedia:
    """Uzak video stream'ini FFmpeg ile yerel analiz dosyasına dönüştürür."""
    if not _command_exists("ffmpeg"):
        return await download_remote_media(source_url, output_dir=output_dir)

    stream = await resolve_remote_media_stream(source_url, prefer_video=True)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = _guess_suffix(mime_type or str(stream.get("mime_type") or ""), ".mp4")
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", str(stream.get("title") or "").strip()).strip("_")
    file_name = safe_title or f"{stream.get('platform', 'remote')}_stream"
    target_path = target_dir / f"{file_name}{suffix}"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(stream.get("resolved_url") or source_url),
        "-t",
        str(max(1.0, float(max_duration_seconds or 120.0))),
        "-c",
        "copy",
        str(target_path),
    ]
    await asyncio.to_thread(_run_subprocess, command)
    resolved_mime = mime_type or str(stream.get("mime_type") or "") or (mimetypes.guess_type(str(target_path))[0] or "")
    return DownloadedMedia(
        path=str(target_path),
        source_url=source_url,
        mime_type=resolved_mime,
        platform=str(stream.get("platform") or detect_video_platform(source_url)),
        resolved_url=str(stream.get("resolved_url") or source_url),
        title=str(stream.get("title") or file_name),
    )


async def extract_video_frames(
    path: str | Path,
    *,
    strategy: str = "fixed-interval",
    interval_seconds: float = 5.0,
    max_frames: int = 6,
    output_dir: str | Path | None = None,
) -> list[ExtractedFrame]:
    """FFmpeg ile videodan örnek frame'ler çıkarır."""
    if strategy != "fixed-interval":
        raise ValueError("Şimdilik yalnızca 'fixed-interval' stratejisi destekleniyor.")
    if max_frames <= 0:
        return []
    if not _command_exists("ffmpeg"):
        raise RuntimeError("Video frame çıkarımı için ffmpeg gerekli.")

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Medya dosyası bulunamadı: {source}")

    target_dir = Path(output_dir) if output_dir else source.parent / f"{source.stem}_frames"
    target_dir.mkdir(parents=True, exist_ok=True)
    pattern = target_dir / "frame_%03d.jpg"

    fps = 1.0 / max(interval_seconds, 0.1)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"fps={fps}",
        "-frames:v",
        str(max_frames),
        str(pattern),
    ]
    await asyncio.to_thread(_run_subprocess, command)

    frames: list[ExtractedFrame] = []
    for index, frame_path in enumerate(sorted(target_dir.glob("frame_*.jpg"))):
        frames.append(ExtractedFrame(path=str(frame_path), timestamp_seconds=index * interval_seconds))
    return frames


async def extract_audio_track(
    path: str | Path,
    *,
    output_path: str | Path | None = None,
    sample_rate: int = 16_000,
) -> str:
    """FFmpeg ile medya dosyasından mono WAV ses kanalı çıkarır."""
    if not _command_exists("ffmpeg"):
        raise RuntimeError("Ses kanalı ayırmak için ffmpeg gerekli.")

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Medya dosyası bulunamadı: {source}")

    target = Path(output_path) if output_path else source.with_suffix(".wav")
    target.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(target),
    ]
    await asyncio.to_thread(_run_subprocess, command)
    return str(target)


async def transcribe_audio(
    path: str | Path,
    *,
    provider: str = "whisper",
    model: str = "base",
    language: str | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    """Whisper CLI üzerinden sesi metne döker."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {source}")

    provider_name = (provider or "whisper").strip().lower()
    if provider_name != "whisper":
        raise ValueError("MVP sürümünde yalnızca whisper sağlayıcısı destekleniyor.")

    if not _command_exists("whisper"):
        return {
            "success": False,
            "provider": provider_name,
            "model": model,
            "text": "",
            "segments": [],
            "language": language or "",
            "reason": "Whisper CLI bulunamadı.",
        }

    with tempfile.TemporaryDirectory(prefix="sidar-whisper-") as tmpdir:
        command = [
            "whisper",
            str(source),
            "--model",
            model,
            "--output_format",
            "json",
            "--output_dir",
            tmpdir,
        ]
        if language:
            command.extend(["--language", language])
        if prompt:
            command.extend(["--initial_prompt", prompt])

        try:
            await asyncio.to_thread(_run_subprocess, command)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
            logger.warning("Whisper transkripsiyon hatası: %s", stderr)
            return {
                "success": False,
                "provider": provider_name,
                "model": model,
                "text": "",
                "segments": [],
                "language": language or "",
                "reason": stderr.strip() or "Whisper komutu başarısız oldu.",
            }

        output_json = Path(tmpdir) / f"{source.stem}.json"
        if not output_json.exists():
            return {
                "success": False,
                "provider": provider_name,
                "model": model,
                "text": "",
                "segments": [],
                "language": language or "",
                "reason": "Whisper çıktı dosyası üretmedi.",
            }

        payload = json.loads(output_json.read_text(encoding="utf-8"))
        segments = payload.get("segments", [])
        return {
            "success": True,
            "provider": provider_name,
            "model": model,
            "text": (payload.get("text", "") or "").strip(),
            "segments": segments if isinstance(segments, list) else [],
            "language": payload.get("language", language or ""),
        }


async def transcribe_webrtc_audio_chunk(
    audio_bytes: bytes,
    *,
    mime_type: str = "audio/webm",
    provider: str = "whisper",
    model: str = "base",
    language: str | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    """WebRTC üzerinden gelen tarayıcı ses parçasını STT'ye uygun dosyaya dönüştürüp çözer."""
    payload = bytes(audio_bytes or b"")
    if not payload:
        return {
            "success": False,
            "provider": (provider or "whisper").strip().lower(),
            "model": model,
            "text": "",
            "segments": [],
            "language": language or "",
            "reason": "Boş WebRTC ses paketi.",
        }

    suffix = _guess_suffix(mime_type, ".webm")
    with tempfile.TemporaryDirectory(prefix="sidar-webrtc-audio-") as tmpdir:
        source = Path(tmpdir) / f"chunk{suffix}"
        source.write_bytes(payload)
        result = await transcribe_audio(
            source,
            provider=provider,
            model=model,
            language=language,
            prompt=prompt,
        )
    result["transport"] = "webrtc"
    result["mime_type"] = (mime_type or "").strip().lower()
    result["bytes"] = len(payload)
    return result


def build_multimodal_context(
    *,
    media_kind: str,
    transcript: dict[str, Any] | None = None,
    frame_analyses: Iterable[dict[str, Any]] | None = None,
    extra_notes: str = "",
) -> str:
    """Transkript ve frame analizlerinden tekil bağlam metni üretir."""
    lines = [f"Medya Türü: {media_kind}"]

    if transcript is not None:
        transcript_text = str(transcript.get("text", "") or "").strip()
        language = str(transcript.get("language", "") or "").strip()
        if transcript_text:
            lines.append("Transkript:")
            lines.append(transcript_text)
        elif transcript.get("reason"):
            lines.append(f"Transkript Durumu: {transcript['reason']}")
        if language:
            lines.append(f"Transkript Dili: {language}")

    frame_items = list(frame_analyses or [])
    if frame_items:
        lines.append("Frame Bulguları:")
        for item in frame_items:
            ts = float(item.get("timestamp_seconds", 0.0) or 0.0)
            summary = str(item.get("analysis", "") or item.get("summary", "") or "").strip()
            if summary:
                lines.append(f"- {ts:.1f}s: {summary}")

    if extra_notes.strip():
        lines.append("Ek Notlar:")
        lines.append(extra_notes.strip())

    return "\n".join(lines).strip()


def build_scene_summary(frame_analyses: Iterable[dict[str, Any]] | None = None) -> str:
    entries: list[str] = []
    for item in list(frame_analyses or []):
        summary = str(item.get("analysis", "") or item.get("summary", "") or "").strip()
        if not summary:
            continue
        ts = float(item.get("timestamp_seconds", 0.0) or 0.0)
        entries.append(f"{ts:.1f}s → {summary}")
    return " | ".join(entries)


def render_multimodal_document(
    analysis: dict[str, Any],
    *,
    source: str,
    title: str = "",
) -> tuple[str, str]:
    transcript = analysis.get("transcript") if isinstance(analysis, dict) else {}
    frame_analyses = analysis.get("frame_analyses") if isinstance(analysis, dict) else []
    resolved_title = title.strip() or f"Video İçgörü Özeti - {Path(str(source)).name or 'remote-source'}"
    body = [
        f"Kaynak: {source}",
        f"Medya Türü: {analysis.get('media_kind', 'video')}",
    ]
    download_info = analysis.get("download") if isinstance(analysis, dict) else {}
    if isinstance(download_info, dict):
        platform = str(download_info.get("platform", "") or "").strip()
        resolved_url = str(download_info.get("resolved_url", "") or "").strip()
        if platform:
            body.append(f"Platform: {platform}")
        if resolved_url and resolved_url != source:
            body.append(f"Çözümlenen Akış: {resolved_url}")
    transcript_text = str((transcript or {}).get("text", "") or "").strip()
    if transcript_text:
        body.extend(["", "Transkript Özeti:", transcript_text])
    scene_summary = build_scene_summary(frame_analyses)
    if scene_summary:
        body.extend(["", "Sahne Özeti:", scene_summary])
    analysis_text = str(analysis.get("analysis", "") or "").strip()
    if analysis_text:
        body.extend(["", "LLM İçgörüsü:", analysis_text])
    context_text = str(analysis.get("context", "") or "").strip()
    if context_text:
        body.extend(["", "Multimodal Bağlam:", context_text])
    return resolved_title, "\n".join(body).strip()


async def ingest_multimodal_analysis(
    document_store,
    analysis: dict[str, Any],
    *,
    source: str,
    session_id: str = "marketing",
    title: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if not analysis.get("success"):
        return {"success": False, "reason": "Başarısız analiz ingest edilemez."}
    resolved_title, content = render_multimodal_document(analysis, source=source, title=title)
    doc_id = await document_store.add_document(
        title=resolved_title,
        content=content,
        source=source,
        tags=list(tags or []),
        session_id=session_id,
    )
    return {"success": True, "doc_id": doc_id, "title": resolved_title, "content": content}


class MultimodalPipeline:
    """Video/ses/görsel dosyalarını ortak bir LLM bağlamına dönüştürür."""

    def __init__(self, llm_client, config=None) -> None:
        self._llm = llm_client
        self._config = config
        self.enabled = bool(getattr(config, "ENABLE_MULTIMODAL", True))
        self.max_media_bytes = int(
            getattr(config, "MULTIMODAL_MAX_FILE_BYTES", _DEFAULT_MAX_MEDIA_BYTES)
            or _DEFAULT_MAX_MEDIA_BYTES
        )
        self.remote_download_timeout = float(
            getattr(config, "MULTIMODAL_REMOTE_DOWNLOAD_TIMEOUT", _DEFAULT_REMOTE_DOWNLOAD_TIMEOUT)
            or _DEFAULT_REMOTE_DOWNLOAD_TIMEOUT
        )
        self.youtube_transcript_timeout = float(
            getattr(config, "YOUTUBE_TRANSCRIPT_TIMEOUT", _DEFAULT_YOUTUBE_TRANSCRIPT_TIMEOUT)
            or _DEFAULT_YOUTUBE_TRANSCRIPT_TIMEOUT
        )
        self.remote_video_max_seconds = float(
            getattr(config, "MULTIMODAL_REMOTE_VIDEO_MAX_SECONDS", 120.0) or 120.0
        )
        self.stt_provider = str(getattr(config, "VOICE_STT_PROVIDER", "whisper") or "whisper")
        self.whisper_model = str(getattr(config, "WHISPER_MODEL", "base") or "base")

    async def _analyze_local_media(
        self,
        *,
        media_path: str | Path,
        mime_type: str | None = None,
        prompt: str = "",
        frame_interval_seconds: float = 5.0,
        max_frames: int = 6,
        language: str | None = None,
        transcript_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = Path(media_path)
        if not source.exists():
            return {"success": False, "reason": f"Medya dosyası bulunamadı: {source}"}
        if source.stat().st_size > self.max_media_bytes:
            return {"success": False, "reason": "Medya dosyası boyut limitini aşıyor"}

        media_kind = detect_media_kind(mime_type=mime_type, path=source)
        if media_kind == "image":
            pipeline = VisionPipeline(self._llm, self._config)
            return await pipeline.analyze(image_path=str(source))

        transcript: dict[str, Any] | None = transcript_override
        frame_analyses: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(prefix="sidar-multimodal-") as tmpdir:
            if media_kind == "video":
                if transcript is None or not str(transcript.get("text", "") or "").strip():
                    audio_path = await extract_audio_track(source, output_path=Path(tmpdir) / "audio.wav")
                    transcript = await transcribe_audio(
                        audio_path,
                        provider=self.stt_provider,
                        model=self.whisper_model,
                        language=language,
                        prompt=prompt,
                    )

                vision = VisionPipeline(self._llm, self._config)
                frames = await extract_video_frames(
                    source,
                    interval_seconds=frame_interval_seconds,
                    max_frames=max_frames,
                    output_dir=Path(tmpdir) / "frames",
                )
                for frame in frames:
                    analysis = await vision.analyze(image_path=frame.path)
                    frame_analyses.append(
                        {
                            "timestamp_seconds": frame.timestamp_seconds,
                            "analysis": analysis.get("analysis", "") if isinstance(analysis, dict) else "",
                            "frame_path": frame.path,
                        }
                    )
            elif media_kind == "audio":
                transcript = await transcribe_audio(
                    source,
                    provider=self.stt_provider,
                    model=self.whisper_model,
                    language=language,
                    prompt=prompt,
                )
            else:
                return {"success": False, "reason": f"Desteklenmeyen medya türü: {media_kind}"}

        context = build_multimodal_context(
            media_kind=media_kind,
            transcript=transcript,
            frame_analyses=frame_analyses,
            extra_notes=prompt,
        )
        summary_prompt = (
            "Aşağıdaki multimodal bağlamı analiz et. "
            "Öne çıkan bulguları, riskleri ve önerilen aksiyonları kısa ama net maddeler halinde ver.\n\n"
            f"{context}"
        )
        analysis = await self._llm.chat(
            messages=[{"role": "user", "content": summary_prompt}],
            json_mode=False,
            stream=False,
        )
        return {
            "success": True,
            "media_kind": media_kind,
            "context": context,
            "transcript": transcript or {},
            "frame_analyses": frame_analyses,
            "scene_summary": build_scene_summary(frame_analyses),
            "analysis": analysis,
        }

    async def transcribe_bytes(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/webm",
        language: str | None = None,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Bellekteki ses baytlarını geçici dosyaya yazar ve transkribe eder."""
        if not self.enabled:
            return {"success": False, "reason": "ENABLE_MULTIMODAL devre dışı"}
        if not audio_bytes:
            return {"success": False, "reason": "Ses verisi boş"}
        if len(audio_bytes) > self.max_media_bytes:
            return {"success": False, "reason": "Ses verisi boyut limitini aşıyor"}

        suffix = _guess_suffix(mime_type, ".bin")
        with tempfile.TemporaryDirectory(prefix="sidar-voice-") as tmpdir:
            audio_path = Path(tmpdir) / f"voice_input{suffix}"
            audio_path.write_bytes(audio_bytes)
            return await transcribe_audio(
                audio_path,
                provider=self.stt_provider,
                model=self.whisper_model,
                language=language,
                prompt=prompt,
            )

    async def analyze_media(
        self,
        *,
        media_path: str,
        mime_type: str | None = None,
        prompt: str = "",
        frame_interval_seconds: float = 5.0,
        max_frames: int = 6,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Medya dosyasından multimodal özet üretir."""
        if not self.enabled:
            return {"success": False, "reason": "ENABLE_MULTIMODAL devre dışı"}
        return await self._analyze_local_media(
            media_path=media_path,
            mime_type=mime_type,
            prompt=prompt,
            frame_interval_seconds=frame_interval_seconds,
            max_frames=max_frames,
            language=language,
        )

    async def analyze_media_source(
        self,
        *,
        media_source: str,
        mime_type: str | None = None,
        prompt: str = "",
        frame_interval_seconds: float = 5.0,
        max_frames: int = 6,
        language: str | None = None,
        ingest_document_store=None,
        ingest_session_id: str = "marketing",
        ingest_title: str = "",
        ingest_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "reason": "ENABLE_MULTIMODAL devre dışı"}
        if not media_source.strip():
            return {"success": False, "reason": "media_source boş olamaz"}

        if not is_remote_media_source(media_source):
            result = await self._analyze_local_media(
                media_path=media_source,
                mime_type=mime_type,
                prompt=prompt,
                frame_interval_seconds=frame_interval_seconds,
                max_frames=max_frames,
                language=language,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="sidar-remote-media-") as tmpdir:
                download: DownloadedMedia | None = None
                if _command_exists("ffmpeg"):
                    with contextlib.suppress(Exception):
                        download = await materialize_remote_media_for_ffmpeg(
                            media_source,
                            output_dir=tmpdir,
                            mime_type=mime_type,
                            max_duration_seconds=self.remote_video_max_seconds,
                        )
                    if download is None:
                        download = await download_remote_media(
                            media_source,
                            output_dir=tmpdir,
                            timeout=self.remote_download_timeout,
                        )
                else:
                    download = await download_remote_media(
                        media_source,
                        output_dir=tmpdir,
                        timeout=self.remote_download_timeout,
                    )
                transcript_override = None
                if download.platform == "youtube":
                    languages = (language,) if language else None
                    transcript_override = await fetch_youtube_transcript(
                        media_source,
                        languages=languages,
                        timeout=self.youtube_transcript_timeout,
                    )
                result = await self._analyze_local_media(
                    media_path=download.path,
                    mime_type=mime_type or download.mime_type,
                    prompt=prompt,
                    frame_interval_seconds=frame_interval_seconds,
                    max_frames=max_frames,
                    language=language,
                    transcript_override=transcript_override,
                )
                result["download"] = {
                    "path": download.path,
                    "platform": download.platform,
                    "mime_type": download.mime_type,
                    "resolved_url": download.resolved_url,
                    "title": download.title,
                }
        result["media_source"] = media_source
        if ingest_document_store is not None and result.get("success"):
            result["document_ingest"] = await ingest_multimodal_analysis(
                ingest_document_store,
                result,
                source=media_source,
                session_id=ingest_session_id,
                title=ingest_title,
                tags=list(ingest_tags or []),
            )
        return result
