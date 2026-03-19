"""Sidar Project — Voice/TTS yardımcıları.

Text-to-Speech adaptörleri ve websocket tarafında kademeli ses yanıtı üretmek
için kullanılacak ortak yardımcı sınıfları içerir.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any


class _BaseTTSAdapter:
    provider = "base"

    @property
    def available(self) -> bool:
        return True

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        raise NotImplementedError


class _MockTTSAdapter(_BaseTTSAdapter):
    provider = "mock"

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        payload = (text or "").strip().encode("utf-8")
        return {
            "success": bool(payload),
            "audio_bytes": payload,
            "mime_type": "audio/mock",
            "provider": self.provider,
            "voice": voice,
            "reason": "" if payload else "Boş metin için TTS üretilmedi.",
        }


class _Pyttsx3Adapter(_BaseTTSAdapter):
    provider = "pyttsx3"

    def __init__(self) -> None:
        try:
            import pyttsx3  # noqa: F401

            self._import_error = ""
        except Exception as exc:  # pragma: no cover - opsiyonel bağımlılık
            self._import_error = str(exc)

    @property
    def available(self) -> bool:
        return not self._import_error

    def _synthesize_sync(self, text: str, voice: str) -> dict[str, Any]:
        import pyttsx3

        engine = pyttsx3.init()
        if voice:
            for candidate in engine.getProperty("voices") or []:
                candidate_id = str(getattr(candidate, "id", "") or "")
                candidate_name = str(getattr(candidate, "name", "") or "")
                if voice.lower() in candidate_id.lower() or voice.lower() in candidate_name.lower():
                    engine.setProperty("voice", candidate_id)
                    break

        with tempfile.TemporaryDirectory(prefix="sidar-tts-") as tmpdir:
            output = Path(tmpdir) / "speech.wav"
            engine.save_to_file(text, str(output))
            engine.runAndWait()
            audio_bytes = output.read_bytes() if output.exists() else b""
        try:
            engine.stop()
        except Exception:
            pass
        return {
            "success": bool(audio_bytes),
            "audio_bytes": audio_bytes,
            "mime_type": "audio/wav",
            "provider": self.provider,
            "voice": voice,
            "reason": "" if audio_bytes else "pyttsx3 çıktı üretemedi.",
        }

    async def synthesize(self, text: str, *, voice: str = "") -> dict[str, Any]:
        if not self.available:
            return {
                "success": False,
                "audio_bytes": b"",
                "mime_type": "audio/wav",
                "provider": self.provider,
                "voice": voice,
                "reason": self._import_error or "pyttsx3 kullanılamıyor.",
            }
        return await asyncio.to_thread(self._synthesize_sync, text, voice)


def _build_tts_adapter(provider: str) -> _BaseTTSAdapter:
    normalized = (provider or "auto").strip().lower()
    if normalized == "mock":
        return _MockTTSAdapter()
    if normalized == "pyttsx3":
        return _Pyttsx3Adapter()

    pyttsx3_adapter = _Pyttsx3Adapter()
    if pyttsx3_adapter.available:
        return pyttsx3_adapter
    return _MockTTSAdapter()


class VoicePipeline:
    """Websocket voice akışı için TTS adaptörü ve segmentleme yardımcıları."""

    INTERRUPT_EVENTS = {"speech_start", "speech", "user_speaking", "barge_in", "interrupt"}
    COMMIT_EVENTS = {"speech_end", "speech_ended", "end_of_turn", "silence", "vad_commit"}

    def __init__(self, config: Any = None) -> None:
        provider = str(getattr(config, "VOICE_TTS_PROVIDER", "auto") or "auto")
        self.voice = str(getattr(config, "VOICE_TTS_VOICE", "") or "")
        self.segment_chars = max(20, int(getattr(config, "VOICE_TTS_SEGMENT_CHARS", 48) or 48))
        self.vad_enabled = bool(getattr(config, "VOICE_VAD_ENABLED", True))
        self.vad_min_speech_bytes = max(256, int(getattr(config, "VOICE_VAD_MIN_SPEECH_BYTES", 1024) or 1024))
        self.duplex_enabled = bool(getattr(config, "VOICE_DUPLEX_ENABLED", True))
        self.vad_interrupt_min_bytes = max(
            128,
            int(getattr(config, "VOICE_VAD_INTERRUPT_MIN_BYTES", 384) or 384),
        )
        self.adapter = _build_tts_adapter(provider)
        self.provider = self.adapter.provider

    @property
    def enabled(self) -> bool:
        return bool(self.adapter.available)

    def extract_ready_segments(self, buffer: str, *, flush: bool = False) -> tuple[list[str], str]:
        text = str(buffer or "")
        if not text.strip():
            return [], ""

        if flush:
            return ([text.strip()] if text.strip() else []), ""

        segments: list[str] = []
        remainder = text
        boundary = re.compile(r"(?<=[.!?。！？\n])\s+")
        parts = boundary.split(text)
        if len(parts) > 1:
            built = []
            for part in parts[:-1]:
                chunk = part.strip()
                if chunk:
                    built.append(chunk)
            segments.extend(built)
            remainder = parts[-1]

        if len(remainder.strip()) >= self.segment_chars:
            segments.append(remainder.strip())
            remainder = ""

        return segments, remainder

    def should_commit_audio(self, buffered_bytes: int, *, event: str = "") -> bool:
        """Basit VAD benzeri karar: speech_end/silence olayı ve yeterli buffer varsa işle."""
        if not self.vad_enabled:
            return False
        normalized = str(event or "").strip().lower()
        if normalized not in self.COMMIT_EVENTS:
            return False
        return int(buffered_bytes or 0) >= self.vad_min_speech_bytes

    def should_interrupt_response(self, buffered_bytes: int, *, event: str = "") -> bool:
        """Full-duplex akışta yeni kullanıcı konuşması mevcut yanıtı kesmeli mi?"""
        if not self.vad_enabled or not self.duplex_enabled:
            return False
        normalized = str(event or "").strip().lower()
        if normalized not in self.INTERRUPT_EVENTS:
            return False
        return int(buffered_bytes or 0) >= self.vad_interrupt_min_bytes

    def build_voice_state_payload(
        self,
        *,
        event: str,
        buffered_bytes: int,
        sequence: int,
    ) -> dict[str, Any]:
        normalized = str(event or "").strip().lower() or "unknown"
        return {
            "voice_state": normalized,
            "buffered_bytes": max(0, int(buffered_bytes or 0)),
            "sequence": max(0, int(sequence or 0)),
            "vad_enabled": self.vad_enabled,
            "auto_commit_ready": self.should_commit_audio(buffered_bytes, event=normalized),
            "duplex_enabled": self.duplex_enabled,
            "interrupt_ready": self.should_interrupt_response(buffered_bytes, event=normalized),
            "tts_enabled": self.enabled,
        }

    async def synthesize_text(self, text: str) -> dict[str, Any]:
        normalized = (text or "").strip()
        if not normalized:
            return {
                "success": False,
                "audio_bytes": b"",
                "mime_type": "audio/mock",
                "provider": self.provider,
                "voice": self.voice,
                "reason": "Boş metin için TTS üretilmedi.",
            }
        return await self.adapter.synthesize(normalized, voice=self.voice)
