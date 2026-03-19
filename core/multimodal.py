"""Sidar Project — Multimodal medya işleme yardımcıları.

Bu modül, v5.0 yol haritasındaki video/ses algı katmanının MVP temelini
oluşturur. Amaç; video dosyalarından frame çıkarmak, ses kanalını ayırmak,
Whisper benzeri bir STT akışıyla transkript üretmek ve bunları ortak bir
LLM bağlamına dönüştürmektir.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VIDEO_MIME_PREFIXES = ("video/",)
_AUDIO_MIME_PREFIXES = ("audio/",)
_IMAGE_MIME_PREFIXES = ("image/",)
_DEFAULT_MAX_MEDIA_BYTES = 50 * 1024 * 1024

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


def _guess_suffix(mime_type: str, fallback: str) -> str:
    return _MIME_SUFFIX_MAP.get((mime_type or "").lower(), fallback)


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
        self.stt_provider = str(getattr(config, "VOICE_STT_PROVIDER", "whisper") or "whisper")
        self.whisper_model = str(getattr(config, "WHISPER_MODEL", "base") or "base")

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

        source = Path(media_path)
        if not source.exists():
            return {"success": False, "reason": f"Medya dosyası bulunamadı: {source}"}
        if source.stat().st_size > self.max_media_bytes:
            return {"success": False, "reason": "Medya dosyası boyut limitini aşıyor"}

        media_kind = detect_media_kind(mime_type=mime_type, path=source)
        if media_kind == "image":
            from core.vision import VisionPipeline

            pipeline = VisionPipeline(self._llm, self._config)
            return await pipeline.analyze(image_path=str(source))

        transcript: dict[str, Any] | None = None
        frame_analyses: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory(prefix="sidar-multimodal-") as tmpdir:
            if media_kind == "video":
                audio_path = await extract_audio_track(source, output_path=Path(tmpdir) / "audio.wav")
                transcript = await transcribe_audio(
                    audio_path,
                    provider=self.stt_provider,
                    model=self.whisper_model,
                    language=language,
                    prompt=prompt,
                )

                with contextlib.suppress(Exception):
                    from core.vision import VisionPipeline

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
            "analysis": analysis,
        }